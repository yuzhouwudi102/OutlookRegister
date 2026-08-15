# OutlookRegister
[English](README_EN.md)
OutlookRegister 是一个基于 **Patchright / Playwright** 的 Outlook 邮箱注册自动化项目。程序可以并发执行注册流程、应用浏览器指纹、处理当前项目支持的验证页面，并在注册完成后获取 OAuth2 令牌。

项目还支持：

- 使用备用邮箱完成 Microsoft 安全验证。
- 通过 Microsoft Graph 自动读取备用邮箱验证码。
- 每个邮箱单独保存 OAuth JSON 令牌。
- 检查并刷新过期令牌，同时同步更新 `Results/outlook_token.txt`。
- Loop Creation（循环创建）模式：新注册邮箱成功后成为下一轮备用邮箱。
- HTTP、带账号密码的 HTTP、SOCKS5 代理格式解析。
- Patchright 与 Playwright 两种浏览器控制器。

> Microsoft 页面、选择器和验证流程可能发生变化。运行结果同时受网络、代理、账号状态及注册频率影响。

## 目录

- [功能概览](#功能概览)
- [运行环境](#运行环境)
- [安装](#安装)
- [快速开始](#快速开始)
- [Python 文件说明](#python-文件说明)
- [config.json 配置说明](#configjson-配置说明)
- [输入与输出文件](#输入与输出文件)
- [常用命令](#常用命令)
- [备用邮箱自动取码](#备用邮箱自动取码)
- [Loop Creation 模式](#loop-creation-模式)
- [令牌过期与刷新](#令牌过期与刷新)
- [代理格式](#代理格式)
- [常见问题](#常见问题)
- [测试](#测试)

## 功能概览

标准注册流程如下：

1. `main.py` 读取 `config.json`。
2. 根据 `choose_browser` 创建 Patchright 或 Playwright 控制器。
3. 按照 `concurrent_flows` 和 `max_tasks` 并发提交注册任务。
4. 自动生成邮箱名和强密码并填写注册页面。
5. 如果出现备用邮箱验证页面，选择已配置的备用邮箱并提交验证码。
6. 注册成功后，根据 `oauth2.enable_oauth2` 决定是否获取新邮箱 OAuth2 令牌。
7. 将账号或令牌写入 `Results` 目录。
8. Loop Creation 开启时，将新邮箱轮换为下一轮备用邮箱，并额外保存独立 JSON 令牌。

## 运行环境

- Windows 10/11。
- Python 3。
- Microsoft Edge、Chromium 或 Patchright 安装的 Chromium。
- 可访问 Microsoft 登录、Outlook 和 Microsoft Graph 的网络环境。

主要依赖：

```text
faker
requests
PySocks
playwright
patchright>=1.61.2
```

## 安装

以下示例使用 PowerShell。

### 1. 创建虚拟环境

```powershell
python -m venv .venv
```

### 2. 激活虚拟环境

```powershell
.\.venv\Scripts\Activate.ps1
```

如果不激活虚拟环境，后续命令可以直接使用：

```powershell
.venv\Scripts\python.exe
```

### 3. 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 4. 安装浏览器

使用 Patchright：

```powershell
patchright install chromium
```

使用 Playwright：

```powershell
playwright install chromium
```

也可以在 `playwright.browser_path` 中填写本机 Edge 或 Chromium 的绝对路径。

## 快速开始

### 1. 编辑 `config.json`

至少确认以下参数：

```json
{
  "choose_browser": "patchright",
  "email_suffix": "@outlook.com",
  "proxy": "http://127.0.0.1:7890",
  "concurrent_flows": 1,
  "max_tasks": 1
}
```

首次测试建议将并发和任务数都设为 `1`。

### 2. 准备备用邮箱

编辑 `Results/backup_email.txt`，每行格式：

```text
邮箱: 密码
```

示例：

```text
example@outlook.com: ExamplePassword123!
```

### 3. 授权备用邮箱

```powershell
python authorize_recovery_mailbox.py
```

### 4. 运行注册程序

```powershell
python main.py
```

## Python 文件说明

### 根目录脚本

| 文件 | 作用 |
| --- | --- |
| `main.py` | 项目主入口。读取配置、选择浏览器控制器、验证 Loop Creation 配置、并发执行注册、获取新邮箱 OAuth2 令牌并保存结果。 |
| `authorize_recovery_mailbox.py` | 独立授权备用邮箱。读取 `backup_email.txt`，找出尚未授权的邮箱，打开 Microsoft OAuth 页面并将令牌分别保存到 JSON 和 `outlook_token.txt`。 |
| `browser_fingerprint.py` | 创建浏览器指纹配置，包括视窗、语言、时区、WebGL、设备内存、CPU 核心数、User-Agent 和初始化脚本。 |
| `get_token.py` | 新邮箱注册完成后执行 OAuth2 授权码/PKCE 流程，返回 `refresh_token`、`access_token` 和过期时间。 |
| `proxy_utils.py` | 解析代理字符串，并分别生成 Playwright/Patchright 与 Requests 可用的代理格式。兼容 HTTP、SOCKS5 和账号密码。 |
| `recovery_mailbox.py` | 备用邮箱及令牌核心模块。负责邮箱列表、令牌 JSON、令牌刷新、Graph 邮件读取、验证码提取、Loop Creation 校验和 `outlook_token.txt` 更新。 |
| `refresh_recovery_tokens.py` | 独立检查 `recovery_mailbox_token` 中所有 JSON。令牌过期时逐个刷新，并立即同步更新 `outlook_token.txt` 中的对应邮箱。支持 `--dry-run`。 |
| `refresh_tokens.py` | 逐行检查 `Results/outlook_token.txt`，刷新其中已经过期的 OAuth2 令牌；主要处理 TXT 文件，不负责逐个 JSON 扫描。 |
| `utils.py` | 生成随机邮箱用户名和符合复杂度要求的随机密码。 |

### 浏览器控制器

| 文件 | 作用 |
| --- | --- |
| `controllers/base_controller.py` | Patchright 与 Playwright 的公共逻辑，包括浏览器上下文、指纹应用、模拟鼠标与输入、注册表单、备用邮箱验证、结果保存和资源清理。 |
| `controllers/patchright_controller.py` | 使用 Patchright 启动 Chromium，并实现当前项目的验证码处理流程。通常作为默认控制器。 |
| `controllers/playwright_controller.py` | 使用标准 Playwright 启动指定浏览器，并实现对应的验证码处理流程。可通过 `browser_path` 指定 Edge。 |

### Results 中的工具

| 文件 | 作用 |
| --- | --- |
| `Results/convert_outlook_token.py` | 将 `outlook_token.txt` 的五字段格式转换成 `邮箱----密码----client_id----refresh_token`，结果写入 `Results/output_token.txt`。 |

### 测试文件

| 文件 | 作用 |
| --- | --- |
| `tests/test_attempt_logging.py` | 检查注册尝试、成功和失败日志。 |
| `tests/test_browser_fingerprint.py` | 检查指纹配置、浏览器参数和有头模式。 |
| `tests/test_proxy_utils.py` | 检查 HTTP/SOCKS5 代理解析和输出格式。 |
| `tests/test_recovery_mailbox.py` | 检查备用邮箱、OAuth、Graph 取码、Loop Creation 和令牌保存。 |
| `tests/test_refresh_recovery_tokens.py` | 检查 JSON 过期判断、刷新及 `outlook_token.txt` 同步更新。 |
| `tests/test_signup_flow.py` | 检查注册页面选择器、日期选项和验证码流程结构。 |

## config.json 配置说明

### 顶层参数

| 参数 | 类型 | 作用 |
| --- | --- | --- |
| `choose_browser` | 字符串 | 选择浏览器控制器。可用值为 `patchright` 或 `playwright`。 |
| `email_suffix` | 字符串 | 注册邮箱后缀。当前流程支持 `@outlook.com` 和 `@hotmail.com`。 |
| `proxy` | 字符串/对象 | 浏览器和备用邮箱网络请求使用的代理。留空字符串表示不主动设置代理。格式见[代理格式](#代理格式)。 |
| `bot_protection_wait` | 数字 | 注册流程的基础等待时间，单位为秒。代码会按比例取其中一部分作为步骤等待时间。 |
| `max_captcha_retries` | 整数 | 验证码处理流程允许的最大重试次数。实际循环通常包含首次尝试。 |
| `concurrent_flows` | 整数 | 同时运行的注册任务数量。值越大，同时打开的浏览器上下文越多。 |
| `max_tasks` | 整数 | 本次运行计划提交的注册任务总数。 |
| `info` | 字符串 | 配置备注，仅供阅读，程序不会用它控制流程。 |

### `recovery_mailbox`

| 参数 | 类型 | 作用 |
| --- | --- | --- |
| `auto_fetch` | 布尔值 | `true` 时通过 Microsoft Graph 自动读取验证码；`false` 时只填写备用邮箱，验证码需要手动处理。 |
| `accounts_file` | 路径 | 备用邮箱账号列表，默认 `Results/backup_email.txt`。 |
| `token_dir` | 路径 | 每个邮箱独立 JSON 令牌的保存目录，默认 `Results/recovery_mailbox_token`。 |
| `legacy_token_cache` | 路径 | 旧版单文件令牌缓存。程序可将旧令牌迁移到独立 JSON 文件。 |
| `timeout_seconds` | 数字 | 自动等待验证码邮件的最长时间，单位为秒。 |
| `poll_interval_seconds` | 数字 | 查询 Graph 收件箱的轮询间隔，单位为秒。 |
| `message_lookback_seconds` | 数字 | 查询验证码时允许邮件时间早于请求时间的容差，单位为秒。 |
| `code_pattern` | 字符串 | 从邮件主题和正文中提取验证码的正则表达式。默认匹配独立的 6～8 位数字。JSON 中反斜杠需要写成 `\\`。 |

### `fingerprint`

| 参数 | 类型 | 作用 |
| --- | --- | --- |
| `enabled` | 布尔值 | 是否创建并应用浏览器指纹配置。关闭时使用较少的上下文覆盖。 |
| `headless` | 布尔值 | 指纹配置中的有头/无头意图字段。当前控制器实际固定使用 `headless=False`，修改该值不会开启无头运行。 |
| `locale` | 字符串 | 浏览器区域语言，例如 `en-US`。同时用于浏览器启动参数。 |
| `languages` | 字符串数组 | `navigator.languages` 和 `Accept-Language` 使用的语言顺序。 |
| `timezone_id` | 字符串 | 浏览器上下文时区，例如 `America/Los_Angeles`。 |
| `geolocation.longitude` | 数字 | 模拟地理位置的经度。 |
| `geolocation.latitude` | 数字 | 模拟地理位置的纬度。 |
| `geolocation.accuracy` | 数字 | 模拟地理位置精度，单位为米。配置后会向上下文授予定位权限。 |
| `color_scheme` | 字符串 | 页面颜色偏好，例如 `light`、`dark` 或 `no-preference`。 |
| `hardware_concurrency` | 整数数组 | 指纹生成时随机选择一个值作为逻辑 CPU 核心数。 |
| `device_memory` | 数字数组 | 指纹生成时随机选择一个值作为设备内存 GB 数。 |
| `device_scale_factor` | 数字数组 | 指纹生成时随机选择一个设备缩放比例。 |

视窗、屏幕大小、WebGL Vendor/Renderer 和 User-Agent 由 `browser_fingerprint.py` 的预设列表选择。

### `oauth2`

| 参数 | 类型 | 作用 |
| --- | --- | --- |
| `enable_oauth2` | 布尔值 | 是否为新注册邮箱获取 OAuth2 令牌。设为 `false` 时，成功账号写入 `Results/unlogged_email.txt`；备用邮箱流程仍可运行。 |
| `Loop Creation` | 布尔值 | 是否开启循环创建模式。开启时必须同时满足 `enable_oauth2=true` 且 `max_tasks` 等于备用邮箱数量。 |
| `client_id` | 字符串 | Microsoft Entra/Azure 应用的客户端 ID。备用邮箱授权与令牌刷新会使用该值。 |
| `redirect_url` | 字符串 | OAuth2 回调地址，必须与应用注册中配置的地址一致，例如 `http://localhost:8000`。 |
| `Scopes` | 字符串数组 | OAuth2 请求权限。`offline_access` 用于获取刷新令牌；Graph 邮件操作需要相应 Mail 权限。 |
| `token_file` | 可选路径 | `outlook_token.txt` 的自定义路径；未填写时使用 `Results/outlook_token.txt`。 |
| `loop_token_file` | 可选路径 | Loop Creation 使用的固定轮换令牌 JSON 路径；未填写时使用代码中的默认路径。 |

### `playwright`

| 参数 | 类型 | 作用 |
| --- | --- | --- |
| `browser_path` | 字符串 | `choose_browser=playwright` 时使用的浏览器可执行文件绝对路径。留空时使用 Playwright 安装的浏览器。 |

## 输入与输出文件

### `Results/backup_email.txt`

备用邮箱列表，每行一个：

```text
邮箱: 密码
```

Loop Creation 开启后，文件会被成功注册的新邮箱轮换覆盖。

### `Results/outlook_token.txt`

每行包含五个字段，分隔符为三个连字符：

```text
邮箱---密码---refresh_token---access_token---expires_at
```

其中 `expires_at` 是 Unix 时间戳。

### `Results/recovery_mailbox_token/*.json`

每个邮箱独立保存一个 JSON：

```json
{
  "email": "example@outlook.com",
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1780000000.0
}
```

文件名由邮箱可读部分和邮箱 SHA-256 摘要的前 10 位组成。访问令牌过期时，程序会使用 `refresh_token` 获取新令牌并覆盖原文件。

### 其他结果文件

| 文件 | 作用 |
| --- | --- |
| `Results/logged_email.txt` | OAuth2 流程成功并完成邮箱初始化的账号。 |
| `Results/unlogged_email.txt` | `enable_oauth2=false` 时注册成功的账号。 |
| `Results/output_token.txt` | `convert_outlook_token.py` 生成的转换格式令牌。 |
| `Results/recovery_mailbox_token.json` | 旧版单文件令牌缓存。 |

## 常用命令

以下命令应在项目根目录执行。

### 运行主程序

```powershell
python main.py
```

作用：按照 `config.json` 启动并发注册任务。

使用项目虚拟环境：

```powershell
.venv\Scripts\python.exe main.py
```

### 授权备用邮箱

```powershell
python authorize_recovery_mailbox.py
```

作用：逐个授权 `backup_email.txt` 中尚未拥有有效 JSON/刷新令牌的邮箱。

### 只检查 JSON 令牌是否过期

```powershell
python refresh_recovery_tokens.py --dry-run
```

作用：扫描全部 `recovery_mailbox_token/*.json`，显示哪些令牌未过期、哪些需要刷新，不修改任何文件。

### 刷新所有已过期 JSON 令牌

```powershell
python refresh_recovery_tokens.py
```

作用：逐个刷新已过期或 60 秒内将过期的 JSON；每刷新一个文件，立即同步更新 `outlook_token.txt` 中相同邮箱的令牌。

自定义提前刷新时间：

```powershell
python refresh_recovery_tokens.py --skew-seconds 300
```

作用：将 5 分钟内过期的令牌也视为需要刷新。

### 只刷新 `outlook_token.txt`

```powershell
python refresh_tokens.py
```

作用：逐行检查并刷新 TXT 中已过期的令牌。该脚本不会遍历每个 JSON 文件。

### 转换令牌格式

```powershell
python Results\convert_outlook_token.py
```

作用：读取 `Results/outlook_token.txt`，生成 `Results/output_token.txt`。

### 安装或更新依赖

```powershell
python -m pip install -r requirements.txt
```

### 编译检查 Python 文件

```powershell
python -m compileall -q .
```

### 运行全部测试

```powershell
python -m unittest discover -s tests -v
```

### 运行指定测试

```powershell
python -m unittest discover -s tests -p test_recovery_mailbox.py -v
python -m unittest discover -s tests -p test_refresh_recovery_tokens.py -v
python -m unittest discover -s tests -p test_proxy_utils.py -v
```

## 备用邮箱自动取码

启用条件：

```json
{
  "recovery_mailbox": {
    "auto_fetch": true
  }
}
```

流程：

1. 从 `backup_email.txt` 读取备用邮箱。
2. 优先选择已经拥有 JSON 授权令牌的邮箱。
3. 注册页面出现 “Let's protect your account” 时填写备用邮箱。
4. 确认页面已经进入验证码输入步骤。
5. 使用 Graph 轮询收件箱并提取验证码。
6. 自动填写并提交验证码。

如果访问令牌过期但存在 `refresh_token`，程序会自动刷新并写回 JSON。刷新令牌也失效时，需要再次运行：

```powershell
python authorize_recovery_mailbox.py
```

## Loop Creation 模式

配置示例：

```json
{
  "max_tasks": 3,
  "oauth2": {
    "enable_oauth2": true,
    "Loop Creation": true
  }
}
```

同时要求 `Results/backup_email.txt` 中正好有 3 个备用邮箱。

运行行为：

1. 每个任务按顺序绑定一个不同的备用邮箱。
2. 新邮箱注册并获取 OAuth2 令牌。
3. 将新邮箱账号写回 `backup_email.txt`。
4. 更新固定的 Loop Creation 令牌 JSON。
5. 在 `recovery_mailbox_token` 中为新邮箱额外写入独立 JSON。
6. 后续运行可以继续使用新邮箱作为备用邮箱。

以下任一条件不满足时，程序会在启动阶段退出：

- `oauth2.enable_oauth2` 必须为 `true`。
- `max_tasks` 必须等于备用邮箱数量。

## 令牌过期与刷新

程序以 `expires_at` 判断访问令牌是否有效，并预留 60 秒余量。

- `access_token` 未过期：直接使用。
- `access_token` 已过期且存在 `refresh_token`：请求新令牌并写回 JSON。
- Graph 返回 401：尝试使用 `refresh_token` 再刷新一次。
- 没有 `refresh_token` 或刷新被 Microsoft 拒绝：该邮箱需要重新授权。

建议先运行检查：

```powershell
python refresh_recovery_tokens.py --dry-run
```

确认后运行刷新：

```powershell
python refresh_recovery_tokens.py
```

## 代理格式

### 本地 HTTP 代理

```json
"proxy": "http://127.0.0.1:7890"
```

### 带账号密码的 HTTP 代理

标准 URL 格式：

```json
"proxy": "http://username:password@proxy.example.com:3010"
```

项目也能解析供应商常见格式：

```json
"proxy": "http://proxy.example.com:3010:username:password"
```

### SOCKS5 代理

```json
"proxy": "socks5://proxy.example.com:3010:username:password"
```

Requests 会转换为 `socks5h://username:password@host:port`。浏览器会生成对应的 Playwright/Patchright 代理配置。不同 Chromium 版本对带认证 SOCKS5 的支持可能不同，应先单独测试代理出口。

### 不设置代理

```json
"proxy": ""
```

## 常见问题

### 浏览器启动失败

检查：

- `choose_browser` 是否为 `patchright` 或 `playwright`。
- Patchright/Playwright 浏览器是否已安装。
- `playwright.browser_path` 是否指向真实的浏览器可执行文件。
- 代理字符串是否能被解析。

### 页面填写后一直停留在 Next

程序会先确认验证码输入框已经出现，然后才开始轮询邮件。如果 Next 点击未生效，日志会显示备用邮箱页面仍然可见或验证码输入框未出现。

### 自动取码超时

检查：

- `auto_fetch` 是否为 `true`。
- 备用邮箱 JSON 是否包含 `refresh_token`。
- `client_id` 和 `Scopes` 是否与授权时一致。
- Graph 网络请求是否能通过当前代理。
- `timeout_seconds` 是否足够。

### Loop Creation 启动时报配置错误

确认：

```text
enable_oauth2 = true
max_tasks = backup_email.txt 中的邮箱数量
```

### JSON 已更新但 outlook_token.txt 没更新

`refresh_recovery_tokens.py` 只有在 `outlook_token.txt` 中找到相同邮箱时才同步更新 TXT。没有对应记录时会输出：

```text
JSON 已更新；outlook_token.txt 中没有对应邮箱记录
```

## 测试

运行：

```powershell
python -m unittest discover -s tests -v
```

测试覆盖：

- 注册尝试日志。
- 指纹配置与浏览器启动参数。
- 代理解析。
- 备用邮箱 OAuth 授权。
- Graph 验证码提取与邮件匹配。
- Loop Creation 账号及令牌轮换。
- JSON 令牌刷新与 TXT 同步。
- 注册页面日期和多语言选择器。

## 运行提示

- 建议先使用 `concurrent_flows=1`、`max_tasks=1` 验证配置。
- 页面或选择器变化时，优先查看终端中第一个明确错误。
- `Results` 中的账号和令牌文件由程序持续更新。
- 修改配置后重新启动程序，已运行的浏览器实例不会自动读取新配置。
