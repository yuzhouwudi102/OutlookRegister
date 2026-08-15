import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from refresh_recovery_tokens import (
    read_outlook_records,
    refresh_token_file,
    token_needs_refresh,
)


class RefreshRecoveryTokensTests(unittest.TestCase):
    def test_token_needs_refresh_uses_sixty_second_skew(self):
        self.assertFalse(
            token_needs_refresh({"expires_at": 1061}, now=1000)
        )
        self.assertTrue(
            token_needs_refresh({"expires_at": 1060}, now=1000)
        )
        self.assertTrue(token_needs_refresh({}, now=1000))

    def test_reads_passwords_from_outlook_token_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outlook_token.txt"
            path.write_text(
                "one@example.com---secret---refresh---access---123\n",
                encoding="utf-8",
            )

            self.assertEqual(
                read_outlook_records(path),
                {"one@example.com": "secret"},
            )

    def test_refresh_updates_json_and_matching_outlook_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token_path = root / "token.json"
            outlook_path = root / "outlook_token.txt"
            token_path.write_text(
                json.dumps(
                    {
                        "email": "one@example.com",
                        "access_token": "old-access",
                        "refresh_token": "old-refresh",
                        "expires_at": 1,
                    }
                ),
                encoding="utf-8",
            )
            outlook_path.write_text(
                "one@example.com---secret---old-refresh---old-access---1\n",
                encoding="utf-8",
            )
            config = {
                "oauth2": {
                    "client_id": "client",
                    "Scopes": ["scope"],
                    "token_file": str(outlook_path),
                },
                "recovery_mailbox": {
                    "token_dir": str(root),
                },
            }
            refreshed = {
                "email": "one@example.com",
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_at": 9999,
            }
            with patch(
                "refresh_recovery_tokens.RecoveryMailboxClient._refresh_token",
                return_value=refreshed,
            ):
                status, detail = refresh_token_file(
                    config,
                    token_path,
                    {"one@example.com": "secret"},
                    skew_seconds=60,
                )

            self.assertEqual(status, "updated")
            self.assertIn("均已更新", detail)
            self.assertEqual(
                json.loads(token_path.read_text(encoding="utf-8")),
                refreshed,
            )
            self.assertIn(
                "one@example.com---secret---new-refresh---new-access---9999.0",
                outlook_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
