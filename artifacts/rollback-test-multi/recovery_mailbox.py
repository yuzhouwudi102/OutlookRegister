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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote

import requests


TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
AUTHORIZE_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MESSAGES_ENDPOINT = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
DEFAULT_CODE_PATTERN = r"(?<!\d)(\d{6,8})(?!\d)"


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
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
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
    def __init__(self, config, proxy=""):
        oauth2 = config.get("oauth2", {})
        mailbox = config.get("recovery_mailbox", {})

        self.email = config.get("recovery_email", "").strip()
        self.client_id = mailbox.get("client_id", oauth2.get("client_id", "")).strip()
        self.redirect_url = mailbox.get(
            "redirect_url", oauth2.get("redirect_url", "http://localhost:8000")
        ).strip()
        self.scopes = mailbox.get("scopes", oauth2.get("Scopes", []))
        self.password = mailbox.get("password", "").strip()
        self.password_file = Path(
            mailbox.get("password_file", "Results/unlogged_email.txt")
        )
        self.token_cache = Path(
            mailbox.get("token_cache", "Results/recovery_mailbox_token.json")
        )
        self.timeout_seconds = float(mailbox.get("timeout_seconds", 180))
        self.poll_interval_seconds = float(mailbox.get("poll_interval_seconds", 3))
        self.lookback_seconds = float(mailbox.get("message_lookback_seconds", 30))
        self.code_pattern = mailbox.get("code_pattern", DEFAULT_CODE_PATTERN)
        self.proxy = proxy.strip()

    @property
    def proxies(self):
        if not self.proxy:
            return None
        return {"http": self.proxy, "https": self.proxy}

    def _read_password(self):
        env_password = os.environ.get("OUTLOOK_RECOVERY_PASSWORD", "").strip()
        if env_password:
            return env_password
        if self.password:
            return self.password
        if not self.password_file.exists():
            raise RuntimeError(f"找不到备用邮箱密码文件：{self.password_file}")

        for line in self.password_file.read_text(encoding="utf-8").splitlines():
            mailbox, separator, password = line.partition(":")
            if separator and mailbox.strip().lower() == self.email.lower():
                return password.strip()
        raise RuntimeError("备用邮箱密码文件中没有匹配的邮箱记录")

    def _load_token(self):
        if not self.token_cache.exists():
            return {}
        try:
            token = json.loads(self.token_cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if token.get("email", "").lower() != self.email.lower():
            return {}
        return token

    def _save_token(self, token):
        self.token_cache.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "email": self.email,
            "access_token": token.get("access_token", ""),
            "refresh_token": token.get("refresh_token", ""),
            "expires_at": time.time() + float(token.get("expires_in", 0)),
        }
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{self.token_cache.name}.",
            suffix=".tmp",
            dir=self.token_cache.parent,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, self.token_cache)
        finally:
            if os.path.exists(temp_name):
                os.remove(temp_name)
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
            raise RuntimeError(f"OAuth 返回了非 JSON 响应（HTTP {response.status_code}）") from exc
        if not response.ok or "access_token" not in result:
            detail = result.get("error_description") or result.get("error") or response.status_code
            raise RuntimeError(f"备用邮箱 OAuth 失败：{str(detail).splitlines()[0]}")
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

    def _authorize_with_browser(self, browser):
        if not self.email or not self.client_id or not self.scopes:
            raise RuntimeError("备用邮箱 OAuth 配置不完整")

        password = self._read_password()
        verifier = generate_code_verifier()
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_url,
            "scope": " ".join(self.scopes),
            "response_mode": "query",
            "prompt": "select_account",
            "code_challenge": generate_code_challenge(verifier),
            "code_challenge_method": "S256",
        }
        authorize_url = (
            f"{AUTHORIZE_ENDPOINT}?"
            + "&".join(f"{key}={quote(value)}" for key, value in params.items())
        )

        context = browser.new_context()
        page = context.new_page()
        captured_url = None

        def capture_redirect(request):
            nonlocal captured_url
            if self.redirect_url in request.url and "code=" in request.url:
                captured_url = request.url

        page.on("request", capture_redirect)
        try:
            try:
                page.goto(authorize_url, timeout=30000, wait_until="domcontentloaded")
            except Exception:
                pass

            login_input = page.locator('input[name="loginfmt"], input[type="email"]').first
            try:
                login_input.wait_for(state="visible", timeout=15000)
                login_input.fill(self.email)
                page.locator("#idSIButton9, button[type='submit'], input[type='submit']").first.click()
            except Exception:
                account = page.get_by_text(self.email, exact=False).first
                if account.count() > 0:
                    account.click()

            password_input = page.locator('input[name="passwd"], input[type="password"]').first
            password_input.wait_for(state="visible", timeout=15000)
            password_input.fill(password)
            page.locator("#idSIButton9, button[type='submit'], input[type='submit']").first.click()

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

            deadline = time.time() + 45
            while time.time() < deadline and not captured_url:
                page.wait_for_timeout(200)
        finally:
            page.remove_listener("request", capture_redirect)
            context.close()

        if not captured_url:
            raise RuntimeError("未捕获到备用邮箱 OAuth 回调")
        query = parse_qs(captured_url.split("?", 1)[1])
        auth_code = query.get("code", [None])[0]
        if not auth_code:
            raise RuntimeError("备用邮箱 OAuth 回调中没有授权码")

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

    def _get_access_token(self, browser):
        token = self._load_token()
        if token.get("access_token") and float(token.get("expires_at", 0)) > time.time() + 60:
            return token["access_token"]
        if token.get("refresh_token"):
            token = self._refresh_token(token["refresh_token"])
            return token["access_token"]
        token = self._authorize_with_browser(browser)
        return token["access_token"]

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
            raise RuntimeError(f"Graph 返回了非 JSON 响应（HTTP {response.status_code}）") from exc
        if not response.ok:
            detail = (result.get("error") or {}).get("message", response.status_code)
            raise RuntimeError(f"读取备用邮箱失败：{detail}")
        return result.get("value", [])

    def wait_for_code(self, browser, requested_at, target_email=""):
        access_token = self._get_access_token(browser)
        deadline = time.time() + self.timeout_seconds
        refreshed_after_401 = False

        while time.time() < deadline:
            messages = self._list_messages(access_token)
            if messages is None:
                if refreshed_after_401:
                    raise RuntimeError("备用邮箱访问令牌已失效")
                token = self._load_token()
                if not token.get("refresh_token"):
                    raise RuntimeError("备用邮箱访问令牌已失效且没有 refresh_token")
                access_token = self._refresh_token(token["refresh_token"])["access_token"]
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

        raise TimeoutError(f"{int(self.timeout_seconds)} 秒内没有收到备用邮箱验证码")
