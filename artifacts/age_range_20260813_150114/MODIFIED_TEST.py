import unittest
from pathlib import Path

from controllers.base_controller import signup_option_labels


class SignupFlowTests(unittest.TestCase):
    def test_english_month_name_is_included_for_month_eleven(self):
        labels = signup_option_labels("11", "month")

        self.assertEqual(labels[0], "11")
        self.assertIn("November", labels)
        self.assertIn("Nov", labels)
        self.assertIn("11月", labels)

    def test_day_eleven_stays_numeric_and_keeps_chinese_fallback(self):
        labels = signup_option_labels("11", "day")

        self.assertIn("11", labels)
        self.assertIn("11日", labels)
        self.assertNotIn("November", labels)

    def test_single_digit_values_include_zero_padded_fallback(self):
        self.assertIn("07", signup_option_labels("7", "month"))
        self.assertIn("07", signup_option_labels("7", "day"))

    def test_patchright_captcha_keeps_result_updata1_flow_with_english_labels(self):
        source = Path(
            "controllers/patchright_controller.py"
        ).read_text(encoding="utf-8")

        self.assertIn('iframe[title="Verification challenge"]', source)
        self.assertIn('[aria-label="Accessibility Challenge"]', source)
        self.assertIn('[aria-label="Press again"]', source)
        self.assertIn("Accessible challenge", source)
        self.assertNotIn("Press and hold", source)
        self.assertNotIn("page.mouse.down()", source)
        self.assertNotIn("page.mouse.up()", source)
        self.assertIn("iframe_timeout_ms = 32000", source)
        self.assertIn("press_again_timeout_ms = 20000", source)
        self.assertIn("loading_timeout_ms = 5000", source)
        self.assertIn("settle_min_ms = 7500", source)
        self.assertIn("settle_max_ms = 8500", source)
        self.assertIn("Skip for now", source)

    def test_birth_year_and_day_ranges_are_updated(self):
        source = Path("controllers/base_controller.py").read_text(encoding="utf-8")

        self.assertIn("year = str(random.randint(1990, 2006))", source)
        self.assertIn("day = str(random.randint(0, 27))", source)
        self.assertNotIn("year = str(random.randint(1960, 2005))", source)
        self.assertNotIn("day = str(random.randint(1, 28))", source)

    def test_post_registration_keeps_result_updata1_flow_with_english_labels(self):
        source = Path(
            "controllers/base_controller.py"
        ).read_text(encoding="utf-8")

        self.assertIn('button:has-text("Next")', source)
        self.assertIn("Skip for now", source)
        self.assertIn('[aria-label="新邮件"]', source)
        self.assertIn('[aria-label="New mail"]', source)


if __name__ == "__main__":
    unittest.main()
