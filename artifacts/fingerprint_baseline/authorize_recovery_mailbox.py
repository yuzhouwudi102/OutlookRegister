import json

from patchright.sync_api import sync_playwright

from recovery_mailbox import (
    RecoveryMailboxClient,
    get_accounts_file,
    list_authorized_emails,
    load_backup_accounts,
)


def load_config():
    with open("config.json", "r", encoding="utf-8") as file:
        return json.load(file)


def get_authorization_status(config):
    accounts = load_backup_accounts(get_accounts_file(config))
    authorized_emails = list_authorized_emails(config)
    pending_accounts = [
        account
        for account in accounts
        if account.email not in authorized_emails
    ]
    return accounts, authorized_emails, pending_accounts


def main():
    config = load_config()
    proxy = (config.get("proxy") or "").strip()
    accounts_file = get_accounts_file(config)
    accounts, authorized_emails, pending_accounts = get_authorization_status(
        config
    )

    if not accounts:
        raise ValueError(
            f"{accounts_file} 中没有备用邮箱，格式应为：邮箱: 密码"
        )

    print(f"备用邮箱总数：{len(accounts)}")
    print(
        "已授权："
        f"{len([a for a in accounts if a.email in authorized_emails])}"
    )
    print(f"待授权：{len(pending_accounts)}")

    if not pending_accounts:
        print("backup_email.txt 中的备用邮箱均已授权。")
        return

    failed_accounts = []
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
        try:
            for index, account in enumerate(pending_accounts, start=1):
                print(
                    f"\n[{index}/{len(pending_accounts)}] "
                    f"开始授权：{account.email}"
                )
                client = RecoveryMailboxClient(
                    config,
                    proxy,
                    account=account,
                )
                try:
                    client.authorize_with_browser(
                        browser,
                        interactive=True,
                        timeout_seconds=300,
                    )
                    print(f"[授权成功] {account.email}")
                    print(f"[令牌文件] {client.token_cache}")
                except Exception as exc:
                    failed_accounts.append(account.email)
                    print(f"[授权失败] {account.email}: {exc}")
        finally:
            browser.close()

    success_count = len(pending_accounts) - len(failed_accounts)
    print(
        f"\n授权流程完成：成功 {success_count}，"
        f"失败 {len(failed_accounts)}。"
    )
    if failed_accounts:
        print("失败邮箱：")
        for email in failed_accounts:
            print(f"- {email}")
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"备用邮箱 OAuth 配置错误：{exc}")
        raise SystemExit(1)
