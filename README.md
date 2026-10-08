# Puter Auto-Register

Puter 注册流程自动化, 账号验证与 OpenAI 格式接口适配工具集.

[![Python](https://img.shields.io/badge/Python-3-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

项目包含 Linux 批处理脚本, Windows PowerShell 脚本, 邮件接收服务和本地 API 适配层. Python 脚本仅使用标准库, 无需安装 `requests` 等第三方 Python 包.

当前版本是需要手动配置的脚本集合. 注册接口, 验证要求和模型权限取决于 Puter 的实际响应. 本文按仓库实现说明功能, 不承诺固定模型数量, 免费额度, 注册成功率或单账号成本.

## 导航

- [功能与文件](#功能与文件)
- [运行环境](#运行环境)
- [注册流程配置](#注册流程配置)
- [邮件接收服务](#邮件接收服务)
- [OpenAI 格式适配层](#openai-格式适配层)
- [协议说明](#协议说明)
- [结果与数据存储](#结果与数据存储)
- [排查与已知限制](#排查与已知限制)

## 功能与文件

主流程依次执行注册, 邮箱确认, 手机验证和模型调用检查, 然后保存账号记录. 各步骤可能单独失败, 注册成功并不代表后续验证或模型调用成功.

| 文件 | 用途 |
| --- | --- |
| [puter_farm.py](puter_farm.py) | Linux 主程序, 通过 Xray 节点执行注册, 按已有记录补足可用账号目标 |
| [scan_nodes.py](scan_nodes.py) | 节点连通性与注册探测, 默认会尝试真实注册 |
| [finish_existing.py](finish_existing.py) | 处理源码中 `EXISTING` 列表里的已有账号, 补充验证并保存结果 |
| [puter_api_reg.py](puter_api_reg.py) | 直接请求注册接口, 不包含完整邮箱和手机验证流程 |
| [puter_sms.py](puter_sms.py) | 通过 SMSBower 请求号码, 执行手机验证和模型调用检查 |
| [mailhook.py](mailhook.py) | HTTP 邮件投递入口, 邮件查询接口与 JSONL 存储 |
| [putershim.py](putershim.py) | 将 Puter 模型接口转换为 OpenAI 格式的模型列表和聊天接口 |
| [test_yescaptcha.py](test_yescaptcha.py) | YesCaptcha 在线验证脚本 |
| [test_puter_token.py](test_puter_token.py) | Puter Token 与模型接口在线验证脚本 |
| [test_proxy_signup.py](test_proxy_signup.py) | 使用 sing-box 的代理注册实验脚本 |
| [test_rse_vmess.py](test_rse_vmess.py) | 使用 sing-box 的 VMess 节点实验脚本 |
| [windows/puter-batch.ps1](windows/puter-batch.ps1) | Windows 注册, 邮箱确认, 手机验证与模型调用检查 |
| [windows/puter-local-reg.ps1](windows/puter-local-reg.ps1) | Windows 本机注册脚本 |
| [windows/puter-helper.ps1](windows/puter-helper.ps1) | 启动本地网页, 通过 Puter SDK 登录并读取当前会话 Token |

`test_*.py` 是访问真实服务的实验脚本, 并非离线单元测试. 部分脚本在导入时就执行网络请求, 可能消耗余额或创建账号, 因此不适合直接用测试发现工具批量加载.

## 运行环境

| 组件 | 环境与依赖 |
| --- | --- |
| Python 脚本 | Python 3 与标准库; 仓库未提供 Python 版本兼容性测试矩阵 |
| Linux 主程序与扫描器 | Xray, `pkill`, 可写的 `/tmp` 与结果目录 |
| Windows 脚本 | Windows PowerShell, `curl.exe`; 浏览器助手还需要可加载 Puter SDK 的浏览器 |
| 代理实验脚本 | `test_proxy_signup.py` 与 `test_rse_vmess.py` 调用 sing-box |
| 注册相关服务 | 对应脚本所需的 YesCaptcha, SMSBower, 收信域名与邮件查询服务 |
| 本地适配层 | 已有 Puter Token, 能访问 Puter API 的网络 |

`puter_farm.py` 使用 Linux 绝对路径和 `pkill`, 不能仅替换 Xray 路径就作为原生 Windows 脚本运行. Windows 使用 `windows/` 下的对应入口. 邮件服务和适配层可独立于注册流程运行.

## 注册流程配置

### Linux 主程序

编辑 [puter_farm.py](puter_farm.py) 顶部配置. 这些值是源码常量, 当前没有统一配置文件或 `.env` 加载器.

| 配置 | 说明 |
| --- | --- |
| `RSE_SUB` | 节点订阅地址; 解析器匹配特定 Clash 风格 YAML 中的 VMess 节点, 并非通用订阅解析器 |
| `YES_KEY` | YesCaptcha API Key |
| `SB_KEY` | SMSBower API Key |
| `SB_SERVICE`, `SB_COUNTRY` | 短信服务与地区编码, 按服务商当前定义核对 |
| `DOMAIN` | 已配置收信的邮箱域名 |
| `MAIL_API` | 邮件查询服务基础地址, 脚本会追加 `/api/mails` |
| `XRAY` | Xray 可执行文件, 默认 `/usr/local/bin/xray` |
| `DB` | 账号 JSONL 文件, 默认 `/opt/mailhook/puter_accounts.jsonl` |

准备与系统架构匹配的 [Xray](https://github.com/XTLS/Xray-core/releases), 确保运行用户对 `DB` 的父目录有写权限. 主程序不会自动创建该目录.

以下命令在 Linux 仓库根目录执行, 使用默认 Xray 路径:

```bash
python3 --version
/usr/local/bin/xray version
python3 puter_farm.py
```

主程序唯一读取的环境变量是 `TARGET`, 默认值为 `10`. 它表示 JSONL 中 `claude` 为真的记录总目标数, 包含已有记录, 不是本次新增数量. 已达到目标时直接退出. 修改目标的示例:

```bash
TARGET=2 python3 puter_farm.py
```

当前主程序最多尝试 `缺口数量 × 25` 次, 达到次数上限后仍可能未完成目标. 计数来自保存的检测结果, 不会在启动时重新验证已有 Token.

### Windows 入口

在 [windows/puter-batch.ps1](windows/puter-batch.ps1) 顶部填写 `$YES_KEY`, `$SB_KEY`, `$DOMAIN`, `$MAIL_API`, 并设置 `$OUT_FILE` 为仓库外的可写路径. 各脚本配置独立, 修改 Python 配置不会同步到 PowerShell.

在仓库根目录打开 PowerShell:

```powershell
Get-Command curl.exe
& .\windows\puter-batch.ps1
```

按提示输入本次尝试次数, 默认 `10`. Windows 批处理不会根据已有文件补足成功数量. 仅注册可使用 `puter-local-reg.ps1`, 浏览器登录与会话 Token 读取可使用 `puter-helper.ps1`.

### 已有账号

`finish_existing.py` 读取源码中的 `EXISTING` 元组列表, 每项为邮箱, 密码和 Token. 配置邮件服务, 短信服务与 `DB` 后再运行. 已存在于 `DB` 的邮箱会被跳过, 因此它不会自动重试库中所有失败记录.

## 邮件接收服务

[mailhook.py](mailhook.py) 是 HTTP 收信后端, 本身不接收 SMTP 邮件. 完整链路需要域名邮件路由和转发 Worker. 仓库未包含 Cloudflare Email Worker 源码, DNS 配置或反向代理配置.

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MAIL_DOMAIN` | `yourdomain.xyz` | 收信域名 |
| `MAIL_LISTEN` | `127.0.0.1:8899` | HTTP 监听地址 |
| `MAIL_STORE` | `/var/lib/mailhook/inbox.jsonl` | 邮件保存路径, Windows 需改为本地可写路径 |
| `MAIL_HOOK_SECRET` | 空 | 非空时, 投递请求需携带匹配的 `X-Hook-Secret` |

Linux 启动示例, 将占位符替换为实际配置:

```bash
export MAIL_DOMAIN="example.com"
export MAIL_LISTEN="127.0.0.1:8899"
export MAIL_STORE="/var/lib/mailhook/inbox.jsonl"
export MAIL_HOOK_SECRET="REPLACE_WITH_A_RANDOM_SECRET"
python3 mailhook.py
```

转发端向 `POST /mailhook` 投递 JSON. 可使用 `to`, `subject`, `text`, `html` 字段, 或以 `to` 和 `raw` 提供原始邮件文本.

本机直接连接时, 注册脚本的 `MAIL_API` 可配置为 `http://127.0.0.1:8899`. 若使用原示例中的 `/mailapi` 前缀, 需由反向代理移除该前缀后再转发, 后端自身没有 `/mailapi` 路由.

邮件列表接口是 `GET /api/mails`, 通过 `Authorization: Bearer <邮箱地址的 Base64>` 选择邮箱. 该值是编码而非签名令牌, 不能作为身份认证. `/inbox` 和单封邮件查询也缺少访问控制. 对外接入需在网络或反向代理层限制访问, `MAIL_HOOK_SECRET` 只保护投递入口.

## OpenAI 格式适配层

[putershim.py](putershim.py) 使用一个 Puter Token 提供本地模型列表与聊天接口.

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PUTER_TOKEN` | 空 | 必填, 未设置时程序退出 |
| `PUTER_LISTEN` | `127.0.0.1:8893` | 本地监听地址 |
| `PUTER_ORIGIN` | `http://localhost:18999` | 上游请求的 `Origin`, 按 Token 来源配置 |
| `PUTER_CLAUDE_ONLY` | `1` | 模型列表只显示名称含 `claude` 的条目; 设为 `0` 显示完整列表 |

### 启动

Windows PowerShell 示例, 将 `$Python` 替换为实际 Python 可执行文件路径:

```powershell
$Python = 'C:\Path\To\python.exe'
$env:PUTER_TOKEN = 'YOUR_PUTER_TOKEN'
$env:PUTER_LISTEN = '127.0.0.1:8893'
& $Python .\putershim.py
```

### 检查与调用

服务启动后, 在另一个 PowerShell 窗口执行:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8893/health'
$models = Invoke-RestMethod 'http://127.0.0.1:8893/v1/models'
$models.data | Select-Object id
```

从返回列表选择模型 ID, 替换下面的占位符后调用:

```powershell
$body = @{
    model = 'MODEL_ID_FROM_LIST'
    messages = @(@{ role = 'user'; content = 'Hello' })
    stream = $false
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Uri 'http://127.0.0.1:8893/v1/chat/completions' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

支持的路由与边界:

| 接口 | 行为 |
| --- | --- |
| `GET /health` | 返回进程状态与 Token 是否已设置, 不验证 Token 有效性 |
| `GET /v1/models` | 查询上游模型列表, 非空结果缓存 600 秒; 列出的模型仍可能没有调用权限 |
| `POST /v1/chat/completions` | 转换 `model`, `messages`, `max_tokens` 与 `stream` |
| `POST /chat/completions` | 同一聊天处理入口的别名 |

`stream: true` 会先等待上游完整响应, 再将文本按每段 60 个字符包装为 SSE 事件, 最后发送 `[DONE]`. 这是响应格式适配, 不具备上游逐 Token 实时生成的延迟特性.

适配层未实现完整 OpenAI API, 包括工具调用, Responses API, Embeddings 和客户端 API Key 校验. 第三方客户端可将基础地址设为 `http://127.0.0.1:8893/v1`; 若客户端强制要求 API Key, 可填本地占位值, 上游实际使用的是 `PUTER_TOKEN`. 保持本机监听, 对外部署时另行配置认证.

## 协议说明

以下是现有脚本使用的请求结构, 用于理解代码与排查接口变化. 它们不是稳定性承诺, 服务端返回字段可能变化.

| 步骤 | 请求 | 关键内容 |
| --- | --- | --- |
| 注册 | `POST https://puter.com/signup` | 用户名, 邮箱, 密码, 验证信息; 后续使用响应中的 `token` |
| 发送确认邮件 | `POST https://api.puter.com/send-confirm-email` | Bearer Token, JSON 请求体 `{}` |
| 确认邮箱 | `GET https://puter.com/confirm-email-by-token?...` | 使用邮件中的完整确认链接 |
| 发送手机验证码 | `POST https://api.puter.com/send-confirm-phone` | Bearer Token, `phone` 与 `fingerprint` |
| 提交手机验证码 | `POST https://api.puter.com/confirm-phone` | Bearer Token, `code` |
| 查询模型或聊天 | `POST https://api.puter.com/drivers/call` | Bearer Token, 驱动名称, 方法与参数 |

### 注册请求示意

主程序向 `https://puter.com/signup` 发送 JSON, 并设置 `Content-Type: application/json`:

```json
{
  "username": "example_user",
  "email": "user@example.com",
  "password": "REPLACE_WITH_A_UNIQUE_PASSWORD",
  "referrer": "",
  "send_confirmation_code": false,
  "p102xyzname": "",
  "cf-turnstile-response": "TURNSTILE_TOKEN",
  "fingerprint": "0123456789abcdef0123456789abcdef"
}
```

主程序将 `p102xyzname` 留空, 并生成 32 位十六进制 `fingerprint`. 各独立注册脚本的字段不完全一致, 以对应实现为准. 响应中的邮箱, 手机或银行卡验证要求需分别处理.

### 模型请求示意

向 `https://api.puter.com/drivers/call` 发送以下 JSON, 并设置 `Authorization: Bearer <PUTER_TOKEN>` 和 `Content-Type: application/json`:

```json
{
  "interface": "puter-chat-completion",
  "driver": "ai-chat",
  "method": "complete",
  "args": {
    "messages": [{"role": "user", "content": "Hello"}],
    "model": "MODEL_ID_FROM_LIST"
  }
}
```

查询模型时使用相同的 `interface` 和 `driver`, 将 `method` 改为 `models`, `args` 改为 `{}`. 仓库部分脚本硬编码了 `claude-sonnet-5-5`, 该字符串的存在不代表当前账号或上游一定支持它, 使用前需核对实际模型列表与调用结果.

## 结果与数据存储

| 来源 | 默认输出 | 内容 |
| --- | --- | --- |
| `puter_farm.py`, `finish_existing.py` | `/opt/mailhook/puter_accounts.jsonl` | 每行一个账号 JSON 对象 |
| `puter_api_reg.py` | `/opt/mailhook/puter_accounts.txt` | 注册信息与截断响应, 不保证保存完整 Token |
| `scan_nodes.py` | `/opt/mailhook/puter_ok.txt` | 探测时创建的账号信息 |
| Windows 注册脚本 | `windows/puter_accounts.txt` | `----` 分隔的账号信息, 批处理额外记录验证结果 |
| `puter-helper.ps1` | 浏览器下载的 `puter_token.txt` | 当前会话 Token |
| `mailhook.py` | `MAIL_STORE` 指定的 JSONL | 收到的邮件内容 |

主程序记录包含 `email`, `password`, `token`, `egress`, `phone`, `claude`, `ts`. `phone` 与 `claude` 是脚本当次根据响应判断的结果, 不是服务端持续有效的状态证明; 当前记录没有独立的邮箱确认成功字段.

账号文件以明文保存密码和 Token. 将输出目录与公开仓库分离, 限制本地访问权限, 分享日志前删除凭据和邮件正文. 现有 `.gitignore` 未覆盖所有输出名称, 例如 `puter_accounts.txt` 与 `puter_token.txt`, 发布前需单独检查. 部分脚本会在日志中输出响应或 Token 前缀.

## 排查与已知限制

| 现象 | 检查项 |
| --- | --- |
| `xray` 或 `pkill` 不存在 | 确认平台, 可执行文件路径与依赖; Windows 使用对应 PowerShell 入口 |
| 写入结果时报目录不存在 | 创建已配置的结果父目录, 并核对运行用户写权限 |
| 解析不到节点 | 检查订阅返回格式; 当前解析器仅匹配部分 YAML 写法, 空列表会导致主流程失败 |
| 邮件查询为空或 404 | 检查域名路由, Worker 投递, `MAIL_API` 前缀与目标邮箱 |
| Token 已设置但调用失败 | `/health` 只检查非空; 核对 Token 有效性, Origin 和账号验证状态 |
| 模型不存在或无权限 | 使用实际模型列表, 检查账号权限与额度, 替换脚本中的硬编码模型 ID |
| HTTP 403 或注册被拒绝 | 保留脱敏后的响应与请求时间, 检查服务状态及账号限制; 不把 HTTP 客户端或 IP 类型视为已确定根因 |
| 短信或验证服务超时 | 检查服务余额, 返回错误, 号码状态与当前服务商配置 |
| SSE 首段等待较长 | 当前适配层需等待上游完整生成后才输出 SSE |

此前记录的浏览器验证失败, PowerShell 请求被拒绝和 sing-box TLS 错误缺少可复现环境与对照数据, 只能作为历史现象. 它们不能证明某种客户端必然失败, 某种网络必然可用, 或某项方案是唯一可行方案.

费用由第三方验证服务, 短信服务, 网络, 域名和 Puter 实际计费共同决定. 失败与重试也可能产生费用. 仓库未提供可复核的成本统计或成功率测试, 因此不提供固定报价或对话次数估算.

## 使用范围与许可证

在拥有授权的账号与测试环境中使用, 遵守 Puter 及各服务商的服务条款和适用法律, 不用于账号倒卖, 垃圾注册或服务滥用.

代码采用 [MIT License](LICENSE). 第三方服务的访问权限与使用规则不由本项目许可证授予.
