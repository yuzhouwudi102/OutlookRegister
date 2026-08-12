import base64
import hashlib
import html
import json
import os
import re
import secrets
import string
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote

import requests

from browser_fingerprint import apply_runtime_overrides


TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
AUTHORIZE_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MESSAGES_ENDPOINT = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
DEFAULT_CODE_PATTERN = r"(?<!\d)(\d{6,8})(?!\d)"
DEFAULT_ACCOUNTS_FILE = "Results/backup_email.txt"
DEFAULT_TOKEN_DIR = "Results/recovery_mailbox_token"
DEFAULT_LEGACY_TOKEN_FILE = "Results/recovery_mailbox_token.json"


@dataclass(frozen=True)
class RecoveryMailboxAccount:
    email: str
    password: str = ""


def load_backup_accounts(path=DEFAULT_ACCOUNTS_FILE):
    path = Path(path)
    if not path.exists():
        return []

    accounts = []
    seen = set()
    for line_number, original_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = original_line.strip()
        if not line or line.startswith("#"):
            continue

        email, separator, password = line.partition(":")
        email = email.strip().lower()
        password = password.strip()
        if not separator or not email or "@" not in email:
            raise ValueError(
                f"{path} 第 {line_number} 行格式错误，应为：邮箱: 密码"
            )
        if email in seen:
            continue

        accounts.append(RecoveryMailboxAccount(email=email, password=password))
        seen.add(email)

    return accounts


def get_accounts_file(config):
    mailbox = config.get("recovery_mailbox", {})
    return Path(mailbox.get("accounts_file", DEFAULT_ACCOUNTS_FILE))


def get_token_dir(config):
    mailbox = config.get("recovery_mailbox", {})
    return Path(mailbox.get("token_dir", DEFAULT_TOKEN_DIR))


def token_file_for_email(token_dir, email):
    normalized = email.strip().lower()
    readable = re.sub(r"[^a-z0-9._-]+", "_", normalized)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    return Path(token_dir) / f"{readable}_{digest}.json"


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def migrate_legacy_token(config):
    mailbox = config.get("recovery_mailbox", {})
    legacy_path = Path(
        mailbox.get("legacy_token_cache", DEFAULT_LEGACY_TOKEN_FILE)
    )
    if not legacy_path.is_file():
        return None

    token = _read_json(legacy_path)
    email = token.get("email", "").strip().lower()
    if not email:
        return None

    destination = token_file_for_email(get_token_dir(config), email)
    if not destination.exists():
        _atomic_write_json(destination, token)
    return destination


def list_authorized_emails(config):
    migrate_legacy_token(config)
    token_dir = get_token_dir(config)
    if not token_dir.is_dir():
        return set()

    authorized = set()
    for path in token_dir.glob("*.json"):
        token = _read_json(path)
        email = token.get("email", "").strip().lower()
        access_token_valid = (
            token.get("access_token")
            and float(token.get("expires_at", 0)) > time.time() + 60
        )
        if email and (token.get("refresh_token") or access_token_valid):
            authorized.add(email)
    return authorized


def generate_code_verifier(length=128):
    alphabet = string.ascii_letters + string.digits + "-._~"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_code_challenge(code_verifier):
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def parse_graph_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


def message_text(message):
    body = message.get("body") or {}
    content = body.get("content", "") if isinstance(body, dict) else ""
    return html.unescape(
        "\n".join(
            (
                message.get("subject", ""),
                message.get("bodyPreview", ""),
                re.sub(r"<[^>]+>", " ", content),
            )
        )
    )


def extract_security_code(text, code_pattern=DEFAULT_CODE_PATTERN):
    if not text:
        return None

    keyword_patterns = (
        r"(?:security|verification|verify|single[- ]use|one[- ]time|code)"
        r"[^0-9]{0,100}([0-9]{4,8})",
        r"(?:验证码|安全代码|一次性代码|校验码)[^0-9]{0,100}([0-9]{4,8})",
    )
    for pattern in keyword_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)

    match = re.search(code_pattern, text)
    return match.group(1) if match else None


def find_code_in_messages(
    messages,
    requested_at,
    target_email="",
    code_pattern=DEFAULT_CODE_PATTERN,
    lookback_seconds=30,
):
    requested_at = requested_at.astimezone(timezone.utc)
    earliest = requested_at.timestamp() - float(lookback_seconds)
    target_email = target_email.lower().strip()

    candidates = []
    for message in messages:
        received_at = parse_graph_datetime(message.get("receivedDateTime"))
        if received_at is None or received_at.timestamp() < earliest:
            continue

        text = message_text(message)
        code = extract_security_code(text, code_pattern)
        if not code:
            continue

        target_match = bool(target_email and target_email in text.lower())
        candidates.append((target_match, received_at, code))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


class RecoveryMailboxClient:
    def __init__(self, config, proxy="", account=None):
        oauth2 = config.get("oauth2", {})
        mailbox = config.get("recovery_mailbox", {})

        if account is None:
            accounts = load_backup_accounts(get_accounts_file(config))
            if len(accounts) != 1:
                raise ValueError(
                    "必须向 RecoveryMailboxClient 指定一个备用邮箱账户"
                )
            account = accounts[0]
        elif isinstance(account, dict):
            account = RecoveryMailboxAccount(
                email=account.get("email", "").strip().lower(),
                password=account.get("password", "").strip(),
            )
        elif isinstance(account, str):
            account = RecoveryMailboxAccount(email=account.strip().lower())

        self.account = account
        self.email = account.email.strip().lower()
        self.password = account.password
        self.client_id = mailbox.get(
            "client_id",
            oauth2.get("client_id", ""),
        ).strip()
        self.redirect_url = mailbox.get(
            "redirect_url",
            oauth2.get("redirect_url", "http://localhost:8000"),
        ).strip()
        self.scopes = mailbox.get("scopes", oauth2.get("Scopes", []))
        self.token_dir = get_token_dir(config)
        self.token_cache = token_file_for_email(self.token_dir, self.email)
        self.timeout_seconds = float(mailbox.get("timeout_seconds", 180))
        self.poll_interval_seconds = float(
            mailbox.get("poll_interval_seconds", 3)
        )
        self.lookback_seconds = float(
            mailbox.get("message_lookback_seconds", 30)
        )
        self.code_pattern = mailbox.get(
            "code_pattern",
            DEFAULT_CODE_PATTERN,
        )
        self.proxy = proxy.strip()
        migrate_legacy_token(config)

    @property
    def proxies(self):
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}

    def _read_password(self):
        if self.password:
            return self.password
        env_password = os.environ.get("OUTLOOK_RECOVERY_PASSWORD", "").strip()
        if env_password:
            return env_password
        raise RuntimeError(
            f"backup_email.txt 中没有填写 {self.email} 的密码"
        )

    def _load_token(self):
        token = _read_json(self.token_cache)
        if token.get("email", "").strip().lower() != self.email:
            return {}
        return token

    def has_authorization(self):
        token = self._load_token()
        access_token_valid = (
            token.get("access_token")
            and float(token.get("expires_at", 0)) > time.time() + 60
        )
        return bool(token.get("refresh_token") or access_token_valid)

    def _save_token(self, token):
        payload = {
            "email": self.email,
            "access_token": token.get("access_token", ""),
            "refresh_token": token.get("refresh_token", ""),
            "expires_at": time.time() + float(token.get("expires_in", 0)),
        }
        _atomic_write_json(self.token_cache, payload)
        return payload

    def _request_token(self, data):
        response = requests.post(
            TOKEN_ENDPOINT,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            proxies=self.proxies,
            timeout=30,
        )
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"OAuth 返回了非 JSON 响应（HTTP {response.status_code}）"
            ) from exc
        if not response.ok or "access_token" not in result:
            detail = (
                result.get("error_description")
                or result.get("error")
                or response.status_code
            )
            raise RuntimeError(
                f"备用邮箱 OAuth 失败：{str(detail).splitlines()[0]}"
            )
        return result

    def _refresh_token(self, refresh_token):
        result = self._request_token(
            {
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": " ".join(self.scopes),
            }
        )
        if "refresh_token" not in result:
            result["refresh_token"] = refresh_token
        return self._save_token(result)

    def build_authorize_url(self, code_verifier):
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_url,
            "scope": " ".join(self.scopes),
            "response_mode": "query",
            "prompt": "select_account",
            "login_hint": self.email,
            "code_challenge": generate_code_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        return (
            f"{AUTHORIZE_ENDPOINT}?"
            + "&".join(
                f"{key}={quote(str(value), safe='')}"
                for key, value in params.items()
            )
        )

    def authorize_with_browser(
        self,
        browser,
        interactive=False,
        timeout_seconds=300,
        context_options=None,
        init_script=None,
        runtime_profile=None,
    ):
        if not self.email or not self.client_id or not self.scopes:
            raise RuntimeError("备用邮箱 OAuth 配置不完整")

        password = self._read_password()
        verifier = generate_code_verifier()
        authorize_url = self.build_authorize_url(verifier)
        context = browser.new_context(**(context_options or {}))
        if init_script:
            context._fingerprint_init_disposable = context.add_init_script(
                script=init_script
            )
        page = context.new_page()
        if init_script:
            page._fingerprint_init_disposable = page.add_init_script(
                script=init_script
            )
        if runtime_profile:
            def apply_profile():
                try:
                    apply_runtime_overrides(page, runtime_profile)
                except Exception:
                    pass

            page.on("domcontentloaded", apply_profile)
            page.on("load", apply_profile)
            apply_profile()
        captured_url = None

        def capture_redirect(request):
            nonlocal captured_url
            if self.redirect_url in request.url:
                captured_url = request.url

        page.on("request", capture_redirect)
        try:
            try:
                page.goto(
                    authorize_url,
                    timeout=30000,
                    wait_until="domcontentloaded",
                )
            except Exception:
                pass

            login_input = page.locator(
                'input[name="loginfmt"], input[type="email"]'
            ).first
            try:
                login_input.wait_for(state="visible", timeout=10000)
                login_input.fill(self.email)
                page.locator(
                    "#idSIButton9, button[type='submit'], input[type='submit']"
                ).first.click()
            except Exception:
                pass

            password_input = page.locator(
                'input[name="passwd"], input[type="password"]'
            ).first
            try:
                password_input.wait_for(state="visible", timeout=10000)
                password_input.fill(password)
                page.locator(
                    "#idSIButton9, button[type='submit'], input[type='submit']"
                ).first.click()
            except Exception:
                pass

            for selector in (
                '[data-testid="appConsentPrimaryButton"]',
                "#idSIButton9",
            ):
                button = page.locator(selector).first
                try:
                    button.wait_for(state="visible", timeout=5000)
                    button.click()
                except Exception:
                    continue

            if interactive:
                print(f"[等待授权] {self.email}")
                print("请在浏览器中完成安全验证和授权，并保持窗口打开。")

            deadline = time.time() + float(timeout_seconds)
            while time.time() < deadline and not captured_url:
                page.wait_for_timeout(250)
        finally:
            page.remove_listener("request", capture_redirect)
            context.close()

        if not captured_url:
            raise TimeoutError(
                f"{self.email} 在 {int(timeout_seconds)} 秒内没有完成 OAuth 授权"
            )

        query = parse_qs(captured_url.split("?", 1)[1])
        auth_code = query.get("code", [None])[0]
        if not auth_code:
            detail = query.get(
                "error_description",
                query.get("error", ["未知错误"]),
            )[0]
            raise RuntimeError(f"{self.email} OAuth 授权失败：{detail}")

        result = self._request_token(
            {
                "client_id": self.client_id,
                "code": auth_code,
                "redirect_uri": self.redirect_url,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
                "scope": " ".join(self.scopes),
            }
        )
        return self._save_token(result)

    def _authorize_with_browser(self, browser):
        return self.authorize_with_browser(
            browser,
            interactive=False,
            timeout_seconds=60,
        )

    def _get_access_token(self):
        token = self._load_token()
        if (
            token.get("access_token")
            and float(token.get("expires_at", 0)) > time.time() + 60
        ):
            return token["access_token"]
        if token.get("refresh_token"):
            token = self._refresh_token(token["refresh_token"])
            return token["access_token"]
        raise RuntimeError(
            f"{self.email} 尚未授权，请先运行 authorize_recovery_mailbox.py"
        )

    def _list_messages(self, access_token):
        response = requests.get(
            MESSAGES_ENDPOINT,
            params={
                "$top": "30",
                "$orderby": "receivedDateTime desc",
                "$select": "subject,bodyPreview,body,receivedDateTime,from",
            },
            headers={
                "Authorization": f"Bearer {access_token}",
                "Prefer": 'outlook.body-content-type="text"',
            },
            proxies=self.proxies,
            timeout=30,
        )
        if response.status_code == 401:
            return None
        try:
            result = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Graph 返回了非 JSON 响应（HTTP {response.status_code}）"
            ) from exc
        if not response.ok:
            detail = (result.get("error") or {}).get(
                "message",
                response.status_code,
            )
            raise RuntimeError(f"读取备用邮箱失败：{detail}")
        return result.get("value", [])

    def wait_for_code(self, requested_at, target_email=""):
        access_token = self._get_access_token()
        deadline = time.time() + self.timeout_seconds
        refreshed_after_401 = False

        while time.time() < deadline:
            messages = self._list_messages(access_token)
            if messages is None:
                if refreshed_after_401:
                    raise RuntimeError("备用邮箱访问令牌已失效")
                token = self._load_token()
                if not token.get("refresh_token"):
                    raise RuntimeError(
                        "备用邮箱访问令牌已失效且没有 refresh_token"
                    )
                access_token = self._refresh_token(
                    token["refresh_token"]
                )["access_token"]
                refreshed_after_401 = True
                continue

            code = find_code_in_messages(
                messages,
                requested_at=requested_at,
                target_email=target_email,
                code_pattern=self.code_pattern,
                lookback_seconds=self.lookback_seconds,
            )
            if code:
                return code
            time.sleep(self.poll_interval_seconds)

        raise TimeoutError(
            f"{self.email} 在 {int(self.timeout_seconds)} 秒内没有收到验证码"
        )
