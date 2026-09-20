#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多渠道通知模块 (移植自 tendegree/wj-atuo 的 utils/notify.js, Python 版)

支持以下通知渠道（通过环境变量 / GitHub Secrets 配置，按需启用，可同时启用多个）：

  1. 企业微信机器人   WECOM_BOT_KEY          (webhook key)
  2. 钉钉机器人       DINGTALK_BOT_KEY       (+ 可选 DINGTALK_SECRET 加签)
  3. 飞书机器人       FEISHU_BOT_KEY         (webhook key)
  4. 云湖机器人       YUNHU_BOT_KEY          (webhook key)
  5. Server酱         SERVERCHAN_SENDKEY     (SendKey)
  6. PushPlus         PUSHPLUS_TOKEN         (+ 可选 PUSHPLUS_TOPIC)
  7. Telegram Bot     TG_BOT_TOKEN + TG_CHAT_ID
  8. Bark (iOS)       BARK_KEY               (+ 可选 BARK_GROUP)
  9. Discord Webhook  DISCORD_WEBHOOK        (完整 URL)
 10. 邮箱 SMTP        MAIL_HOST, MAIL_PORT, MAIL_USER, MAIL_PASS, MAIL_TO

仅依赖 requests + Python 标准库 (smtplib)。
"""

import os
import base64
import hmac
import hashlib
import time
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

import requests

TIMEOUT = 15


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{ts}] {msg}")


# ------------------------------------------------------------------
#  各渠道发送实现
# ------------------------------------------------------------------

# 1. 企业微信机器人
def send_wecom(title, content, key):
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    resp = requests.post(url, json={
        "msgtype": "text",
        "text": {"content": f"{title}\n\n{content}"},
    }, timeout=TIMEOUT)
    return resp.ok


# 2. 钉钉机器人（支持可选加签）
def send_dingtalk(title, content, key, secret=None):
    url = f"https://oapi.dingtalk.com/robot/send?access_token={key}"
    if secret:
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        sign = base64.b64encode(
            hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
        ).decode()
        url += f"&timestamp={timestamp}&sign={requests.utils.quote(sign, safe='')}"
    resp = requests.post(url, json={
        "msgtype": "markdown",
        "markdown": {"title": title, "text": f"### {title}\n\n{content}"},
    }, timeout=TIMEOUT)
    return resp.ok


# 3. 飞书机器人
def send_feishu(title, content, key):
    url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{key}"
    resp = requests.post(url, json={
        "msg_type": "text",
        "content": {"text": f"{title}\n\n{content}"},
    }, timeout=TIMEOUT)
    return resp.ok


# 4. 云湖机器人
def send_yunhu(title, content, key):
    url = f"https://www.yhchat.com/bot/send?key={key}"
    resp = requests.post(url, json={
        "msg": {"text": f"{title}\n\n{content}"},
    }, timeout=TIMEOUT)
    return resp.ok


# 5. Server酱 (sct)
def send_serverchan(title, content, sendkey):
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    resp = requests.post(url, data={"title": title, "desp": content}, timeout=TIMEOUT)
    return resp.ok


# 6. PushPlus
def send_pushplus(title, content, token, topic=None):
    url = "https://www.pushplus.plus/send"
    body = {"token": token, "title": title, "content": content, "template": "txt"}
    if topic:
        body["topic"] = topic
    resp = requests.post(url, json=body, timeout=TIMEOUT)
    return resp.ok


# 7. Telegram Bot
def send_telegram(title, content, bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": chat_id,
        "text": f"*{title}*\n\n{content}",
        "parse_mode": "Markdown",
    }, timeout=TIMEOUT)
    return resp.ok


# 8. Bark (iOS 推送)
def send_bark(title, content, key, group=None):
    base = key if key.startswith("http") else f"https://api.day.app/{key}"
    # safe='' 确保内容中的 / ? # 等全部被编码, 不破坏 URL 结构
    url = (f"{base}/{requests.utils.quote(title, safe='')}"
           f"/{requests.utils.quote(content, safe='')}")
    params = {}
    if group:
        params["group"] = group
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    return resp.ok


# 9. Discord Webhook
def send_discord(title, content, webhook_url):
    resp = requests.post(webhook_url, json={
        "content": f"**{title}**\n\n{content}"[:2000],
    }, timeout=TIMEOUT)
    return resp.ok


# 10. 邮箱 SMTP（标准库 smtplib，支持隐式 TLS 465 / STARTTLS 587）
def send_mail_smtp(title, content, host, port, user, password, to_addr):
    smtp_port = int(port) if port else 465
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = formataddr((str(Header("AgentRouter 签到通知", "utf-8")), user))
    msg["To"] = to_addr

    if smtp_port == 465:
        server = smtplib.SMTP_SSL(host, smtp_port, timeout=TIMEOUT)
    else:
        server = smtplib.SMTP(host, smtp_port, timeout=TIMEOUT)
    try:
        if smtp_port != 465:
            server.starttls()
        try:
            server.login(user, password)
        except smtplib.SMTPAuthenticationError:
            # 安全: 认证异常可能携带发件账号等信息, 不向外抛原始异常
            raise RuntimeError("SMTP 登录失败: 认证被拒绝, 请检查 MAIL_USER/MAIL_PASS")
        server.sendmail(user, [to_addr], msg.as_string())
    finally:
        try:
            server.quit()
        except Exception:
            pass
    return True


# ------------------------------------------------------------------
#  统一发送入口
# ------------------------------------------------------------------

def send_notify(title, content):
    """把通知发送到所有已配置的渠道。

    返回值:
      True  至少有一个渠道配置且全部发送成功
      False 未配置任何渠道 / 存在发送失败
    """
    channels = []

    env = os.environ
    if env.get("WECOM_BOT_KEY"):
        channels.append(("企业微信", lambda: send_wecom(title, content, env["WECOM_BOT_KEY"])))
    if env.get("DINGTALK_BOT_KEY"):
        channels.append(("钉钉", lambda: send_dingtalk(
            title, content, env["DINGTALK_BOT_KEY"], env.get("DINGTALK_SECRET") or None)))
    if env.get("FEISHU_BOT_KEY"):
        channels.append(("飞书", lambda: send_feishu(title, content, env["FEISHU_BOT_KEY"])))
    if env.get("YUNHU_BOT_KEY"):
        channels.append(("云湖", lambda: send_yunhu(title, content, env["YUNHU_BOT_KEY"])))
    if env.get("SERVERCHAN_SENDKEY"):
        channels.append(("Server酱", lambda: send_serverchan(title, content, env["SERVERCHAN_SENDKEY"])))
    if env.get("PUSHPLUS_TOKEN"):
        channels.append(("PushPlus", lambda: send_pushplus(
            title, content, env["PUSHPLUS_TOKEN"], env.get("PUSHPLUS_TOPIC") or None)))
    if env.get("TG_BOT_TOKEN") and env.get("TG_CHAT_ID"):
        channels.append(("Telegram", lambda: send_telegram(
            title, content, env["TG_BOT_TOKEN"], env["TG_CHAT_ID"])))
    if env.get("BARK_KEY"):
        channels.append(("Bark", lambda: send_bark(
            title, content, env["BARK_KEY"], env.get("BARK_GROUP") or None)))
    if env.get("DISCORD_WEBHOOK"):
        channels.append(("Discord", lambda: send_discord(title, content, env["DISCORD_WEBHOOK"])))
    if env.get("MAIL_HOST") and env.get("MAIL_USER") and env.get("MAIL_PASS") and env.get("MAIL_TO"):
        channels.append(("邮箱", lambda: send_mail_smtp(
            title, content,
            env["MAIL_HOST"], env.get("MAIL_PORT") or 465,
            env["MAIL_USER"], env["MAIL_PASS"], env["MAIL_TO"])))

    if not channels:
        return False

    log(f"正在发送通知到 {len(channels)} 个渠道: {', '.join(n for n, _ in channels)}")
    success, fail = 0, 0
    for name, fn in channels:
        try:
            if fn():
                log(f"  ✓ {name} 发送成功")
                success += 1
            else:
                log(f"  ✗ {name} 发送失败: HTTP 错误")
                fail += 1
        except Exception as e:
            # 安全: 请求异常的报文里可能含 webhook key / token / 推送内容,
            # 只输出异常类型, 不透传原始报文。
            log(f"  ✗ {name} 发送失败: {type(e).__name__}")
            fail += 1
    log(f"通知发送完成: {success} 成功, {fail} 失败")
    return success > 0 and fail == 0
