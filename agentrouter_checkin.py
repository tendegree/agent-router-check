#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgentRouter 自动签到脚本 (GitHub Actions)
站点: https://agentrouter.org

===== 原理 (已对线上接口逐项实测确认) =====
本站"签到"= 每日完成一次登录。仅支持账号密码登录:

  向 POST /api/user/login 发送 {username: 邮箱, password: 密码}
  -> 服务端下发 session cookie, 并在 data.checked_in=true 时发放当日额度
  -> 登录响应 data 里直接带 quota(余额), 无需额外查询。
  密码是固定的, 不像第三方会话 cookie 会过期, 基本一劳永逸。

登录成功后还会做一次端到端核验(见下), 确认 /console/log 里确实落了
"签到成功"日志, 才会报"日志已确认"。

===== 配置方式 =====
统一使用 AGENTROUTER_ACCOUNTS, 单账号多账号通用:

  AGENTROUTER_ACCOUNTS  必填. 格式: 邮箱,密码,别名;邮箱,密码,别名;...
    - 账号之间用 ; 隔开, 邮箱/密码/别名之间用 , 隔开
    - 别名为可选第三段, 用于通知中区分账号
    例: a@x.com,pwdA;b@x.com,pwdB;甲@x.com,pwdC,主号
    (密码中不要含 , ; 分隔符)

===== 推送通知 (可选) =====
参考 tendegree/wj-atuo 的多渠道通知方式, 通过环境变量按需启用, 可同时开启多个:
  企业微信 WECOM_BOT_KEY | 钉钉 DINGTALK_BOT_KEY(+DINGTALK_SECRET)
  飞书 FEISHU_BOT_KEY | 云湖 YUNHU_BOT_KEY | Server酱 SERVERCHAN_SENDKEY
  PushPlus PUSHPLUS_TOKEN(+PUSHPLUS_TOPIC) | Telegram TG_BOT_TOKEN+TG_CHAT_ID
  Bark BARK_KEY(+BARK_GROUP) | Discord DISCORD_WEBHOOK
  邮箱 SMTP MAIL_HOST/MAIL_PORT/MAIL_USER/MAIL_PASS/MAIL_TO
  详见 utils/notify.py 与 README。

===== GitHub Actions 定时 =====
  参见 .github/workflows/checkin.yml, 默认每天北京时间 9:30 运行一次,
  账号与通知配置均通过仓库 Secrets 注入。重复跑不会重复发额度,
  服务端按天去重。

===== 注意事项 =====
  * 账号密码方式无需担心 cookie 过期, 最省心。
  * 签到后默认做一次端到端核验: 读取 /api/log/self 个人日志, 确认存在 type=4、
    内容含"签到成功"的当日记录, 才会报"日志已确认", 避免"登录成功但签到未真正触发"。
  * 备用域名 ps.air-outer.com 与本域名功能一致, 如需可改 AGENTROUTER_BASE_URL。
  * 若运行环境无法直连(常见于需翻墙/容器 IPv6 问题):
    - 设 AGENTROUTER_FORCE_IPV4=1 强制走 IPv4 (海外服务器直连常见修复)
    - 或设 AGENTROUTER_PROXY 指向可达代理, 例 http://127.0.0.1:10808
      (Docker 同机用 http://host.docker.internal:10808; http 不通试 socks5://)
"""

import os
import sys
import re
import time
import random
import traceback

try:
    import requests
except ImportError:
    print("缺少依赖 requests, 请先执行: pip install requests")
    sys.exit(1)

# ---------- 基础配置 ----------
# 注意: GitHub Actions 中 vars.AGENTROUTER_BASE_URL 未配置时会被设为空字符串,
# 因此用 or 回退默认值, 而不是依赖 get 的 default 参数。
BASE_URL = (os.environ.get("AGENTROUTER_BASE_URL") or "https://agentrouter.org").rstrip("/")
LOGIN_PATH = "/api/user/login"
# 用户个人日志(控制台"使用日志"页), 需带 New-API-User: <数字 uid> 请求头
SELF_LOG_PATH = "/api/log/self/"
SELF_LOG_HEADER = "New-API-User"
CHECKIN_LOG_TYPE = 4  # 每日签到日志的 type 字段值
TIMEOUT = 20

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")

# ---------- 代理(可选) ----------
PROXY = os.environ.get("AGENTROUTER_PROXY", "").strip()
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None

# ---------- 强制 IPv4(可选) ----------
# 部分容器有 IPv6 地址但无 IPv6 默认路由, 解析到站点 IPv6 地址后连接直接报
# [Errno 101] Network unreachable 且不回退 IPv4。设 AGENTROUTER_FORCE_IPV4=1
# 可强制所有连接只走 IPv4。海外服务器能直连时一般无需代理。
if os.environ.get("AGENTROUTER_FORCE_IPV4", "").strip() in ("1", "true", "yes", "on"):
    import socket as _socket
    _orig_getaddrinfo = _socket.getaddrinfo
    def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, _socket.AF_INET, type, proto, flags)
    _socket.getaddrinfo = _getaddrinfo_ipv4

# 通知: 多渠道推送 (utils/notify.py, 参考 tendegree/wj-atuo),
# 按环境变量启用渠道; 未配置任何渠道时仅打印到日志。
try:
    from utils.notify import send_notify as _multi_send
except Exception:
    _multi_send = None


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{ts}] {msg}")


# 脱敏: 抹掉 URL 中的 user:pass@ 凭据段(如代理地址 http://user:pass@host:port)
_URL_CREDS_RE = re.compile(r"(?<=//)[^/@\s:]+:[^/@\s]+@")


def sanitize(text):
    """抹去文本中的 URL 内嵌凭据, 用于所有异常信息落日志之前。"""
    return _URL_CREDS_RE.sub("***:***@", str(text))


def safe_notify(title, content):
    # 多渠道推送: 配置了任一通知渠道环境变量即启用
    if _multi_send:
        try:
            if _multi_send(title, content):
                return
        except Exception as e:
            log(f"多渠道通知发送异常(不影响签到): {sanitize(e)}")
    # 兜底: 仅打印
    log(f"[通知] {title}\n{content}")


def extract_quota(payload):
    """从登录响应的 data 中提取余额字段。"""
    if isinstance(payload, dict):
        for k in ("quota", "remainder_quota", "balance"):
            if k in payload:
                return payload[k]
    return None


# ===================== 账号密码登录 =====================
def password_login(account):
    name = account.get("name", "默认账号")
    email = (account.get("email") or "").strip()
    password = (account.get("password") or "").strip()
    if not email or not password:
        return _result(name, "fail", "未配置 email/password, 跳过", None, None)

    log(f"====== 开始处理账号(账号密码登录): {name} ======")
    site = requests.Session()
    site.headers.update({
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Referer": f"{BASE_URL}/login",
        "Origin": BASE_URL,
    })
    site.proxies = PROXIES

    try:
        r = site.post(f"{BASE_URL}{LOGIN_PATH}",
                      json={"username": email, "password": password},
                      timeout=TIMEOUT)
    except Exception as e:
        return _result(name, "fail", f"登录请求异常: {sanitize(e)}", None, None)

    if "text/html" in r.headers.get("Content-Type", ""):
        return _result(name, "fail", "登录接口返回 HTML(可能被 WAF 拦截或路径变化)", None, None)

    try:
        j = r.json()
    except Exception:
        return _result(name, "fail", f"登录响应非 JSON: {r.text[:120]}", None, None)

    if not j.get("success"):
        return _result(name, "fail",
                       f"登录失败: {j.get('message') or r.text[:120]}", None, None)

    data = j.get("data") or {}
    checked_in = bool(data.get("checked_in"))
    username = data.get("username") or data.get("display_name") or email
    quota = extract_quota(data)
    uid = data.get("id")

    if checked_in:
        level, vdetail, _, _ = verify_checkin(site, uid)
        if level in ("new", "today"):
            status = "success"
            msg = f"签到成功，日志已确认（{vdetail}）"
        else:
            status = "success"
            msg = f"登录成功且服务端返回已签到，但日志未确认: {vdetail}"
    else:
        status = "success"
        msg = "登录成功，但 checked_in=false(可能今日额度已发或接口变化)"

    return _result(name, status, msg, username, quota)


# ===================== 签到日志核验 =====================
def verify_checkin(session, uid, slack_new=300, window_days=1):
    """登录成功后调用: 查询 /api/log/self 确认是否真的产生了"签到成功"日志。

    端到端验证: 服务端登录返回 checked_in=true 只说明"当日签到已计入",
    但 /console/log 里会落一条 type=4、内容含"签到成功"的日志。比对这条日志
    可以排除"登录成功但签到未真正触发"的边界情况。

    返回 (level, detail, ts, content):
      level:
        "new"   本次运行刚生成了签到日志(created_at 在 slack_new 秒内)
        "today" 近 window_days 天内有签到日志(多半是今日更早时已完成签到)
        "none"  找不到任何签到日志 / 日志过旧
        "error" 日志接口异常(此时不应影响登录结论)
    """
    if not uid:
        return "error", "缺少 uid, 跳过日志核验", None, None
    try:
        r = session.get(f"{BASE_URL}{SELF_LOG_PATH}",
                        params={"p": 1, "page_size": 20},
                        headers={SELF_LOG_HEADER: str(uid)},
                        timeout=TIMEOUT)
        if r.status_code != 200 or "text/html" in r.headers.get("Content-Type", ""):
            return "error", f"日志接口返回 HTTP {r.status_code}", None, None
        items = (r.json().get("data") or {}).get("items") or []
    except Exception as e:
        return "error", f"日志查询异常: {sanitize(e)}", None, None

    now = int(time.time())
    newest_ts, newest_content = None, None
    for it in items:
        content = it.get("content") or ""
        if ("签到成功" in content) or (it.get("type") == CHECKIN_LOG_TYPE):
            ts = it.get("created_at")
            if isinstance(ts, (int, float)) and (newest_ts is None or ts > newest_ts):
                newest_ts, newest_content = ts, content

    if newest_ts is None:
        return "none", "日志中未找到任何签到记录", None, None

    ago = now - newest_ts
    if ago < 60:
        ago_str = f"{ago} 秒前"
    elif ago < 3600:
        ago_str = f"{int(ago / 60)} 分钟前"
    elif ago < 86400:
        ago_str = f"{int(ago / 3600)} 小时前"
    else:
        ago_str = f"{int(ago / 86400)} 天前"

    if newest_ts >= now - slack_new:
        return "new", f"本次运行已生成签到日志（{ago_str}）", newest_ts, newest_content
    if newest_ts >= now - window_days * 86400:
        return "today", f"近 {window_days} 天内有签到记录（{ago_str}），本次未新增", newest_ts, newest_content
    return "none", f"最近一条签到日志较旧（{ago_str}）", newest_ts, newest_content


# ===================== 调度 =====================
def do_checkin(account):
    email = (account.get("email") or "").strip()
    password = (account.get("password") or "").strip()
    if email and password:
        return password_login(account)
    return _result(account.get("name", "默认账号"), "fail",
                   "账号未配置 email/password, 跳过", None, None)


def _result(name, status, message, username, quota):
    res = {
        "name": name,
        "status": status,
        "message": message,
        "username": username or "",
        "quota": quota,
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }
    tag = {"success": "✅ 成功", "already": "🟡 已签到", "fail": "❌ 失败"}[status]
    quota_str = f"{quota}" if quota is not None else "未知"
    log(f"[{name}] {tag} | {message} | 额度: {quota_str}")
    return res


def collect_accounts():
    """解析 AGENTROUTER_ACCOUNTS (格式: 邮箱,密码,别名;邮箱,密码,别名;... 别名可选)"""
    accounts = _parse_accounts_text(os.environ.get("AGENTROUTER_ACCOUNTS", "").strip())
    if accounts:
        log(f"已读取 AGENTROUTER_ACCOUNTS 配置, 共 {len(accounts)} 个账号")
    else:
        log("未检测到有效账号配置: 请设置 AGENTROUTER_ACCOUNTS=邮箱,密码,别名;...")
    return accounts


def _parse_accounts_text(raw):
    """解析 '邮箱,密码,别名;邮箱,密码,别名;...' 文本格式。"""
    accounts = []
    for i, item in enumerate(raw.split(";")):
        item = item.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split(",", 2)]
        if (
            len(parts) < 2 or not parts[0] or not parts[1]
            or "@" not in parts[0] or parts[0].startswith(("[", "{"))
        ):
            # 安全: 不打印账号原文, 避免日志泄露邮箱/密码
            log(f"第 {i + 1} 个账号格式无效(应为 邮箱,密码[,别名]), 已跳过")
            continue
        accounts.append({
            "name": parts[2] if len(parts) > 2 and parts[2] else f"账号{i + 1}",
            "email": parts[0],
            "password": parts[1],
        })
    return accounts


def mask_github_actions(accounts):
    """在 GitHub Actions 中把各账号的邮箱/密码注册为日志掩码。

    GitHub 只自动掩码 Secret 的完整值; 拆分后的单个邮箱/密码属于其子串,
    不会被自动掩码。这里用 ::add-mask:: 主动注册, 即使后续异常信息或调试
    输出带出这些子串, 日志中也只显示 ***。
    """
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    masked = 0
    for acc in accounts:
        for v in (acc.get("email"), acc.get("password")):
            v = (v or "").strip()
            if len(v) >= 3 and not v.replace("@", "").isdigit():
                print(f"::add-mask::{v}")
                masked += 1
    if masked:
        log(f"已为 {masked} 项敏感信息注册 GitHub 日志掩码")


def main():
    log("AgentRouter 自动签到启动 (账号密码登录即签到)")

    accounts = collect_accounts()
    mask_github_actions(accounts)
    if not accounts:
        safe_notify("[AgentRouter] 签到失败", "未检测到账号配置, 请检查环境变量")
        return

    results = []
    for idx, acc in enumerate(accounts):
        try:
            res = do_checkin(acc)
            if res:
                results.append(res)
        except Exception:
            log(f"[{acc.get('name', '?')}] 处理异常:\n{sanitize(traceback.format_exc())}")
        if idx < len(accounts) - 1:
            time.sleep(random.uniform(2, 5))

    if not results:
        safe_notify("[AgentRouter] 签到失败", "所有账号均未成功执行")
        return

    lines = []
    for r in results:
        tag = {"success": "✅", "already": "🟡", "fail": "❌"}[r["status"]]
        quota_str = f"{r['quota']}" if r["quota"] is not None else "未知"
        who = r["username"] or r["name"]
        lines.append(f"{tag} {r['name']}({who})：{r['message']} | 额度 {quota_str}")
    safe_notify("[AgentRouter] 签到汇总", "\n".join(lines))
    log("全部账号处理完毕")


if __name__ == "__main__":
    main()
