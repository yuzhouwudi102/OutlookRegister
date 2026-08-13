import json
import io
import os
import re
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, mock_open, patch
from types import SimpleNamespace

from authorize_recovery_mailbox import get_authorization_status
from controllers.base_controller import BaseBrowserController
from recovery_mailbox import (
    RecoveryMailboxClient,
    RecoveryMailboxAccount,
    LOOP_CREATION_ERROR,
    build_loop_token_payload,
    clear_and_write_loop_backup,
    extract_security_code,
    find_code_in_messages,
    get_loop_token_file,
    list_authorized_emails,
    load_backup_accounts,
    token_file_for_email,
    validate_loop_creation,
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

    def test_failed_post_registration_after_captcha_reports_registration_success(self):
        controller = object.__new__(DummyController)
        controller.email_suffix = "@outlook.com"
        controller.thread_local = SimpleNamespace(captcha_completed=True)
        controller.complete_post_registration = Mock(return_value=False)
        controller.save_registered_account = Mock()
        output = io.StringIO()

        with redirect_stdout(output):
            result = controller.finalize_registered_account(
                Mock(),
                "failed-after-captcha",
                "password",
            )

        self.assertFalse(result)
        self.assertIn("但注册已成功，可尝试登录", output.getvalue())
        controller.save_registered_account.assert_not_called()

    def test_recovery_email_waits_two_seconds_after_fill(self):
        source = Path(
            "controllers/base_controller.py"
        ).read_text(encoding="utf-8")
        fill_index = source.index("recovery_input.fill(account.email)")
        wait_index = source.index("page.wait_for_timeout(2000)", fill_index)
        requested_index = source.index(
            "requested_at = datetime.now(timezone.utc)",
            fill_index,
        )

        self.assertLess(fill_index, wait_index)
        self.assertLess(wait_index, requested_index)

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

    def test_loop_creation_requires_matching_task_count_and_oauth(self):
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
            config["oauth2"]["Loop Creation"] = True
            config["oauth2"]["enable_oauth2"] = False

            with self.assertRaisesRegex(
                ValueError,
                re.escape(LOOP_CREATION_ERROR),
            ):
                validate_loop_creation(config, 2)

            config["oauth2"]["enable_oauth2"] = True
            with self.assertRaisesRegex(
                ValueError,
                re.escape(LOOP_CREATION_ERROR),
            ):
                validate_loop_creation(config, 1)

            enabled, accounts = validate_loop_creation(config, 2)
            self.assertTrue(enabled)
            self.assertEqual(
                [account.email for account in accounts],
                ["one@example.com", "two@example.com"],
            )

    def test_loop_creation_rotates_backup_and_token_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            config["oauth2"]["Loop Creation"] = True
            config["oauth2"]["enable_oauth2"] = True
            config["oauth2"]["loop_token_file"] = str(
                Path(directory) / "loop-token.json"
            )
            accounts_file = Path(
                config["recovery_mailbox"]["accounts_file"]
            )
            accounts_file.write_text(
                "old@example.com: old-password\n",
                encoding="utf-8",
            )
            payload = build_loop_token_payload(
                "new@example.com",
                "refresh",
                "access",
                1234.5,
            )

            token_path = clear_and_write_loop_backup(
                config,
                "new@example.com",
                "new-password",
                payload,
            )

            self.assertEqual(
                accounts_file.read_text(encoding="utf-8"),
                "new@example.com: new-password\n",
            )
            self.assertEqual(token_path, get_loop_token_file(config))
            self.assertEqual(
                json.loads(token_path.read_text(encoding="utf-8")),
                payload,
            )

    def test_loop_creation_uses_each_assigned_account_once(self):
        import main

        controller = Mock()
        assigned = []

        def record_attempt(_controller, loop_account=None):
            assigned.append(loop_account.email)
            return True

        with patch.object(
            main,
            "process_single_flow",
            side_effect=record_attempt,
        ):
            main.run_concurrent_flows(
                controller,
                concurrent_flows=2,
                max_tasks=2,
                loop_accounts=[
                    RecoveryMailboxAccount(
                        "one@example.com",
                        "pass-one",
                    ),
                    RecoveryMailboxAccount(
                        "two@example.com",
                        "pass-two",
                    ),
                ],
            )

        self.assertEqual(
            sorted(assigned),
            ["one@example.com", "two@example.com"],
        )

    def test_loop_creation_process_persists_token_and_rotates_backup(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            original_cwd = os.getcwd()
            os.chdir(directory)
            try:
                Path("Results").mkdir()
                accounts_file = Path("Results/backup_email.txt")
                accounts_file.write_text(
                    "old@example.com: old-password\n",
                    encoding="utf-8",
                )
                config = {
                    "oauth2": {
                        "Loop Creation": True,
                        "enable_oauth2": True,
                        "loop_token_file": (
                            "Results/"
                            "tarmaobrvkuzbt_outlook.com_c8ffee6885.json"
                        ),
                    },
                    "recovery_mailbox": {
                        "accounts_file": str(accounts_file),
                    },
                }
                controller = Mock()
                controller.email_suffix = "@outlook.com"
                controller.enable_oauth2 = True
                controller.loop_creation_enabled = True
                controller.loop_creation_lock = threading.Lock()
                controller.config = config
                controller.get_thread_page.return_value = Mock()
                controller.outlook_register.return_value = True
                controller.clean_up = Mock()

                with patch.object(
                    main,
                    "random_email",
                    return_value="created",
                ), patch.object(
                    main,
                    "generate_strong_password",
                    return_value="CreatedPassword!",
                ), patch.object(
                    main,
                    "get_access_token",
                    return_value=(
                        "refresh-token",
                        "access-token",
                        1234.5,
                    ),
                ), patch(
                    "builtins.open",
                    mock_open(),
                ):
                    result = main.process_single_flow(
                        controller,
                        RecoveryMailboxAccount(
                            "old@example.com",
                            "old-password",
                        ),
                    )

                self.assertTrue(result)
                self.assertEqual(
                    accounts_file.read_text(encoding="utf-8"),
                    "created@outlook.com: CreatedPassword!\n",
                )
                loop_token = json.loads(
                    Path(
                        "Results/"
                        "tarmaobrvkuzbt_outlook.com_c8ffee6885.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    loop_token,
                    {
                        "email": "created@outlook.com",
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                        "expires_at": 1234.5,
                    },
                )
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
