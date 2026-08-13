import random
import time
from patchright.sync_api import sync_playwright
from .base_controller import BaseBrowserController


class PatchrightController(BaseBrowserController):

    def launch_browser(self):
        try:
            p = sync_playwright().start() 

            proxy_settings = {
                "server": self.proxy,
                "bypass": "localhost",
            } if self.proxy else None

            b = p.chromium.launch(
                headless=self.browser_headless,
                args=self.get_browser_launch_args(),
                proxy=proxy_settings
            )

            return p, b

        except Exception as e:
            print(f"启动浏览器失败: {e}")
            return False, False
        
    def handle_captcha(self, page):
        """Run one bounded Accessible challenge captcha cycle, with retries."""
        iframe_timeout_ms = 32000
        press_again_timeout_ms = 20000
        loading_timeout_ms = 5000
        settle_min_ms = 7500
        settle_max_ms = 8500

        iframe_selector = (
            'iframe[title="\u9a8c\u8bc1\u8d28\u8be2"], '
            'iframe[title="Verification challenge"]'
        )
        challenge_iframe = page.locator(iframe_selector).first
        frame1 = page.frame_locator(iframe_selector)
        frame2 = frame1.frame_locator('iframe[style*="display: block"]')
        challenge_selector = (
            '[aria-label="\u53ef\u8bbf\u95ee\u6027\u6311\u6218"], '
            '[aria-label="Accessibility Challenge"], '
            '[aria-label="Accessible challenge"], '
            '[aria-label*="accessible challenge" i]'
        )
        press_again_selector = (
            '[aria-label="\u518d\u6b21\u6309\u4e0b"], '
            '[aria-label="Press again"]'
        )
        loading_selector = (
            '[role="status"][aria-label="\u6b63\u5728\u52a0\u8f7d..."] , '
            '[role="status"][aria-label="Loading..."]'
        )

        def first_visible(locator):
            try:
                count = locator.count()
            except Exception:
                return None
            for index in range(min(count, 20)):
                candidate = locator.nth(index)
                try:
                    if candidate.is_visible():
                        return candidate
                except Exception:
                    continue
            return None

        def wait_first_visible(locators, timeout):
            deadline = time.monotonic() + timeout / 1000
            while time.monotonic() < deadline:
                for locator in locators:
                    candidate = first_visible(locator)
                    if candidate is not None:
                        return candidate
                page.wait_for_timeout(200)
            return None

        def has_skip_or_success():
            return (
                page.get_by_text("\u6682\u65f6\u8df3\u8fc7").count() > 0
                or page.get_by_text("Skip for now", exact=False).count() > 0
            )

        def has_rate_limit():
            return (
                page.get_by_text("\u4e00\u4e9b\u5f02\u5e38\u6d3b\u52a8").count() > 0
                or page.get_by_text(
                    "\u6b64\u7ad9\u70b9\u6b63\u5728\u7ef4\u62a4\uff0c\u6682\u65f6\u65e0\u6cd5\u4f7f\u7528\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002"
                ).count() > 0
            )

        def click_accessibility_challenge():
            locators = (
                frame2.locator(challenge_selector),
                frame2.get_by_text("Accessible challenge", exact=True),
                frame2.get_by_text("Accessibility Challenge", exact=True),
                frame1.get_by_text("Accessible challenge", exact=True),
                frame1.get_by_text("Accessibility Challenge", exact=True),
                frame1.get_by_text("\u53ef\u8bbf\u95ee\u6027\u6311\u6218", exact=True),
            )
            candidate = wait_first_visible(locators, timeout=8000)
            if candidate is None:
                return False
            try:
                candidate.scroll_into_view_if_needed()
            except Exception:
                pass
            try:
                candidate.click(timeout=5000)
            except Exception:
                candidate.click(timeout=5000, force=True)
            return True

        for _ in range(self.max_captcha_retries + 1):
            try:
                challenge_iframe.wait_for(state="visible", timeout=iframe_timeout_ms)
            except Exception:
                return False
            if not click_accessibility_challenge():
                return False
            try:
                press_again = wait_first_visible(
                    (
                        frame2.locator(press_again_selector),
                        frame1.locator(press_again_selector),
                        frame2.get_by_text("Press again", exact=True),
                        frame1.get_by_text("Press again", exact=True),
                        frame2.get_by_text("\u518d\u6b21\u6309\u4e0b", exact=True),
                        frame1.get_by_text("\u518d\u6b21\u6309\u4e0b", exact=True),
                    ),
                    timeout=press_again_timeout_ms,
                )
                if press_again is None:
                    return False
                press_again.click(timeout=5000, force=True)
                wait_first_visible(
                    (
                        frame2.locator(loading_selector),
                        frame1.locator(loading_selector),
                        page.locator(loading_selector),
                    ),
                    timeout=loading_timeout_ms,
                )
                page.wait_for_timeout(random.randint(settle_min_ms, settle_max_ms))
                if has_rate_limit():
                    print("[Error: Rate limit] captcha passed but registration is being throttled")
                    return False
                if has_skip_or_success():
                    return True
                if first_visible(frame2.locator(challenge_selector)) is not None:
                    continue
                if first_visible(frame1.locator(challenge_selector)) is not None:
                    continue
                return True
            except Exception:
                if has_rate_limit():
                    return False
                if has_skip_or_success():
                    return True
                continue
        return False

    def get_thread_page(self):
        browser = self.get_thread_browser()
        return self.create_browser_page(browser)

    def clean_up(self, page=None, type="all_browser"):
        if type == "done_browser" and page:
            context = page.context
            context.close()

        elif type == "all_browser":
            for p, b in self.active_resources:
                try:
                    b.close()
                except Exception: pass
                try:
                    p.stop()
                except Exception: pass
