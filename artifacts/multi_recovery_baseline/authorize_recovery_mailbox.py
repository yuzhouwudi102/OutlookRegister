import json
import time
from urllib.parse import parse_qs, quote

from patchright.sync_api import sync_playwright

from recovery_mailbox import (
    AUTHORIZE_ENDPOINT,
    RecoveryMailboxClient,
    generate_code_challenge,
    generate_code_verifier,
)


def load_config():
    with open("config.json", "r", encoding="utf-8") as file:
        return json.load(file)


def build_authorize_url(config, code_verifier):
    oauth2 = config["oauth2"]
    mailbox = config.get("recovery_mailbox", {})
    client_id = mailbox.get("client_id", oauth2["client_id"])
    redirect_url = mailbox.get(
        "redirect_url",
        oauth2.get("redirect_url", "http://localhost:8000"),
    )
    scopes = mailbox.get("scopes", oauth2["Scopes"])

    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_url,
        "scope": " ".join(scopes),
        "response_mode": "query",
        "prompt": "select_account",
        "code_challenge": generate_code_challenge(code_verifier),
        "code_challenge_method": "S256",
    }
    url = (
        f"{AUTHORIZE_ENDPOINT}?"
        + "&".join(
            f"{key}={quote(str(value), safe='')}"
            for key, value in params.items()
        )
    )
    return url, client_id, redirect_url, scopes


def main():
    config = load_config()
    recovery_email = config.get("recovery_email", "").strip()
    proxy = (config.get("proxy") or "").strip()

    if not recovery_email:
        raise ValueError("config.json 中缺少 recovery_email")

    code_verifier = generate_code_verifier()
    authorize_url, client_id, redirect_url, scopes = build_authorize_url(
        config,
        code_verifier,
    )

    captured_url = None

    with sync_playwright() as playwright:
        proxy_settings = (
            {"server": proxy, "bypass": "localhost"}
            if proxy
            else None
        )
        browser = playwright.chromium.launch(
            headless=False,
            args=["--lang=zh-CN"],
            proxy=proxy_settings,
        )
        context = browser.new_context()
        page = context.new_page()

        def capture_redirect(request):
            nonlocal captured_url
            if redirect_url in request.url and "code=" in request.url:
                captured_url = request.url

        page.on("request", capture_redirect)
        try:
            try:
                page.goto(
                    authorize_url,
                    timeout=30000,
                    wait_until="domcontentloaded",
                )
            except Exception as exc:
                print(f"授权页面导航完成前中断：{exc}")

            print(f"请在浏览器中登录备用邮箱：{recovery_email}")
            print("完成安全验证并点击“接受”后，保持浏览器窗口打开。")

            deadline = time.time() + 300
            while time.time() < deadline and not captured_url:
                page.wait_for_timeout(500)
        finally:
            page.remove_listener("request", capture_redirect)

        if not captured_url:
            context.close()
            browser.close()
            raise TimeoutError("5 分钟内没有捕获到 OAuth 回调")

        query = parse_qs(captured_url.split("?", 1)[1])
        authorization_code = query.get("code", [None])[0]
        oauth_error = query.get("error_description", query.get("error", [None]))[0]
        if not authorization_code:
            context.close()
            browser.close()
            raise RuntimeError(
                f"OAuth 回调中没有 authorization code：{oauth_error or '未知错误'}"
            )

        mailbox_client = RecoveryMailboxClient(config, proxy)
        token = mailbox_client._request_token(
            {
                "client_id": client_id,
                "code": authorization_code,
                "redirect_uri": redirect_url,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
                "scope": " ".join(scopes),
            }
        )
        mailbox_client._save_token(token)

        context.close()
        browser.close()

    print("备用邮箱 OAuth 获取成功。")
    print("令牌已保存到：Results/recovery_mailbox_token.json")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"备用邮箱 OAuth 获取失败：{exc}")
        raise SystemExit(1)
