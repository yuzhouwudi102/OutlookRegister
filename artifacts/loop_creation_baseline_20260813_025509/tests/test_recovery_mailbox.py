import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from authorize_recovery_mailbox import get_authorization_status
from controllers.base_controller import BaseBrowserController
from recovery_mailbox import (
    RecoveryMailboxClient,
    extract_security_code,
    find_code_in_messages,
    list_authorized_emails,
    load_backup_accounts,
    token_file_for_email,
)


class DummyController(BaseBrowserController):
    def launch_browser(self):
        return None, None

    def handle_captcha(self, page):
        return False

    def clean_up(self, page=None, type="all_browser"):
        return None

    def get_thread_page(self):
        return None


class FakeInboxLocator:
    def __init__(self):
        self.timeout = None

    def wait_for(self, timeout):
        self.timeout = timeout


class FakeInboxPage:
    def __init__(self):
        self.inbox = FakeInboxLocator()

    def locator(self, selector):
        return self.inbox


def build_config(directory):
    directory = Path(directory)
    return {
        "oauth2": {
            "client_id": "client",
            "redirect_url": "http://localhost:8000",
            "Scopes": ["offline_access", "Mail.Read"],
        },
        "recovery_mailbox": {
            "accounts_file": str(directory / "backup_email.txt"),
            "token_dir": str(directory / "recovery_mailbox_token"),
            "legacy_token_cache": str(directory / "legacy-token.json"),
        },
    }


class RecoveryMailboxTests(unittest.TestCase):
    def test_extracts_keyword_code(self):
        self.assertEqual(
            extract_security_code("Your Microsoft security code is 7654321."),
            "7654321",
        )
        self.assertEqual(extract_security_code("你的安全代码是 123456。"), "123456")

    def test_prefers_message_matching_target_account(self):
        now = datetime.now(timezone.utc)
        messages = [
            {
                "receivedDateTime": now.isoformat(),
                "subject": "Security code 111111",
                "bodyPreview": "for somebody@example.com",
                "body": {"content": ""},
            },
            {
                "receivedDateTime": (now - timedelta(seconds=1)).isoformat(),
                "subject": "Security code 222222",
                "bodyPreview": "for target@example.com",
                "body": {"content": ""},
            },
        ]
        self.assertEqual(
            find_code_in_messages(
                messages,
                now,
                "target@example.com",
                lookback_seconds=5,
            ),
            "222222",
        )

    def test_ignores_old_message(self):
        now = datetime.now(timezone.utc)
        messages = [
            {
                "receivedDateTime": (now - timedelta(minutes=5)).isoformat(),
                "subject": "Security code 333333",
                "bodyPreview": "",
                "body": {"content": ""},
            }
        ]
        self.assertIsNone(
            find_code_in_messages(messages, now, lookback_seconds=30)
        )

    def test_loads_multiple_backup_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            accounts_file = Path(
                config["recovery_mailbox"]["accounts_file"]
            )
            accounts_file.write_text(
                "# backup mailboxes\n"
                "one@example.com: pass-one\n"
                "two@example.com: pass-two\n"
                "one@example.com: ignored-duplicate\n",
                encoding="utf-8",
            )

            accounts = load_backup_accounts(accounts_file)

            self.assertEqual(
                [account.email for account in accounts],
                ["one@example.com", "two@example.com"],
            )
            self.assertEqual(accounts[1].password, "pass-two")

    def test_uses_separate_token_file_for_each_email(self):
        with tempfile.TemporaryDirectory() as directory:
            first = token_file_for_email(directory, "one@example.com")
            second = token_file_for_email(directory, "two@example.com")

            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(directory))
            self.assertEqual(second.parent, Path(directory))

    def test_detects_authorized_and_pending_accounts(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            accounts_file = Path(
                config["recovery_mailbox"]["accounts_file"]
            )
            accounts_file.write_text(
                "one@example.com: pass-one\n"
                "two@example.com: pass-two\n",
                encoding="utf-8",
            )
            accounts = load_backup_accounts(accounts_file)
            first_client = RecoveryMailboxClient(
                config,
                account=accounts[0],
            )
            first_client._save_token(
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                }
            )

            all_accounts, authorized, pending = get_authorization_status(config)

            self.assertEqual(len(all_accounts), 2)
            self.assertEqual(authorized, {"one@example.com"})
            self.assertEqual(
                [account.email for account in pending],
                ["two@example.com"],
            )

    def test_registration_randomly_selects_an_authorized_account(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            accounts_file = Path(
                config["recovery_mailbox"]["accounts_file"]
            )
            accounts_file.write_text(
                "one@example.com: pass-one\n"
                "two@example.com: pass-two\n",
                encoding="utf-8",
            )
            accounts = load_backup_accounts(accounts_file)
            for account in accounts:
                RecoveryMailboxClient(
                    config,
                    account=account,
                )._save_token(
                    {
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "expires_in": 3600,
                    }
                )

            controller = object.__new__(DummyController)
            controller.recovery_accounts_file = accounts_file
            controller.recovery_mailbox_enabled = True
            controller.config = config
            controller.proxy = ""

            with patch(
                "controllers.base_controller.random.choice",
                return_value=accounts[1],
            ) as mocked_choice:
                selected, client = controller.choose_recovery_mailbox()

            mocked_choice.assert_called_once()
            self.assertEqual(selected.email, "two@example.com")
            self.assertEqual(client.email, "two@example.com")

    def test_migrates_legacy_single_token(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            legacy_path = Path(
                config["recovery_mailbox"]["legacy_token_cache"]
            )
            legacy_path.write_text(
                json.dumps(
                    {
                        "email": "legacy@example.com",
                        "access_token": "access",
                        "refresh_token": "refresh",
                        "expires_at": 0,
                    }
                ),
                encoding="utf-8",
            )

            authorized = list_authorized_emails(config)

            self.assertEqual(authorized, {"legacy@example.com"})
            migrated = token_file_for_email(
                config["recovery_mailbox"]["token_dir"],
                "legacy@example.com",
            )
            self.assertTrue(migrated.exists())

    def test_oauth_disabled_account_is_saved_to_unlogged_file(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = object.__new__(DummyController)
            controller.results_dir = directory
            controller.results_lock = threading.Lock()
            controller.enable_oauth2 = False
            controller.email_suffix = "@outlook.com"

            first_path = controller.save_registered_account(
                "new-account",
                "password",
            )
            second_path = controller.save_registered_account(
                "new-account",
                "password",
            )

            self.assertEqual(first_path, second_path)
            self.assertTrue(first_path.endswith("unlogged_email.txt"))
            records = Path(first_path).read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertEqual(
                records,
                ["new-account@outlook.com: password"],
            )

    def test_oauth_disabled_still_runs_recovery_email_flow(self):
        controller = object.__new__(DummyController)
        controller.enable_oauth2 = False
        controller.recovery_mailbox_enabled = True
        controller.handle_recovery_email_prompt = Mock(return_value=True)
        page = FakeInboxPage()

        result = controller.complete_post_registration(
            page,
            "new-account@outlook.com",
        )

        self.assertTrue(result)
        controller.handle_recovery_email_prompt.assert_called_once_with(
            page,
            "new-account@outlook.com",
        )
        self.assertEqual(page.inbox.timeout, 60000)

    def test_failed_post_registration_is_not_saved(self):
        controller = object.__new__(DummyController)
        controller.email_suffix = "@outlook.com"
        controller.complete_post_registration = Mock(
            return_value=False
        )
        controller.save_registered_account = Mock()

        result = controller.finalize_registered_account(
            Mock(),
            "failed-account",
            "password",
        )

        self.assertFalse(result)
        controller.save_registered_account.assert_not_called()

    def test_successful_post_registration_is_saved(self):
        controller = object.__new__(DummyController)
        controller.email_suffix = "@outlook.com"
        controller.complete_post_registration = Mock(
            return_value=True
        )
        controller.save_registered_account = Mock()

        result = controller.finalize_registered_account(
            Mock(),
            "successful-account",
            "password",
        )

        self.assertTrue(result)
        controller.save_registered_account.assert_called_once_with(
            "successful-account",
            "password",
        )


if __name__ == "__main__":
    unittest.main()
