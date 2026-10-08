# Puter 自动注册机 · Puter Auto-Register

> 完整逆向 Puter.com 注册链路，实现全自动批量注册 + Claude 模型访问。
> 实测可跑通：**注册 → 邮箱确认 → 手机验证 → Claude 调用**

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

---

## 项目简介

[Puter](https://puter.com) 是一个开源互联网操作系统，其 **User-Pays** 模式提供免费的 AI 服务（含 63 个 Claude 模型）。本项目完整还原了其注册协议，实现全自动批量注册。

**核心成果**：
- ✅ 完整逆向 `puter.com/signup` API 协议
- ✅ 破解 Cloudflare Turnstile（YesCaptcha 打码）
- ✅ 邮箱确认链路（自有域名邮件服务器）
- ✅ 手机验证链路（SMSBower 接码，$0.004/号）
- ✅ 63 个 Claude 模型可用（`claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-4-5` …）
- ✅ OpenAI 兼容适配层（可直接接 CLIProxyAPI 等）

---

## 协议还原

### 1. 注册

```http
POST https://puter.com/signup
Content-Type: application/json

{
  "username": "yourname",
  "email": "you@example.com",
  "password": "YourPassword123!",
  "referrer": "",
  "send_confirmation_code": false,
  "p102xyzname": "",                      // 蜜罐字段，必须为空
  "cf-turnstile-response": "<turnstile token>",
  "fingerprint": "<32位hex>"
}
```

**成功响应**：
```json
{
  "proceed": true,
  "next_step": "complete",
  "token": "eyJhbGciOiJIUzI1NiIs...",     // Puter auth token
  "user": {
    "username": "...",
    "uuid": "...",
    "email_confirmed": false,
    "requires_email_confirmation": true,
    "requires_phone_verification": true,
    "requires_card_verification": false
  }
}
```

**关键点**：
- `fingerprint` 来自前端 `window.getDeviceFingerprint()`（32 位 hex）
- 端点就是 `https://puter.com/signup`（不是 `api.puter.com`）
- 响应头 `Set-Cookie: puter_auth_token=...`

### 2. 邮箱确认

```http
POST https://api.puter.com/send-confirm-email
Authorization: Bearer <token>
Content-Type: application/json

{}
```

邮件内容含确认链接：
```
https://puter.com/confirm-email-by-token?token=<uuid>&user_uuid=<uuid>
```

**GET 这个链接即可完成确认**（返回 "Success — Puter"）。

### 3. 手机验证

```http
POST https://api.puter.com/send-confirm-phone
Authorization: Bearer <token>
Content-Type: application/json

{"phone": "+12164958664", "fingerprint": "<hex>"}
```

响应：`{"channel":"rcs"}`

```http
POST https://api.puter.com/confirm-phone
Authorization: Bearer <token>
Content-Type: application/json

{"code": "859517"}
```

响应：`{"phone_verified":true}`

### 4. 调用 Claude

```http
POST https://api.puter.com/drivers/call
Authorization: Bearer <token>
Content-Type: application/json
User-Agent: puter-js/1.0
Origin: https://puter.com

{
  "interface": "puter-chat-completion",
  "driver": "ai-chat",
  "method": "complete",
  "args": {
    "messages": [{"role": "user", "content": "Hello"}],
    "model": "claude-sonnet-5-5"
  }
}
```

**可用 Claude 模型**（63 个，部分）：
```
claude-fable-5 / claude-fable-5-1
claude-haiku-4-5-20251001
claude-opus-4-5-20251101 / 4-6 / 4-7 / 4-8
claude-opus-5 / claude-opus-5-5 / claude-opus-5-fast
claude-sonnet-4-6 / claude-sonnet-5 / claude-sonnet-5-5
```

---

## 风控规律（实测）

| 环节 | 拦截条件 | 绕过方式 |
|---|---|---|
| **IP** | 机房 IP / Cloudflare IP 全拦 | **必须住宅 IP** |
| **IP 频率** | 单 IP 约 3-5 个/24h | 轮换住宅 IP |
| **Turnstile** | 无头浏览器无法渲染 | YesCaptcha `TurnstileTaskProxyless` |
| **账号评分** | ~50% 概率要银行卡 | 多试，重试到成功 |
| **邮箱** | 无 | 自有域名 + Cloudflare Email Routing |

**关键发现**：
- ❌ Chrome / Camoufox / patchright 都过不了 Turnstile（无头检测 + 脚本破坏）
- ✅ **打码平台是唯一可靠方案**
- ❌ sing-box 的 vmess 实现有 bug（`SSL: UNEXPECTED_EOF`）
- ✅ **xray 正常**

---

## 文件说明

| 文件 | 用途 |
|---|---|
| `puter_farm.py` | **主程序** · 批量注册机（节点轮换 + 全流程） |
| `scan_nodes.py` | 节点扫描器（找没被拉黑的住宅 IP） |
| `finish_existing.py` | 补齐已有账号（邮箱 + 手机） |
| `puter_sms.py` | 手机验证模块 |
| `puter_api_reg.py` | 纯 API 注册（需本机住宅 IP） |
| `putershim.py` | **Puter → OpenAI 兼容适配层** |
| `test_yescaptcha.py` | YesCaptcha 测试 |
| `test_puter_token.py` | Token 功能测试 |
| `windows/puter-batch.ps1` | Windows 本机批量注册 |
| `windows/puter-helper.ps1` | Puter Token 提取助手（浏览器） |

---

## 快速开始

### 1. 环境

```bash
pip install requests
# 需要 xray（不是 sing-box）
curl -L https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip -o xray.zip
unzip xray.zip -d /usr/local/bin/ && chmod +x /usr/local/bin/xray
```

### 2. 配置

编辑 `puter_farm.py` 顶部：

```python
RSE_SUB  = "你的住宅节点订阅"          # 需要住宅 IP 的代理订阅
YES_KEY  = "你的 YesCaptcha Key"       # https://yescaptcha.com
SB_KEY   = "你的 SMSBower Key"         # https://smsbower.app
DOMAIN   = "你的收信域名"              # 配 Cloudflare Email Routing
MAIL_API = "你的邮件 API"              # 自建 mailhook
```

### 3. 跑

```bash
python puter_farm.py          # 默认目标 10 个
TARGET=20 python puter_farm.py
```

---

## OpenAI 兼容层

`putershim.py` 把 Puter 包装成标准 OpenAI API：

```bash
export PUTER_TOKEN="eyJhbGciOiJIUzI1NiIs..."
export PUTER_LISTEN="127.0.0.1:8893"
python putershim.py
```

```bash
curl http://127.0.0.1:8893/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-5-5","messages":[{"role":"user","content":"你好"}]}'
```

支持 `/v1/models`、`/v1/chat/completions`（含 SSE 流式）。

**接 CLIProxyAPI**：
```yaml
openai-compatibility:
- name: puter
  base-url: http://127.0.0.1:8893/v1
  api-key-entries:
  - api-key: any
  models:
  - name: claude-sonnet-5-5
    alias: puter/claude-sonnet-5-5
  - name: claude-opus-5-5
    alias: puter/claude-opus-5-5
```

---

## 成本

| 项目 | 单价 |
|---|---|
| 接码（SMSBower） | $0.004 |
| Turnstile（YesCaptcha） | ~$0.001 |
| 邮箱（自有域名） | 免费 |
| **合计** | **~$0.005 / 账号** |

每个账号 = **1000 Credits**（约 600-2000 次 Claude 对话）

---

## 实测结果

```
✓ zwti4o6ec0@xxx.xyz   phone=True  claude=True
✓ zwenfszvvk@xxx.xyz   phone=True  claude=True
✗ zwlcf09e2l@xxx.xyz   phone=True  claude=False  (需银行卡)
✗ zw7zk21dco@xxx.xyz   phone=True  claude=False  (需银行卡)
```

**成功率**：约 50%（受账号级风控影响）

---

## 踩坑记录

### Turnstile 过不去
- ❌ headless Chrome — 不渲染 iframe
- ❌ headful + Xvfb — 同样不渲染
- ❌ Camoufox — 脚本全局暴露被破坏（`window.turnstile === undefined`）
- ❌ patchright — 同样不渲染
- ✅ **YesCaptcha 打码**（唯一可行）

### PowerShell 的坑
- ❌ `Invoke-WebRequest` → 403（会加 `Expect: 100-continue` 等头被 WAF 拦）
- ✅ **用 `curl.exe`**

### sing-box vs xray
- ❌ sing-box vmess → `SSL: UNEXPECTED_EOF_WHILE_READING`
- ✅ **xray 正常**

### 代理节点
- ❌ 机房 IP / Cloudflare Workers IP → Puter 全拦
- ✅ **住宅 IP 才行**（但机场共享住宅 IP 多半已被拉黑，需轮换）

---

## 免责声明

本项目仅供**安全研究与协议学习**使用。

使用者应遵守：
- Puter 的服务条款
- 所在地区法律法规
- 不得用于商业倒卖或滥用

作者不对任何滥用行为负责。

---

## License

MIT
