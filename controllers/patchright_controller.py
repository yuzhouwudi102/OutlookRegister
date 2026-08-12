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

        challenge_iframe = page.locator(
            'iframe[title="验证质询"], '
            'iframe[title="Verification challenge"]'
        ).first
        challenge_iframe.wait_for(state="visible", timeout=22000)

        frame1 = page.frame_locator(
            'iframe[title="验证质询"], '
            'iframe[title="Verification challenge"]'
        )
        frame2 = frame1.frame_locator('iframe[style*="display: block"]')
        challenge_selector = (
            '[aria-label="可访问性挑战"], '
            '[aria-label="Accessibility Challenge"], '
            '[aria-label="Accessible challenge"], '
            '[aria-label*="accessible challenge" i]'
        )
        press_again_selector = (
            '[aria-label="再次按下"], '
            '[aria-label="Press again"]'
        )
        loading_selector = (
            '[role="status"][aria-label="正在加载..."], '
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

        def wait_first_visible(locators, timeout=8000):
            deadline = time.monotonic() + timeout / 1000
            while time.monotonic() < deadline:
                for locator in locators:
                    candidate = first_visible(locator)
                    if candidate is not None:
                        return candidate
                page.wait_for_timeout(200)
            return None

        def click_accessibility_challenge():
            locators = (
                frame2.locator(challenge_selector),
                frame2.get_by_text(
                    "Accessible challenge",
                    exact=True,
                ),
                frame2.get_by_text(
                    "Accessibility Challenge",
                    exact=True,
                ),
                frame1.get_by_text(
                    "Accessible challenge",
                    exact=True,
                ),
                frame1.get_by_text(
                    "Accessibility Challenge",
                    exact=True,
                ),
                frame1.get_by_text(
                    "可访问性挑战",
                    exact=True,
                ),
            )
            candidate = wait_first_visible(locators)
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

        def press_and_hold():
            locators = (
                frame2.locator(
                    '[aria-label="Press and hold"], '
                    '[aria-label="按住"]'
                ),
                frame2.get_by_text(
                    "Press and hold",
                    exact=True,
                ),
                frame2.get_by_text(
                    "按住",
                    exact=True,
                ),
                frame1.get_by_text(
                    "Press and hold",
                    exact=True,
                ),
                frame1.get_by_text(
                    "按住",
                    exact=True,
                ),
            )
            candidate = wait_first_visible(locators)
            if candidate is None:
                return False
            box = candidate.bounding_box()
            if not box:
                return False
            tx = box["x"] + box["width"] / 2
            ty = box["y"] + box["height"] / 2
            self.smooth_move_to(page, tx, ty)
            page.mouse.move(tx, ty)
            page.mouse.down()
            try:
                started_at = time.monotonic()
                hold_deadline = started_at + 14
                minimum_release = started_at + 1.8
                while time.monotonic() < hold_deadline:
                    page.wait_for_timeout(250)
                    now = time.monotonic()
                    if now < minimum_release:
                        continue
                    try:
                        if not candidate.is_visible():
                            break
                    except Exception:
                        break
                    if (
                        page.get_by_text("暂时跳过").count() > 0
                        or page.get_by_text(
                            "Skip for now",
                            exact=False,
                        ).count() > 0
                    ):
                        break
            finally:
                page.mouse.up()
            self.set_last_pos(tx, ty)
            return True

        for _ in range(0, self.max_captcha_retries + 1):

            page.wait_for_timeout(random.randint(250, 450))
            if not click_accessibility_challenge():
                return False

            page.wait_for_timeout(random.randint(300, 600))
            if not press_and_hold():
                loc2 = first_visible(
                    frame2.locator(press_again_selector)
                )
                if loc2 is None:
                    return False
                loc2.click(timeout=5000)

            try:
                page.locator('.draw').wait_for(state="detached", timeout=14000)
                try:
                    # 简单的认为加载8秒后成功，暂不考虑请求.
                    page.locator(loading_selector).first.wait_for(timeout=5000)

                    captcha_passed = False
                    for _ in range(20):
                        if page.get_by_text('一些异常活动').count() or page.get_by_text('此站点正在维护，暂时无法使用，请稍后重试。').count() > 0:
                            print("[Error: Rate limit] - 正常通过验证码，但当前IP注册频率过快。")
                            return False
                        elif (
                            first_visible(
                                frame2.locator(challenge_selector)
                            )
                            is not None
                        ):
                            captcha_passed = False
                            page.wait_for_timeout(random.randint(500, 1000))
                            break
                        elif (
                            page.get_by_text("暂时跳过").count() > 0
                            or page.get_by_text(
                                "Skip for now",
                                exact=False,
                            ).count() > 0
                        ):
                            captcha_passed = True
                            break
                        page.wait_for_timeout(random.randint(375, 425))
                    else:
                        if (
                            first_visible(
                                frame2.locator(challenge_selector)
                            )
                            is None
                        ):
                            captcha_passed = True

                    if captcha_passed:
                        break

                except Exception:
                    if (
                        page.get_by_text('暂时跳过').count() > 0
                        or page.get_by_text(
                            "Skip for now",
                            exact=False,
                        ).count() > 0
                    ):
                        break
                    frame1.locator(
                        ':has-text("请再试一次"), '
                        ':has-text("Keep going"), '
                        ':has-text("a few more tries")'
                    ).first.wait_for(timeout=15000)
                    continue

            except Exception:
                if (
                    page.get_by_text('暂时跳过').count() > 0
                    or page.get_by_text(
                        "Skip for now",
                        exact=False,
                    ).count() > 0
                ):
                     break
                return False
        else: 
            return False

        return True

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
