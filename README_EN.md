# OutlookRegister

OutlookRegister is an Outlook mailbox registration automation project based on **Patchright / Playwright**. It can run registration flows concurrently, apply browser-fingerprint settings, handle the verification pages supported by this project, and obtain OAuth2 tokens after registration.

The project also supports:

- Using a recovery mailbox for Microsoft security verification.
- Reading recovery-mailbox verification codes automatically through Microsoft Graph.
- Storing a separate OAuth JSON token for each mailbox.
- Checking and refreshing expired tokens while synchronizing `Results/outlook_token.txt`.
- Loop Creation mode: successfully registered mailboxes become replacement recovery mailboxes for the next run.
- HTTP, authenticated HTTP, and SOCKS5 proxy parsing.
- Both Patchright and Playwright browser controllers.

> Microsoft pages, selectors, and verification flows can change. Results also depend on network conditions, proxies, account state, and registration frequency.

## Contents

- [Overview](#overview)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Python File Reference](#python-file-reference)
- [config.json Reference](#configjson-reference)
- [Input and Output Files](#input-and-output-files)
- [Common Commands](#common-commands)
- [Automatic Recovery-Mailbox Code Retrieval](#automatic-recovery-mailbox-code-retrieval)
- [Loop Creation Mode](#loop-creation-mode)
- [Token Expiration and Refresh](#token-expiration-and-refresh)
- [Proxy Formats](#proxy-formats)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)

## Overview

The standard registration flow is:

1. `main.py` reads `config.json`.
2. It creates a Patchright or Playwright controller according to `choose_browser`.
3. It submits registration tasks concurrently according to `concurrent_flows` and `max_tasks`.
4. It generates a mailbox name and strong password, then fills in the registration page.
5. If a recovery-mailbox verification page appears, it selects a configured recovery mailbox and submits its verification code.
6. After registration, `oauth2.enable_oauth2` determines whether to obtain an OAuth2 token for the new mailbox.
7. It writes accounts or tokens to the `Results` directory.
8. When Loop Creation is enabled, each fully successful mailbox replaces the recovery mailbox assigned to that task and also gets its own JSON token cache.

## Requirements

- Windows 10/11.
- Python 3.
- Microsoft Edge, Chromium, or the Chromium installed by Patchright.
- Network access to Microsoft sign-in, Outlook, and Microsoft Graph.

Main dependencies:

```text
faker
requests
PySocks
playwright
patchright>=1.61.2
```

## Installation

The examples below use PowerShell.

### 1. Create a virtual environment

```powershell
python -m venv .venv
```

### 2. Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

Without activation, use the environment's interpreter directly:

```powershell
.venv\Scripts\python.exe
```

### 3. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4. Install a browser

For Patchright:

```powershell
patchright install chromium
```

For Playwright:

```powershell
playwright install chromium
```

You can also set an absolute local Edge or Chromium executable path in `playwright.browser_path`.

## Quick Start

### 1. Edit `config.json`

At minimum, verify these values:

```json
{
  "choose_browser": "patchright",
  "email_suffix": "@outlook.com",
  "proxy": "http://127.0.0.1:7890",
  "concurrent_flows": 1,
  "max_tasks": 1
}
```

For the first test, set both concurrency and task count to `1`.

### 2. Prepare recovery mailboxes

Edit `Results/backup_email.txt`. Use one mailbox per line:

```text
email: password
```

Example:

```text
example@outlook.com: ExamplePassword123!
```

### 3. Authorize recovery mailboxes

```powershell
python authorize_recovery_mailbox.py
```

### 4. Run the registration program

```powershell
python main.py
```

## Python File Reference

### Root scripts

| File | Purpose |
| --- | --- |
| `main.py` | Main entry point. Reads configuration, selects a browser controller, validates Loop Creation settings, runs registration concurrently, obtains OAuth2 tokens, and stores results. |
| `authorize_recovery_mailbox.py` | Authorizes recovery mailboxes independently. Reads `backup_email.txt`, finds mailboxes without usable authorization, opens the Microsoft OAuth page, and saves tokens to JSON files and `outlook_token.txt`. |
| `browser_fingerprint.py` | Builds browser-fingerprint configuration, including viewport, languages, timezone, WebGL, device memory, CPU count, User-Agent, and initialization scripts. |
| `get_token.py` | Runs the OAuth2 authorization-code/PKCE flow after new-mailbox registration and returns `refresh_token`, `access_token`, and expiration time. |
| `proxy_utils.py` | Parses proxy strings and produces proxy formats for Playwright/Patchright and Requests. Supports HTTP, SOCKS5, and credentials. |
| `recovery_mailbox.py` | Core recovery-mailbox and token module. Handles mailbox lists, token JSON files, token refresh, Graph mail reading, verification-code extraction, Loop Creation validation, and `outlook_token.txt` updates. |
| `refresh_recovery_tokens.py` | Checks every JSON file in `recovery_mailbox_token`. Refreshes expired tokens one by one and immediately synchronizes the corresponding record in `outlook_token.txt`. Supports `--dry-run`. |
| `refresh_tokens.py` | Checks `Results/outlook_token.txt` line by line and refreshes expired OAuth2 tokens. It primarily handles the TXT file rather than scanning each JSON token. |
| `utils.py` | Generates random mailbox usernames and strong random passwords. |

### Browser controllers

| File | Purpose |
| --- | --- |
| `controllers/base_controller.py` | Shared Patchright/Playwright behavior: browser contexts, fingerprint application, simulated mouse and typing, registration form handling, recovery-mailbox verification, result storage, and cleanup. |
| `controllers/patchright_controller.py` | Starts Chromium with Patchright and implements the verification workflow used by this project. Usually the default controller. |
| `controllers/playwright_controller.py` | Starts the selected browser with standard Playwright and implements the corresponding verification workflow. It can use Edge through `browser_path`. |

### Tools in `Results`

| File | Purpose |
| --- | --- |
| `Results/convert_outlook_token.py` | Converts the five-field `outlook_token.txt` format to `email----password----client_id----refresh_token` and writes `Results/output_token.txt`. |

### Test files

| File | Purpose |
| --- | --- |
| `tests/test_attempt_logging.py` | Tests registration-attempt, success, and failure logs. |
| `tests/test_browser_fingerprint.py` | Tests fingerprint configuration, browser arguments, and headed mode. |
| `tests/test_proxy_utils.py` | Tests HTTP/SOCKS5 proxy parsing and output formats. |
| `tests/test_recovery_mailbox.py` | Tests recovery mailboxes, OAuth, Graph code retrieval, Loop Creation, and token persistence. |
| `tests/test_refresh_recovery_tokens.py` | Tests JSON expiration checks, refresh, and `outlook_token.txt` synchronization. |
| `tests/test_signup_flow.py` | Tests registration-page selectors, date options, and verification-flow structure. |

## config.json Reference

### Top-level settings

| Key | Type | Purpose |
| --- | --- | --- |
| `choose_browser` | string | Browser controller: `patchright` or `playwright`. |
| `email_suffix` | string | New-mailbox suffix. The current flow supports `@outlook.com` and `@hotmail.com`. |
| `proxy` | string/object | Proxy for browser traffic and recovery-mailbox network requests. An empty string means no explicit proxy. See [Proxy Formats](#proxy-formats). |
| `bot_protection_wait` | number | Base wait time in seconds for the registration flow. Code can use portions of this value for individual steps. |
| `max_captcha_retries` | integer | Maximum verification-flow retries. The actual loop normally includes the initial attempt. |
| `concurrent_flows` | integer | Number of registration tasks run at the same time. Higher values open more browser contexts. |
| `max_tasks` | integer | Total number of registration tasks planned for this run. |
| `info` | string | A human-readable configuration note; it does not control program flow. |

### `recovery_mailbox`

| Key | Type | Purpose |
| --- | --- | --- |
| `auto_fetch` | boolean | When `true`, Microsoft Graph retrieves verification codes automatically. When `false`, only the recovery mailbox is entered and the code must be handled manually. |
| `accounts_file` | path | Recovery-mailbox account list. Default: `Results/backup_email.txt`. |
| `token_dir` | path | Directory for one JSON token per mailbox. Default: `Results/recovery_mailbox_token`. |
| `legacy_token_cache` | path | Legacy single-file token cache. The program can migrate it to individual JSON files. |
| `timeout_seconds` | number | Maximum time, in seconds, to wait automatically for a verification email. |
| `poll_interval_seconds` | number | Microsoft Graph inbox polling interval in seconds. |
| `message_lookback_seconds` | number | Allowed age tolerance for messages that predate the code request. |
| `code_pattern` | string | Regular expression used to extract a code from message subjects and bodies. The default matches an isolated 6- to 8-digit number. Backslashes in JSON must be escaped as `\\`. |

### `fingerprint`

| Key | Type | Purpose |
| --- | --- | --- |
| `enabled` | boolean | Whether to create and apply browser-fingerprint configuration. When disabled, fewer context overrides are used. |
| `headless` | boolean | Headed/headless intent field in the fingerprint configuration. The current controllers use `headless=False`; changing this value does not enable headless execution. |
| `locale` | string | Browser locale, for example `en-US`; also used for browser launch arguments. |
| `languages` | array of strings | Language order for `navigator.languages` and `Accept-Language`. |
| `timezone_id` | string | Browser-context timezone, for example `America/Los_Angeles`. |
| `geolocation.longitude` | number | Longitude for simulated geolocation. |
| `geolocation.latitude` | number | Latitude for simulated geolocation. |
| `geolocation.accuracy` | number | Simulated geolocation accuracy in meters. Location permission is granted to the context when configured. |
| `color_scheme` | string | Color preference such as `light`, `dark`, or `no-preference`. |
| `hardware_concurrency` | array of integers | A random value is chosen as logical CPU core count while generating a fingerprint. |
| `device_memory` | array of numbers | A random value is chosen as device memory in GB while generating a fingerprint. |
| `device_scale_factor` | array of numbers | A random device scale factor is chosen while generating a fingerprint. |

Viewport and screen dimensions, WebGL vendor/renderer, and User-Agent are selected from preset lists in `browser_fingerprint.py`.

### `oauth2`

| Key | Type | Purpose |
| --- | --- | --- |
| `enable_oauth2` | boolean | Whether to obtain an OAuth2 token for each newly registered mailbox. When `false`, successful accounts are written to `Results/unlogged_email.txt`; the recovery-mailbox flow can still run. |
| `Loop Creation` | boolean | Enables Loop Creation. It requires `enable_oauth2=true` and `max_tasks` to equal the recovery-mailbox count. |
| `client_id` | string | Client ID of the Microsoft Entra/Azure application. Recovery authorization and token refresh use this value. |
| `redirect_url` | string | OAuth2 callback URL. It must match the application registration, for example `http://localhost:8000`. |
| `Scopes` | array of strings | OAuth2 permissions. `offline_access` obtains a refresh token; Graph mail operations require the applicable Mail permissions. |
| `token_file` | optional path | Custom `outlook_token.txt` path. Defaults to `Results/outlook_token.txt`. |
| `loop_token_file` | optional path | Fixed Loop Creation token JSON path. Defaults to the path defined in code. |

### `playwright`

| Key | Type | Purpose |
| --- | --- | --- |
| `browser_path` | string | Absolute browser executable path used when `choose_browser=playwright`. Leave empty to use Playwright's installed browser. |

## Input and Output Files

### `Results/backup_email.txt`

The recovery-mailbox list, one entry per line:

```text
email: password
```

With Loop Creation enabled, each task that completes registration and OAuth replaces only the recovery mailbox assigned to that task. Recovery mailboxes assigned to failed tasks remain in the file.

### `Results/outlook_token.txt`

Each line contains five fields separated by three hyphens:

```text
email---password---refresh_token---access_token---expires_at
```

`expires_at` is a Unix timestamp.

### `Results/recovery_mailbox_token/*.json`

Each mailbox has its own JSON file:

```json
{
  "email": "example@outlook.com",
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1780000000.0
}
```

The filename contains a readable mailbox portion plus the first 10 characters of the mailbox SHA-256 digest. When the access token expires, the program uses `refresh_token` to obtain a new token and overwrites the JSON file.

### Other result files

| File | Purpose |
| --- | --- |
| `Results/logged_email.txt` | Accounts that completed OAuth2 and mailbox initialization. |
| `Results/unlogged_email.txt` | Accounts registered successfully while `enable_oauth2=false`. |
| `Results/output_token.txt` | Converted tokens produced by `convert_outlook_token.py`. |
| `Results/recovery_mailbox_token.json` | Legacy single-file token cache. |

## Common Commands

Run these commands from the project root.

### Run the main program

```powershell
python main.py
```

Starts concurrent registration tasks according to `config.json`.

Using the project virtual environment:

```powershell
.venv\Scripts\python.exe main.py
```

### Authorize recovery mailboxes

```powershell
python authorize_recovery_mailbox.py
```

Authorizes, one by one, mailboxes in `backup_email.txt` that do not yet have a usable JSON/refresh token.

### Check JSON token expiration only

```powershell
python refresh_recovery_tokens.py --dry-run
```

Scans all `recovery_mailbox_token/*.json` files, reports which tokens are valid and which need refresh, and does not modify files.

### Refresh all expired JSON tokens

```powershell
python refresh_recovery_tokens.py
```

Refreshes tokens that have expired or will expire within 60 seconds. After each refresh, it immediately updates the matching mailbox in `outlook_token.txt`.

Customize the early-refresh window:

```powershell
python refresh_recovery_tokens.py --skew-seconds 300
```

This treats tokens expiring within five minutes as requiring refresh.

### Refresh only `outlook_token.txt`

```powershell
python refresh_tokens.py
```

Checks and refreshes expired TXT records line by line. This script does not traverse individual JSON token files.

### Convert token format

```powershell
python Results\convert_outlook_token.py
```

Reads `Results/outlook_token.txt` and generates `Results/output_token.txt`.

### Install or update dependencies

```powershell
python -m pip install -r requirements.txt
```

### Compile-check Python files

```powershell
python -m compileall -q .
```

### Run all tests

```powershell
python -m unittest discover -s tests -v
```

### Run selected tests

```powershell
python -m unittest discover -s tests -p test_recovery_mailbox.py -v
python -m unittest discover -s tests -p test_refresh_recovery_tokens.py -v
python -m unittest discover -s tests -p test_proxy_utils.py -v
```

## Automatic Recovery-Mailbox Code Retrieval

Enable it with:

```json
{
  "recovery_mailbox": {
    "auto_fetch": true
  }
}
```

Flow:

1. Read recovery mailboxes from `backup_email.txt`.
2. Prefer mailboxes that already have authorized JSON tokens.
3. When the registration page shows "Let's protect your account", enter the recovery mailbox.
4. Confirm that the page has reached the verification-code input step.
5. Poll the inbox through Graph and extract the verification code.
6. Fill in and submit the code.

If the access token has expired but a `refresh_token` is available, the program refreshes and writes back the JSON automatically. If the refresh token has also expired, run:

```powershell
python authorize_recovery_mailbox.py
```

## Loop Creation Mode

Example configuration:

```json
{
  "max_tasks": 3,
  "oauth2": {
    "enable_oauth2": true,
    "Loop Creation": true
  }
}
```

`Results/backup_email.txt` must contain exactly three recovery mailboxes.

Run behavior:

1. Each task is assigned a different recovery mailbox.
2. A new mailbox is registered and obtains its OAuth2 token.
3. A task that completes both steps replaces its assigned recovery mailbox in `backup_email.txt`; a failed task leaves its assigned recovery mailbox in place.
4. The fixed Loop Creation token JSON is updated.
5. An extra per-mailbox JSON is written in `recovery_mailbox_token` for the new mailbox.
6. A later run can use the newly created mailbox as a recovery mailbox.

The program exits during startup unless both conditions are met:

- `oauth2.enable_oauth2` is `true`.
- `max_tasks` equals the recovery-mailbox count.

## Token Expiration and Refresh

The program uses `expires_at` to determine access-token validity and keeps a 60-second buffer.

- `access_token` is still valid: use it directly.
- `access_token` is expired and `refresh_token` exists: request a new token and write it to JSON.
- Graph returns 401: try one more refresh using `refresh_token`.
- No `refresh_token`, or Microsoft rejects refresh: the mailbox must be authorized again.

Check first:

```powershell
python refresh_recovery_tokens.py --dry-run
```

Then refresh:

```powershell
python refresh_recovery_tokens.py
```

## Proxy Formats

### Local HTTP proxy

```json
"proxy": "http://127.0.0.1:7890"
```

### Authenticated HTTP proxy

Standard URL form:

```json
"proxy": "http://username:password@proxy.example.com:3010"
```

The project also parses a common provider form:

```json
"proxy": "http://proxy.example.com:3010:username:password"
```

### SOCKS5 proxy

```json
"proxy": "socks5://proxy.example.com:3010:username:password"
```

Requests converts it to `socks5h://username:password@host:port`. The browser receives a corresponding Playwright/Patchright proxy configuration. Authenticated SOCKS5 support can vary by Chromium version, so test the proxy exit separately first.

### No explicit proxy

```json
"proxy": ""
```

## Troubleshooting

### Browser fails to start

Check:

- `choose_browser` is `patchright` or `playwright`.
- Patchright/Playwright browser binaries are installed.
- `playwright.browser_path` points to a real browser executable.
- The proxy string can be parsed.

### The page stays on Next after form entry

The program first confirms that the verification-code input is visible, then begins mailbox polling. If the Next click does not take effect, logs show whether the recovery-mailbox page remains visible or whether the code input did not appear.

### Automatic code retrieval times out

Check:

- `auto_fetch` is `true`.
- The recovery-mailbox JSON has `refresh_token`.
- `client_id` and `Scopes` match the values used during authorization.
- Graph network requests can use the current proxy.
- `timeout_seconds` is sufficient.

### Loop Creation exits with a configuration error

Verify:

```text
enable_oauth2 = true
max_tasks = number of mailboxes in backup_email.txt
```

### JSON was updated but `outlook_token.txt` was not

`refresh_recovery_tokens.py` synchronizes a TXT record only when it finds the same mailbox in `outlook_token.txt`. If no matching record exists, it prints:

```text
JSON updated; no matching mailbox record exists in outlook_token.txt
```

## Tests

Run:

```powershell
python -m unittest discover -s tests -v
```

Coverage includes:

- Registration-attempt logging.
- Fingerprint configuration and browser launch arguments.
- Proxy parsing.
- Recovery-mailbox OAuth authorization.
- Graph verification-code extraction and mail matching.
- Loop Creation account and token rotation.
- JSON token refresh and TXT synchronization.
- Registration-page date and multilingual selectors.

## Runtime Notes

- Start by validating configuration with `concurrent_flows=1` and `max_tasks=1`.
- When pages or selectors change, inspect the first explicit error in the terminal.
- Account and token files under `Results` are updated continuously by the program.
- Restart the program after changing configuration; browser instances that are already running do not reload it automatically.