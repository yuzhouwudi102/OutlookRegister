import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from recovery_mailbox import (
    RecoveryMailboxClient,
    extract_security_code,
    find_code_in_messages,
)


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
            find_code_in_messages(messages, now, "target@example.com", lookback_seconds=5),
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
        self.assertIsNone(find_code_in_messages(messages, now, lookback_seconds=30))

    def test_reads_matching_password_record(self):
        with tempfile.TemporaryDirectory() as directory:
            password_file = Path(directory) / "accounts.txt"
            password_file.write_text(
                "other@example.com: other-pass\nbackup@example.com: wanted-pass\n",
                encoding="utf-8",
            )
            client = RecoveryMailboxClient(
                {
                    "recovery_email": "backup@example.com",
                    "oauth2": {"client_id": "client", "Scopes": ["Mail.Read"]},
                    "recovery_mailbox": {"password_file": str(password_file)},
                }
            )
            self.assertEqual(client._read_password(), "wanted-pass")


if __name__ == "__main__":
    unittest.main()
