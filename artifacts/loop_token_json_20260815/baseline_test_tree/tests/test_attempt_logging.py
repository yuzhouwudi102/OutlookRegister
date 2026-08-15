import contextlib
import io
import unittest
from unittest.mock import Mock, patch

import main


class AttemptLoggingTests(unittest.TestCase):
    def test_each_attempt_prints_email_and_password_once(self):
        controller = Mock()
        controller.email_suffix = "@outlook.com"
        controller.enable_oauth2 = False
        controller.get_thread_page.return_value = Mock()
        controller.outlook_register.return_value = False

        output = io.StringIO()
        with patch.object(
            main,
            "random_email",
            return_value="sample",
        ), patch.object(
            main,
            "generate_strong_password",
            return_value="Password123!",
        ), contextlib.redirect_stdout(output):
            result = main.process_single_flow(controller)

        self.assertFalse(result)
        self.assertEqual(
            output.getvalue().count(
                "[Attempt: Email Registration] - "
                "sample@outlook.com: Password123!"
            ),
            1,
        )
        controller.clean_up.assert_called_once()

    def test_success_log_does_not_repeat_the_password(self):
        source = (
            __import__("pathlib")
            .Path("controllers/base_controller.py")
            .read_text(encoding="utf-8")
        )

        self.assertIn("[Success: Email Registration]", source)
        self.assertNotIn(
            "[Success: Email Registration] - "
            "{email}{self.email_suffix}: {password}",
            source,
        )

    def test_attempt_is_printed_even_when_page_creation_fails(self):
        controller = Mock()
        controller.email_suffix = "@outlook.com"
        controller.get_thread_page.side_effect = RuntimeError(
            "browser failed"
        )

        output = io.StringIO()
        with patch.object(
            main,
            "random_email",
            return_value="before-browser",
        ), patch.object(
            main,
            "generate_strong_password",
            return_value="Password456!",
        ), contextlib.redirect_stdout(output):
            result = main.process_single_flow(controller)

        self.assertFalse(result)
        self.assertEqual(
            output.getvalue().count(
                "[Attempt: Email Registration] - "
                "before-browser@outlook.com: Password456!"
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
