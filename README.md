# AgentRouter 自动签到脚本 (GitHub Actions)

[AgentRouter](https://agentrouter.org) 每日自动签到脚本。签到 = 每日完成一次登录；登录响应 `checked_in=true` 即完成签到并下发当日额度。

> 仅支持**账号密码登录**（最稳）。脚本优先走账号密码，登录成功后会再读一次个人日志做端到端核验，确认签到真的成功了。社区里 `POST /api/user/checkin` 的旧脚本在本站已失效（返回 404）。

推送通知方式参考 [tendegree/wj-atuo](https://github.com/tendegree/wj-atuo) 的多渠道通知实现（`utils/notify.js` → Python 版 `utils/notify.py`）。

## ✨ 功能特点

- **全自动化**：GitHub Actions 每日定时执行，一次配置、长期有效。
- **多账号支持**：单变量 `AGENTROUTER_ACCOUNTS` 通吃单账号/多账号，支持备注名。
- **多渠道通知**：企业微信、钉钉、飞书、云湖、Server酱、PushPlus、Telegram、Bark、Discord、邮箱 SMTP，按需启用、可同时开启。
- **安全可靠**：账号与通知凭据全部走 GitHub Secrets，不落仓库。
- **端到端核验**：签到后回读个人日志确认「签到成功」记录，杜绝「登录成功但签到未触发」。

## 🔧 部署指南（GitHub Actions）

### 1. Fork 或克隆本项目

- 点击右上角 **Fork**，将项目复刻到你自己的 GitHub 账号下。
- **建议**：进入 Fork 后的仓库 `Settings`，将可见性设为 **私有 (Private)**。

### 2. 添加仓库 Secrets

进入 `Settings` → `Secrets and variables` → `Actions` → `New repository secret`：

#### `AGENTROUTER_ACCOUNTS`（必需）

单账号/多账号通用，格式：**`邮箱,密码,别名;邮箱,密码,别名;...`**

- 不同账号之间用 `;` 隔开，邮箱/密码/别名之间用 `,` 隔开；
- 别名（第三段）可选，用于在通知中区分账号；
- ⚠️ 密码中请勿包含 `,` `;` 分隔符。

格式示例（3 个账号，其中第 3 个带别名）：

```
a@example.com,password1;b@example.com,password2;c@example.com,password3,主号
```

### 📋 所有可配置变量总表

| 变量 | 配置类型 | 必填 | 说明 |
|---|---|---|---|
| `AGENTROUTER_ACCOUNTS` | Secret | ✅ | 账号列表，格式 `邮箱,密码,别名;邮箱,密码,别名;...`，别名可选 |
| `AGENTROUTER_BASE_URL` | Variable | 可选 | 站点地址，默认 `https://agentrouter.org`，备用 `https://ps.air-outer.com` |
| `AGENTROUTER_PROXY` | Secret | 可选 | 无法直连时填代理，如 `http://127.0.0.1:10808`（支持 URL 内嵌凭据，日志中会脱敏） |
| `AGENTROUTER_FORCE_IPV4` | Secret | 可选 | 容器有 IPv6 但无路由导致 `Network unreachable` 时，设为 `1` 强制走 IPv4 |
| `WECOM_BOT_KEY` | Secret | 可选 | 企业微信群机器人 Webhook 地址后的 `key` |
| `DINGTALK_BOT_KEY` | Secret | 可选 | 钉钉自定义机器人 `access_token` |
| `DINGTALK_SECRET` | Secret | 可选 | 钉钉机器人加签密钥，配置后自动加签 |
| `FEISHU_BOT_KEY` | Secret | 可选 | 飞书自定义机器人 Webhook 地址后的 `token` |
| `YUNHU_BOT_KEY` | Secret | 可选 | 云湖机器人 Webhook `key` |
| `SERVERCHAN_SENDKEY` | Secret | 可选 | Server酱 (sct) 的 `SendKey` |
| `PUSHPLUS_TOKEN` | Secret | 可选 | PushPlus Token |
| `PUSHPLUS_TOPIC` | Secret | 可选 | PushPlus 群组编码 |
| `TG_BOT_TOKEN` | Secret | 可选 | Telegram Bot Token（与 `TG_CHAT_ID` 同时配置才生效） |
| `TG_CHAT_ID` | Secret | 可选 | Telegram 接收通知的 Chat ID |
| `BARK_KEY` | Secret | 可选 | Bark (iOS) 设备 key 或完整推送地址 |
| `BARK_GROUP` | Secret | 可选 | Bark 分组 |
| `DISCORD_WEBHOOK` | Secret | 可选 | Discord Webhook 完整 URL |
| `MAIL_HOST` | Secret | 可选 | 邮箱 SMTP 服务器地址（与 `MAIL_USER`/`MAIL_PASS`/`MAIL_TO` 同时配置才生效） |
| `MAIL_PORT` | Secret | 可选 | SMTP 端口，默认 `465`（隐式 TLS）；`587` 走 STARTTLS |
| `MAIL_USER` | Secret | 可选 | 发件邮箱账号 |
| `MAIL_PASS` | Secret | 可选 | SMTP 密码/授权码 |
| `MAIL_TO` | Secret | 可选 | 收件邮箱 |

> 通知类变量全部可选，配置**一个或多个**你使用的渠道即可，所有渠道可同时启用；不配置任何通知渠道时，签到结果仅打印到 Actions 运行日志。

### 3. 启用并运行 Action

1. 进入仓库的 **`Actions`** 标签页，若提示工作流被禁用，点击 **Enable** 启用。
2. 左侧选择 **AgentRouter Daily Check-in**，点击 **Run workflow** 手动触发一次，验证配置是否正确。
3. 测试通过后，脚本将于**每天北京时间 09:30** 自动运行（可在 `.github/workflows/checkin.yml` 中修改 cron）。

> 注意：GitHub Actions 的 cron 依赖 GitHub 调度，高峰期可能有几分钟到半小时的延迟，属正常现象。仓库保活已由下方的 **Repository Keepalive** 工作流自动处理，无需人工干预。

## 🔄 仓库保活（Repository Keepalive）

GitHub Actions 的定时任务在仓库 **60 天无提交**后会被自动停用。本项目自带保活工作流 [`.github/workflows/keepalive.yml`](.github/workflows/keepalive.yml)：

- **触发时间**：每月 1 日北京时间 10:00（UTC `0 2 1 * *`），也支持手动 `Run workflow` 触发；
- **执行内容**：向 [KEEPALIVE.md](KEEPALIVE.md) 追加一行本次执行记录（执行时间 + Actions 运行链接），并以 `github-actions[bot]` 身份提交推送；
- **权限**：仅需 `contents: write`，提交者固定为官方 bot 账号，不涉及任何 Secrets。

记录示例（表格 newest 在上）：

| 执行时间（北京时间）          | 运行记录                                                      |
| ------------------- | --------------------------------------------------------- |
| 2026-10-01 10:03:12 | [#12547](https://github.com/your-repo/actions/runs/12547) |

> 若推送失败，通常是因为分支设了保护规则（禁止 bot 直接 push），可给 `github-actions[bot]` 放行或改用带审核的 PR 模式。

## 原理（已对线上接口实测）

向 `POST /api/user/login` 发送 `{username: 邮箱, password: 密码}`，服务端下发 session cookie，登录响应 `data.checked_in=true` 即签到成功，余额直接在 `data.quota` 中返回。密码是固定的，不像第三方会话 cookie 那样会过期，基本一劳永逸。

仅依赖 `requests`，无需浏览器自动化、无需解验证码。

## 签到核验（端到端保证）

登录返回 `checked_in=true` 只说明「当日签到已计入」，脚本还会再读一次个人日志接口 `GET /api/log/self/`（带 `New-API-User: <数字 uid>` 请求头）做二次确认：

- 在日志中找到 `type=4` 且内容含「签到成功」的记录（即控制台 `/console/log` 里的那条「每日签到成功，增加额度 …」），且时间在近 24 小时内，才会判定为 **日志已确认**；
- 若本次运行刚生成签到日志（数十秒内），判定为「本次运行已生成签到日志」，置信度最高；
- 若日志接口异常或找不到近期记录，仍会以登录结果为准，但会在汇总里提示「日志未确认」，此时建议手动到 `/console/log` 核对。

> 这是为了防止「登录接口成功了、但签到实际没触发」这类边界情况，确保每次跑完都能确定签到真的成功了。

## 🔒 日志防泄露设计

脚本在运行日志层面做了多层防泄露处理：

- **凭据只进 Secrets**：账号与通知凭据全部通过 GitHub Secrets 注入环境变量，仓库与 workflow 文件中不出现明文。
- **主动注册掩码**：GitHub 只自动掩码 Secret 的完整值，拆分后的单个邮箱/密码属于其子串。脚本启动时会用 `::add-mask::` 把每个账号的邮箱、密码逐一注册为日志掩码，即使异常信息带出这些子串，日志中也只显示 `***`。
- **异常信息脱敏**：所有落日志的异常统一经过脱敏——URL 中的 `user:pass@` 凭据段（如代理地址）会被替换为 `***:***@`；通知渠道失败只输出异常类型，不透传可能含 webhook key/token 的原始报文；SMTP 认证失败不携带发件账号信息。
- **解析失败不回显**：`AGENTROUTER_ACCOUNTS` 格式解析失败时仅提示序号，不打印账号原文。
- **最小化输出**：日志与通知中只显示账号备注名、签到结果与额度，不输出密码、Cookie 或完整请求。

> 建议：将 Fork 仓库设为 Private；不要在 workflow 中添加 `set -x` 或打印环境变量的调试步骤；调试时可开启 `ACTIONS_RUNNER_DEBUG`，但注意其会输出更详细的运行日志。

## 注意事项

- **账号密码方式基本一劳永逸**：密码不会像第三方会话 cookie 那样过期，最省心。
- 签到成功 ≠ 余额一定增加：实际发放额度由本站管理员按用户组配置的每日配额决定（普通用户可能为 0，但签到记录有效）。
- **安全提醒**：账号密码与通知凭据属于敏感信息，请仅通过 GitHub Secrets 配置，不要写进脚本或提交到仓库；建议将 Fork 仓库设为 Private。
- **免责声明**：本项目仅用于学习和技术研究，请在遵守目标网站用户协议的前提下使用。
