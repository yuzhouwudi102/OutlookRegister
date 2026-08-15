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
    build_outlook_token_record,
    build_loop_token_payload,
    clear_and_write_loop_backup,
    extract_security_code,
    find_code_in_messages,
    get_loop_token_file,
    get_outlook_token_file,
    list_authorized_emails,
    load_backup_accounts,
    token_file_for_email,
    save_outlook_token_record,
    validate_loop_creation,
    replace_loop_backup_account,
    write_loop_backup_accounts,
    write_recovery_mailbox_token,
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
    def test_writes_per_email_recovery_token_json(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            payload = build_loop_token_payload(
                "New@Example.com",
                "refresh",
                "access",
                1234.5,
            )

            token_path = write_recovery_mailbox_token(config, payload)

            self.assertEqual(
                token_path,
                token_file_for_email(
                    config["recovery_mailbox"]["token_dir"],
                    "new@example.com",
                ),
            )
            self.assertEqual(
                json.loads(token_path.read_text(encoding="utf-8")),
                payload,
            )

    def test_recovery_email_retries_next_before_mailbox_polling(self):
        controller = object.__new__(DummyController)
        controller.smooth_click = Mock()
        page = Mock()
        recovery_input = Mock()
        recovery_input.is_visible.return_value = True
        next_button = Mock()
        code_input = Mock()
        code_input.wait_for.side_effect = [RuntimeError('not ready'), None]
        page.locator.return_value.first = code_input

        result = controller.wait_for_recovery_code_step(
            page,
            recovery_input,
            next_button,
        )

        self.assertIs(result, code_input)
        controller.smooth_click.assert_called_once_with(page, next_button)
        next_button.click.assert_called_once_with(timeout=5000)
        self.assertEqual(
            code_input.wait_for.call_args_list,
            [
                unittest.mock.call(state='visible', timeout=15000),
                unittest.mock.call(state='visible', timeout=20000),
            ],
        )

    def test_recovery_email_confirms_code_page_before_graph_polling(self):
        source = Path('controllers/base_controller.py').read_text(
            encoding='utf-8'
        )
        handler = source[source.index('    def handle_recovery_email_prompt'):]

        self.assertLess(
            handler.index('self.wait_for_recovery_code_step('),
            handler.index('mailbox_client.wait_for_code('),
        )

    def test_builds_outlook_token_five_field_record(self):
        record = build_outlook_token_record(
            "ONE@EXAMPLE.COM",
            "secret",
            "refresh",
            "access",
            1234.5,
        )

        self.assertEqual(
            record,
            "one@example.com---secret---refresh---access---1234.5",
        )

    def test_saves_and_replaces_outlook_token_record(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            config["oauth2"]["token_file"] = str(
                Path(directory) / "outlook_token.txt"
            )
            account = RecoveryMailboxAccount(
                "one@example.com",
                "password",
            )

            first_path = save_outlook_token_record(
                config,
                account,
                {
                    "refresh_token": "refresh-one",
                    "access_token": "access-one",
                    "expires_at": 100.0,
                },
            )
            second_path = save_outlook_token_record(
                config,
                account,
                {
                    "refresh_token": "refresh-two",
                    "access_token": "access-two",
                    "expires_at": 200.0,
                },
            )

            self.assertEqual(first_path, get_outlook_token_file(config))
            self.assertEqual(second_path, first_path)
            self.assertEqual(
                first_path.read_text(encoding="utf-8").splitlines(),
                [
                    "one@example.com---password---refresh-two---"
                    "access-two---200.0"
                ],
            )

    def test_authorize_script_uses_automated_flow_and_txt_export(self):
        source = Path("authorize_recovery_mailbox.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("interactive=False", source)
        self.assertIn("save_outlook_token_record", source)
        self.assertNotIn("interactive=True", source)

    def test_authorization_handles_account_picker_and_password_method(self):
        source = Path("recovery_mailbox.py").read_text(encoding="utf-8")

        picker_index = source.index('"Pick an account"')
        account_index = source.index(
            "page.get_by_text(self.email, exact=True)",
            picker_index,
        )
        password_method_index = source.index('"Use your password"')
        generic_email_index = source.index(
            "'input[name=\"loginfmt\"], input[type=\"email\"]'",
            password_method_index,
        )

        self.assertLess(picker_index, account_index)
        self.assertLess(account_index, password_method_index)
        self.assertLess(password_method_index, generic_email_index)
        self.assertIn("account_picker_visible", source)

    def test_authorization_waits_one_second_after_navigation_actions(self):
        source = Path("recovery_mailbox.py").read_text(encoding="utf-8")
        flow = source[source.index("def authorize_with_browser("):]

        self.assertEqual(flow.count("page.wait_for_timeout(1000)"), 4)
        self.assertNotIn("page.wait_for_timeout(600)", flow)
        self.assertIn("page.wait_for_timeout(250)", flow)

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

    def test_registration_authorizes_when_no_authorized_account_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            accounts_file = Path(config["recovery_mailbox"]["accounts_file"])
            accounts_file.write_text(
                "one@example.com: pass-one\n",
                encoding="utf-8",
            )
            account = load_backup_accounts(accounts_file)[0]
            controller = object.__new__(DummyController)
            controller.recovery_accounts_file = accounts_file
            controller.recovery_mailbox_enabled = True
            controller.config = config
            controller.proxy = ""
            controller.fingerprint_enabled = False
            controller.thread_local = SimpleNamespace()
            browser = Mock()
            controller.get_thread_browser = Mock(return_value=browser)
            token_payload = {
                "refresh_token": "refresh",
                "access_token": "access",
                "expires_at": 1234.5,
            }

            with patch(
                "controllers.base_controller.random.choice",
                return_value=account,
            ), patch.object(
                RecoveryMailboxClient,
                "authorize_with_browser",
                return_value=token_payload,
            ) as mocked_authorize, patch(
                "controllers.base_controller.save_outlook_token_record",
                return_value=Path(directory) / "outlook_token.txt",
            ) as mocked_save:
                selected, client = controller.choose_recovery_mailbox()

            self.assertEqual(selected.email, account.email)
            self.assertEqual(client.email, account.email)
            mocked_authorize.assert_called_once_with(
                browser,
                interactive=False,
                timeout_seconds=300,
                context_options={},
                init_script=None,
                runtime_profile=None,
            )
            mocked_save.assert_called_once_with(
                config,
                account,
                token_payload,
            )

    def test_loop_assigned_account_is_authorized_when_needed(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            account = RecoveryMailboxAccount(
                "loop@example.com",
                "loop-password",
            )
            controller = object.__new__(DummyController)
            controller.recovery_mailbox_enabled = True
            controller.config = config
            controller.proxy = ""
            controller.fingerprint_enabled = False
            controller.thread_local = SimpleNamespace(
                loop_recovery_account=account,
            )
            browser = Mock()
            controller.get_thread_browser = Mock(return_value=browser)
            token_payload = {
                "refresh_token": "refresh",
                "access_token": "access",
                "expires_at": 1234.5,
            }

            with patch.object(
                RecoveryMailboxClient,
                "authorize_with_browser",
                return_value=token_payload,
            ) as mocked_authorize, patch(
                "controllers.base_controller.save_outlook_token_record",
                return_value=Path(directory) / "outlook_token.txt",
            ) as mocked_save:
                selected, client = controller.choose_recovery_mailbox()

            self.assertEqual(selected.email, account.email)
            self.assertEqual(client.email, account.email)
            mocked_authorize.assert_called_once_with(
                browser,
                interactive=False,
                timeout_seconds=300,
                context_options={},
                init_script=None,
                runtime_profile=None,
            )
            mocked_save.assert_called_once_with(
                config,
                account,
                token_payload,
            )

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

    def test_loop_creation_writes_all_accounts_created_in_current_run(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
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
            created_accounts = {
                "first@example.com": "first-password",
                "second@example.com": "second-password",
            }
            payload = build_loop_token_payload(
                "second@example.com",
                "refresh",
                "access",
                1234.5,
            )

            write_loop_backup_accounts(
                config,
                created_accounts,
                payload,
            )

            self.assertEqual(
                accounts_file.read_text(encoding="utf-8"),
                "first@example.com: first-password\n"
                "second@example.com: second-password\n",
            )

    def test_loop_creation_replaces_only_the_successful_mailbox(self):
        with tempfile.TemporaryDirectory() as directory:
            config = build_config(directory)
            accounts_file = Path(config["recovery_mailbox"]["accounts_file"])
            accounts = {
                "used@example.com": "used-password",
                "failed@example.com": "failed-password",
            }
            token_payload = build_loop_token_payload(
                "created@example.com",
                "refresh",
                "access",
                1234.5,
            )

            replace_loop_backup_account(
                config,
                accounts,
                RecoveryMailboxAccount("used@example.com", "used-password"),
                "created@example.com",
                "created-password",
                token_payload,
            )

            self.assertEqual(
                accounts_file.read_text(encoding="utf-8"),
                "created@example.com: created-password\n"
                "failed@example.com: failed-password\n",
            )
            self.assertEqual(
                accounts,
                {
                    "created@example.com": "created-password",
                    "failed@example.com": "failed-password",
                },
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
                per_email_token = json.loads(
                    token_file_for_email(
                        "Results/recovery_mailbox_token",
                        "created@outlook.com",
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(per_email_token, loop_token)
            finally:
                os.chdir(original_cwd)

    def test_two_loop_creation_tasks_keep_both_new_accounts(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            original_cwd = os.getcwd()
            os.chdir(directory)
            try:
                Path("Results").mkdir()
                config = build_config(directory)
                accounts_file = Path(
                    config["recovery_mailbox"]["accounts_file"]
                )
                accounts_file.write_text(
                    "old-one@example.com: old-one-password\n"
                    "old-two@example.com: old-two-password\n",
                    encoding="utf-8",
                )
                config["oauth2"]["Loop Creation"] = True
                config["oauth2"]["enable_oauth2"] = True
                config["oauth2"]["loop_token_file"] = str(
                    Path(directory) / "loop-token.json"
                )
                controller = Mock()
                controller.email_suffix = "@outlook.com"
                controller.enable_oauth2 = True
                controller.loop_creation_enabled = True
                controller.loop_creation_lock = threading.Lock()
                controller.loop_created_accounts = {}
                controller.config = config
                controller.get_thread_page.return_value = Mock()
                controller.outlook_register.return_value = True
                controller.clean_up = Mock()

                with patch.object(
                    main,
                    "random_email",
                    side_effect=["first", "second"],
                ), patch.object(
                    main,
                    "generate_strong_password",
                    side_effect=["FirstPassword!", "SecondPassword!"],
                ), patch.object(
                    main,
                    "get_access_token",
                    side_effect=[
                        ("refresh-1", "access-1", 1234.5),
                        ("refresh-2", "access-2", 2345.6),
                    ],
                ):
                    main.run_concurrent_flows(
                        controller,
                        concurrent_flows=2,
                        max_tasks=2,
                        loop_accounts=[
                            RecoveryMailboxAccount(
                                "old-one@example.com",
                                "old-one-password",
                            ),
                            RecoveryMailboxAccount(
                                "old-two@example.com",
                                "old-two-password",
                            ),
                        ],
                    )

                self.assertEqual(
                    accounts_file.read_text(encoding="utf-8"),
                    "first@outlook.com: FirstPassword!\n"
                    "second@outlook.com: SecondPassword!\n",
                )
            finally:
                os.chdir(original_cwd)

    def test_loop_creation_keeps_the_mailbox_for_a_failed_task(self):
        import main

        with tempfile.TemporaryDirectory() as directory:
            original_cwd = os.getcwd()
            os.chdir(directory)
            try:
                Path("Results").mkdir()
                config = build_config(directory)
                accounts_file = Path(
                    config["recovery_mailbox"]["accounts_file"]
                )
                accounts_file.write_text(
                    "used@example.com: used-password\n"
                    "failed@example.com: failed-password\n",
                    encoding="utf-8",
                )
                config["oauth2"]["Loop Creation"] = True
                config["oauth2"]["enable_oauth2"] = True
                controller = Mock()
                controller.email_suffix = "@outlook.com"
                controller.enable_oauth2 = True
                controller.loop_creation_enabled = True
                controller.loop_creation_lock = threading.Lock()
                controller.config = config
                controller.get_thread_page.return_value = Mock()
                controller.outlook_register.side_effect = (
                    lambda _page, address, _password: address == "created"
                )
                controller.clean_up = Mock()

                with patch.object(
                    main,
                    "random_email",
                    side_effect=["created", "failed"],
                ), patch.object(
                    main,
                    "generate_strong_password",
                    return_value="NewPassword!",
                ), patch.object(
                    main,
                    "get_access_token",
                    return_value=("refresh", "access", 1234.5),
                ), patch("builtins.open", mock_open()):
                    main.run_concurrent_flows(
                        controller,
                        concurrent_flows=2,
                        max_tasks=2,
                        loop_accounts=[
                            RecoveryMailboxAccount(
                                "used@example.com", "used-password"
                            ),
                            RecoveryMailboxAccount(
                                "failed@example.com", "failed-password"
                            ),
                        ],
                    )

                self.assertEqual(
                    accounts_file.read_text(encoding="utf-8"),
                    "created@outlook.com: NewPassword!\n"
                    "failed@example.com: failed-password\n",
                )
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
