import json
import random
import unittest
from pathlib import Path

from browser_fingerprint import (
    build_context_options,
    build_init_script,
    build_launch_args,
    create_fingerprint_profile,
)


class BrowserFingerprintTests(unittest.TestCase):
    def test_profile_is_coherent_and_deterministic_for_seed(self):
        config = {
            "locale": "en-US",
            "languages": ["en-US", "en"],
            "timezone_id": "America/Los_Angeles",
            "hardware_concurrency": [8],
            "device_memory": [8],
            "device_scale_factor": [1],
        }
        first = create_fingerprint_profile(
            config,
            browser_version="149.0.0",
            random_source=random.Random(1),
        )
        second = create_fingerprint_profile(
            config,
            browser_version="149.0.0",
            random_source=random.Random(1),
        )

        self.assertEqual(first, second)
        self.assertEqual(first["platform"], "Win32")
        self.assertIn("Chrome/149.0.0.0", first["user_agent"])
        self.assertEqual(first["hardware_concurrency"], 8)
        self.assertEqual(first["device_memory"], 8)

    def test_context_options_and_init_script_contain_profile_values(self):
        profile = create_fingerprint_profile(
            {
                "locale": "en-US",
                "languages": ["en-US", "en"],
                "timezone_id": "America/Los_Angeles",
                "hardware_concurrency": [4],
                "device_memory": [4],
                "device_scale_factor": [1],
            },
            browser_version="149.0.0",
            random_source=random.Random(2),
        )
        options = build_context_options(profile)
        script = build_init_script(profile)

        self.assertEqual(options["locale"], "en-US")
        self.assertEqual(options["timezone_id"], "America/Los_Angeles")
        self.assertEqual(options["viewport"], profile["viewport"])
        self.assertIn("Navigator.prototype", script)
        self.assertIn("webdriver", script)
        self.assertIn(profile["webgl_vendor"], script)
        self.assertIn(profile["profile_id"], script)

    def test_launch_args_and_config_keep_headless_disabled(self):
        config = json.loads(
            Path("config.json").read_text(encoding="utf-8")
        )
        fingerprint = config["fingerprint"]
        args = build_launch_args(fingerprint)

        self.assertTrue(fingerprint["enabled"])
        self.assertFalse(fingerprint["headless"])
        self.assertIn("--disable-blink-features=AutomationControlled", args)
        self.assertTrue(
            all(
                "headless" not in arg.lower()
                for arg in args
            )
        )


if __name__ == "__main__":
    unittest.main()
