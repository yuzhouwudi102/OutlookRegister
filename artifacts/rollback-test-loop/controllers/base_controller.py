import os
import time
import json
import random
import threading
from datetime import datetime, timezone
from faker import Faker
from abc import ABC, abstractmethod
from browser_fingerprint import (
    apply_runtime_overrides,
    build_context_options,
    build_init_script,
    build_launch_args,
    create_fingerprint_profile,
)
from recovery_mailbox import (
    RecoveryMailboxClient,
    get_accounts_file,
    list_authorized_emails,
    load_backup_accounts,
)


ENGLISH_MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def signup_option_labels(value, field_kind):
    """Return visible labels used by localized signup dropdowns."""
    number = int(value)
    labels = [str(number), f"{number:02d}"]

    if field_kind == "month":
        month_name = ENGLISH_MONTH_NAMES[number]
        labels.extend(
            (
                month_name,
                month_name[:3],
                f"{number}月",
            )
        )
    elif field_kind == "day":
        labels.append(f"{number}日")

    return tuple(dict.fromkeys(labels))


class BaseBrowserController(ABC):
    """
    所有浏览器通用的接口和共享逻辑
    """

    def __init__(self):
        with open('config.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.wait_time = data['bot_protection_wait'] * 1000
        self.max_captcha_retries = data['max_captcha_retries']
        self.enable_oauth2 = data["oauth2"]['enable_oauth2']
        self.proxy = data['proxy']
        self.email_suffix = data['email_suffix']
        self.config = data
        self.fingerprint_config = data.get('fingerprint', {})
        self.fingerprint_enabled = self.fingerprint_config.get(
            'enabled',
            True,
        )
        self.browser_headless = False
        self.recovery_mailbox_enabled = data.get('recovery_mailbox', {}).get('auto_fetch', False)
        self.recovery_accounts_file = get_accounts_file(data)

        self.thread_local = threading.local()
        self.cleanup_lock = threading.Lock()
        self.results_lock = threading.Lock()
        self.recovery_locks_guard = threading.Lock()
        self.recovery_locks = {}
        self.active_resources = []  # 记录资源以便关闭

        self.results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Results')
        os.makedirs(self.results_dir, exist_ok=True)

    def get_browser_launch_args(self):
        if not self.fingerprint_enabled:
            return ['--lang=zh-CN']
        return build_launch_args(self.fingerprint_config)

    def get_fingerprint_profile(self, browser):
        if not hasattr(self.thread_local, 'fingerprint_profile'):
            browser_version = getattr(browser, 'version', '')
            if callable(browser_version):
                browser_version = browser_version()
            self.thread_local.fingerprint_profile = (
                create_fingerprint_profile(
                    self.fingerprint_config,
                    browser_version=browser_version,
                )
            )
            profile = self.thread_local.fingerprint_profile
            print(
                '[Browser: Fingerprint] - '
                f'id={profile["profile_id"]}, '
                f'locale={profile["locale"]}, '
                f'timezone={profile["timezone_id"]}, '
                f'viewport={profile["viewport"]["width"]}x'
                f'{profile["viewport"]["height"]}, '
                'headless=False'
            )
        return self.thread_local.fingerprint_profile

    def create_browser_context(self, browser):
        if not self.fingerprint_enabled:
            return browser.new_context()

        profile = self.get_fingerprint_profile(browser)
        context = browser.new_context(**build_context_options(profile))
        context._fingerprint_init_disposable = context.add_init_script(
            script=build_init_script(profile)
        )
        return context

    def create_browser_page(self, browser):
        context = self.create_browser_context(browser)
        page = context.new_page()
        if self.fingerprint_enabled:
            profile = self.get_fingerprint_profile(browser)
            page._fingerprint_init_disposable = page.add_init_script(
                script=build_init_script(profile)
            )
            def apply_profile():
                try:
                    apply_runtime_overrides(page, profile)
                except Exception:
                    pass

            page.on("domcontentloaded", apply_profile)
            page.on("load", apply_profile)
            apply_profile()
        return page

    def get_last_pos(self):
        """获取当前线程的上一次鼠标位置 (x, y)"""
        return getattr(self.thread_local, 'last_pos', None)

    def set_last_pos(self, x, y):
        """设置当前线程的鼠标位置 (x, y)"""
        self.thread_local.last_pos = (float(x), float(y))

    def reset_last_pos(self):
        """重置当前线程的坐标历史"""
        if hasattr(self.thread_local, 'last_pos'):
            del self.thread_local.last_pos

    def wait_random_ratio(self, page, min_ratio, delta=0.02):

        actual_ratio = random.uniform(min_ratio, min_ratio + delta)
        page.wait_for_timeout(actual_ratio * self.wait_time)

    def smooth_move_to(self, page, target_x, target_y, steps=None):
        """从上一次坐标滑动到目标坐标"""
        last_pos = self.get_last_pos()
        if not last_pos:
            last_pos = (random.uniform(150, 450), random.uniform(100, 350))
            try:
                page.mouse.move(last_pos[0], last_pos[1])
            except Exception:
                pass

        if steps is None:
            steps = random.randint(6, 14)

        try:
            page.mouse.move(target_x, target_y, steps=steps)
        except Exception:
            pass

        self.set_last_pos(target_x, target_y)

    def smooth_click(self, page, locator, offset_range=5, click_delay_range=(60, 160)):
        """点击方法"""
        try:
            box = locator.bounding_box()
            if not box:
                locator.click()
                return False

            tx = box['x'] + box['width'] / 2 + random.uniform(-offset_range, offset_range)
            ty = box['y'] + box['height'] / 2 + random.uniform(-offset_range, offset_range)

            self.smooth_move_to(page, tx, ty)

            pause_ms = random.randint(click_delay_range[0], click_delay_range[1])
            page.wait_for_timeout(pause_ms)

            page.mouse.click(tx, ty)
            self.set_last_pos(tx, ty)
            return True
        except Exception:
            try:
                locator.click()
            except Exception:
                pass
            return False

    def smooth_type(self, page, locator, text, click_first=True):
        """输入方法"""
        if click_first:
            self.smooth_click(page, locator)

        for char in text:
            try:
                locator.type(char, delay=random.randint(40, 110))
            except Exception:
                break

    def choose_recovery_mailbox(self):
        accounts = load_backup_accounts(self.recovery_accounts_file)
        if not accounts:
            raise RuntimeError(
                f"备用邮箱列表为空：{self.recovery_accounts_file}"
            )

        candidates = accounts
        if self.recovery_mailbox_enabled:
            authorized_emails = list_authorized_emails(self.config)
            candidates = [
                account
                for account in accounts
                if account.email in authorized_emails
            ]
            if not candidates:
                raise RuntimeError(
                    "没有已授权的备用邮箱，请先运行 "
                    "authorize_recovery_mailbox.py"
                )

        account = random.choice(candidates)
        client = RecoveryMailboxClient(
            self.config,
            self.proxy,
            account=account,
        )
        return account, client

    def get_recovery_mailbox_lock(self, email):
        with self.recovery_locks_guard:
            if email not in self.recovery_locks:
                self.recovery_locks[email] = threading.Lock()
            return self.recovery_locks[email]

    def handle_recovery_email_prompt(self, page, target_email=""):
        """填写 Microsoft 强制显示的备用邮箱页面。"""
        recovery_input = page.locator(
            '#EmailAddress, input[name="EmailAddress"], '
            'input[type="email"], input[placeholder="someone@example.com"]'
        ).first

        try:
            recovery_input.wait_for(state='visible', timeout=8000)
        except Exception:
            return None

        try:
            account, mailbox_client = self.choose_recovery_mailbox()
        except Exception as exc:
            print(f'[Error: Recovery Email] - 选择备用邮箱失败：{exc}')
            return False

        mailbox_lock = self.get_recovery_mailbox_lock(account.email)
        with mailbox_lock:
            recovery_input.fill(account.email)
            requested_at = datetime.now(timezone.utc)

            next_button = None
            for selector in (
                '#iNext',
                '[data-testid="primaryButton"]',
                'button:has-text("下一步")',
                'button:has-text("Next")',
                'input[type="submit"][value="下一步"]',
                'input[type="submit"][value="Next"]',
            ):
                candidate = page.locator(selector).first
                try:
                    if candidate.count() > 0 and candidate.is_visible():
                        next_button = candidate
                        break
                except Exception:
                    continue

            if next_button is None:
                print(
                    '[Error: Recovery Email] - '
                    '已填写备用邮箱，但未找到“下一步/Next”按钮。'
                )
                return False

            self.smooth_click(page, next_button)
            if not self.recovery_mailbox_enabled:
                print(
                    f'[Action: Recovery Email] - 已随机填写 {account.email}。'
                    '自动取码未启用，请手动输入安全代码。'
                )
                return True

            try:
                code = mailbox_client.wait_for_code(
                    requested_at=requested_at,
                    target_email=target_email,
                )
                code_input = page.locator(
                    'input[name="VerificationCode"], input[name="otc"], '
                    'input[name="code"], input[type="tel"], input[inputmode="numeric"], '
                    'input[aria-label*="code" i], input[placeholder*="code" i], '
                    'input[aria-label*="代码"], input[placeholder*="代码"]'
                ).first
                code_input.wait_for(state='visible', timeout=15000)
                code_input.fill(code)

                submit_button = None
                for selector in (
                    '#iNext',
                    '[data-testid="primaryButton"]',
                    'button[type="submit"]',
                    'input[type="submit"]',
                ):
                    candidate = page.locator(selector).first
                    if candidate.count() > 0 and candidate.is_visible():
                        submit_button = candidate
                        break
                if submit_button is None:
                    raise RuntimeError('验证码已填写，但没有找到提交按钮')

                self.smooth_click(page, submit_button)
                print(
                    f'[Action: Recovery Email] - 已使用 {account.email} '
                    '自动读取并填写验证码。'
                )
            except Exception as exc:
                print(f'[Error: Recovery Email] - 自动取码或填写失败：{exc}')
                return False
            return True

    def save_registered_account(self, email, password):
        full_email = f"{email}{self.email_suffix}"
        filename = os.path.join(
            self.results_dir,
            'logged_email.txt' if self.enable_oauth2
            else 'unlogged_email.txt',
        )
        record = f"{full_email}: {password}"

        with self.results_lock:
            os.makedirs(self.results_dir, exist_ok=True)
            with open(filename, 'a+', encoding='utf-8') as file:
                file.seek(0)
                existing_records = {
                    line.strip()
                    for line in file.read().splitlines()
                    if line.strip()
                }
                if record not in existing_records:
                    file.seek(0, os.SEEK_END)
                    file.write(f"{record}\n")
                    file.flush()
                    os.fsync(file.fileno())

        print(f'[Saved: Email Account] - {full_email} -> {filename}')
        return filename

    def complete_post_registration(self, page, full_email):
        recovery_email_status = self.handle_recovery_email_prompt(
            page,
            full_email,
        )
        if recovery_email_status is False:
            return False
        recovery_email_required = recovery_email_status is True

        if not recovery_email_required:
            start_skip_time = time.time()
            while time.time() - start_skip_time < 20:
                try:
                    btn_skip = None
                    for text in ("暂时跳过", "Skip for now"):
                        candidate = page.get_by_text(
                            text,
                            exact=False,
                        ).first
                        if (
                            candidate.count() > 0
                            and candidate.is_visible()
                        ):
                            btn_skip = candidate
                            break
                    if btn_skip is None:
                        page.wait_for_timeout(700)
                        continue
                    self.smooth_click(page, btn_skip)
                    page.wait_for_timeout(random.randint(1000, 1500))
                except Exception:
                    break

        try:
            if recovery_email_required:
                inbox_timeout = (
                    60000 if self.recovery_mailbox_enabled else 300000
                )
            else:
                inbox_timeout = 32000
            inbox_selector = (
                '[aria-label="新邮件"], '
                '[aria-label="New mail"], '
                '[aria-label="New message"]'
            )
            inbox_locator = page.locator(inbox_selector)
            try:
                inbox_locator = inbox_locator.first
            except AttributeError:
                pass
            inbox_locator.wait_for(timeout=inbox_timeout)
            return True
        except Exception:
            print('[Error: Timeout] - 邮箱未初始化，无法正常收件。')
            return False

    def finalize_registered_account(self, page, email, password):
        full_email = f"{email}{self.email_suffix}"
        if not self.complete_post_registration(page, full_email):
            return False

        self.save_registered_account(email, password)
        print(f'[Success: Email Registration] - {full_email}')
        return True

    @abstractmethod
    def launch_browser(self):
        """
        获取浏览器实例,返回playwright_instance, browser_instance
        """
        pass

    @abstractmethod
    def handle_captcha(self, page):
        """
        验证码处理流程
        """
        pass

    @abstractmethod
    def clean_up(self, page=None, type="all_browser"):
        """
        清理自己创建的内容
        一个是单进程结束后关闭进程，另一个是程序结束后清除所有内容
        """
        pass

    @abstractmethod
    def get_thread_page(self):
        """
        返回页面
        """

    def get_thread_browser(self):
        """
        通用逻辑:获取不同进程的浏览器
        """
        if not hasattr(self.thread_local, "browser"):
            p, b = self.launch_browser()
            if not p:
                return False

            self.thread_local.playwright = p
            self.thread_local.browser = b

            with self.cleanup_lock:
                self.active_resources.append((p, b))

        return self.thread_local.browser

    def outlook_register(self, page, email, password):
        """Fill the current Microsoft signup flow and finish registration."""

        self.reset_last_pos()
        fake = Faker()

        lastname = fake.last_name()
        firstname = fake.first_name()
        year = str(random.randint(1960, 2005))
        month = str(random.randint(1, 12))
        day = str(random.randint(1, 28))
        start_time = time.time()

        def first_visible(selectors, timeout=8000):
            deadline = time.time() + timeout / 1000
            while time.time() < deadline:
                for selector in selectors:
                    try:
                        candidates = page.locator(selector)
                        for index in range(min(candidates.count(), 30)):
                            candidate = candidates.nth(index)
                            if candidate.is_visible():
                                return candidate
                    except Exception:
                        continue
                page.wait_for_timeout(200)
            raise TimeoutError(f"No visible element found: {', '.join(selectors)}")

        def click_primary():
            button = first_visible(
                (
                    '#iSignupAction',
                    '#iNext',
                    '[data-testid="primaryButton"]',
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:has-text("Next")',
                ),
                timeout=10000,
            )
            self.smooth_click(page, button)

        def fill_text(selectors, value, timeout=10000):
            field = first_visible(selectors, timeout=timeout)
            self.smooth_type(page, field, value)
            return field

        def select_dropdown(selectors, value, field_kind):
            field = first_visible(selectors, timeout=10000)
            option_labels = signup_option_labels(value, field_kind)
            try:
                tag_name = field.evaluate("element => element.tagName")
            except Exception:
                tag_name = ""

            if tag_name.upper() == "SELECT":
                option_attempts = [
                    {"value": str(int(value))},
                    {"value": f"{int(value):02d}"},
                ]
                option_attempts.extend(
                    {"label": label}
                    for label in option_labels
                )
                for option_kwargs in option_attempts:
                    try:
                        field.select_option(**option_kwargs)
                        return
                    except Exception:
                        continue

            self.smooth_click(page, field)
            option_selectors = []
            for label in option_labels:
                option_selectors.extend(
                    (
                        f'[role="option"]:text-is("{label}")',
                        f'[role="option"][aria-label="{label}"]',
                        f'option:text-is("{label}")',
                    )
                )
            option_selectors.extend(
                (
                    f'[role="option"][data-value="{int(value)}"]',
                    f'option[value="{int(value)}"]',
                    f'option[value="{int(value):02d}"]',
                )
            )
            try:
                option = first_visible(
                    tuple(option_selectors),
                    timeout=7000,
                )
            except TimeoutError as exc:
                raise TimeoutError(
                    f"No visible {field_kind} option found for {value}; "
                    f"tried labels: {', '.join(option_labels)}"
                ) from exc
            self.smooth_click(page, option)

        email_selectors = (
            '#MemberName',
            'input[name="MemberName"]',
            'input[aria-label="New email"]',
            'input[aria-label*="email" i]',
            'input[placeholder*="email" i]',
            'input[type="email"]',
        )

        try:
            page.goto(
                "https://outlook.live.com/mail/0/?prompt=create_account",
                timeout=20000,
                wait_until="domcontentloaded",
            )

            # The current page can show "New email" directly without consent.
            consent_selectors = (
                'button:has-text("Agree and continue")',
                'input[type="submit"][value*="Agree" i]',
            )
            try:
                consent_btn = first_visible(consent_selectors, timeout=4000)
            except Exception:
                consent_btn = None

            if consent_btn is not None:
                self.wait_random_ratio(page, 0.06)
                self.smooth_click(page, consent_btn)

            first_visible(email_selectors, timeout=30000)
        except Exception:
            print(
                "[Error: Signup Page] - Email input was not found; "
                "check page loading and IP status."
            )
            return False

        try:
            if self.email_suffix == "@hotmail.com":
                self.wait_random_ratio(page, 0.06)
                domain_btn = first_visible(
                    (
                        'button:has-text("@outlook.com")',
                        '[role="button"]:has-text("@outlook.com")',
                        'text="@outlook.com"',
                    ),
                    timeout=8000,
                )
                self.smooth_click(page, domain_btn)
                option_btn = first_visible(
                    (
                        '[role="option"]:text-is("@hotmail.com")',
                        '[role="option"]:has-text("@hotmail.com")',
                        'text="@hotmail.com"',
                    ),
                    timeout=5000,
                )
                self.smooth_click(page, option_btn)

            fill_text(email_selectors, email)
            click_primary()
            self.wait_random_ratio(page, 0.04)

            fill_text(
                (
                    '#PasswordInput',
                    'input[name="Password"]',
                    'input[type="password"]',
                ),
                password,
            )
            self.wait_random_ratio(page, 0.03)
            click_primary()
            self.wait_random_ratio(page, 0.03)

            if (
                page.get_by_text("Please try again later", exact=False).count() > 0
            ):
                print(
                    "[Error: IP or browser] - The current IP or signup "
                    "frequency was limited."
                )
                return False

            year_input = first_visible(
                (
                    '#BirthYearInput',
                    'input[name="BirthYear"]',
                    'input[aria-label*="year" i]',
                ),
                timeout=10000,
            )
            year_input.fill(year)

            select_dropdown(
                (
                    'select[name="BirthMonth"]',
                    '[name="BirthMonth"]',
                    'select[aria-label*="month" i]',
                    '[aria-label*="month" i]',
                ),
                month,
                "month",
            )
            self.wait_random_ratio(page, 0.03)
            select_dropdown(
                (
                    'select[name="BirthDay"]',
                    '[name="BirthDay"]',
                    'select[aria-label*="day" i]',
                    '[aria-label*="day" i]',
                ),
                day,
                "day",
            )
            click_primary()

            fill_text(
                (
                    '#lastNameInput',
                    'input[name="LastName"]',
                    'input[aria-label*="last name" i]',
                    'input[placeholder*="last name" i]',
                ),
                lastname,
                timeout=10000,
            )
            self.wait_random_ratio(page, 0.02)
            fill_text(
                (
                    '#firstNameInput',
                    'input[name="FirstName"]',
                    'input[aria-label*="first name" i]',
                    'input[placeholder*="first name" i]',
                ),
                firstname,
                timeout=10000,
            )

            if time.time() - start_time < self.wait_time / 1000:
                page.wait_for_timeout(
                    self.wait_time - (time.time() - start_time) * 1000
                )

            click_primary()
            privacy_link = page.locator(
                'span > [href="https://go.microsoft.com/fwlink/?LinkID=521839"]'
            ).first
            if privacy_link.count() > 0:
                privacy_link.wait_for(state='detached', timeout=22000)
            page.wait_for_timeout(400)

            if (
                page.get_by_text("Something went wrong", exact=False).count() > 0
                or page.get_by_text('一些异常活动').count() > 0
                or page.get_by_text(
                    '此站点正在维护，暂时无法使用，请稍后重试。'
                ).count() > 0
            ):
                print(
                    "[Error: IP or browser] - The current IP or browser "
                    "triggered a signup restriction."
                )
                return False

            if page.locator('iframe#enforcementFrame').count() > 0:
                print("[Error: FunCaptcha] - Unsupported captcha type.")
                return False

            captcha_result = self.handle_captcha(page)
            if not captcha_result:
                raise TimeoutError

        except Exception as exc:
            print(f"[Error: Signup Flow] - Signup page handling failed: {exc}")
            return False

        return self.finalize_registered_account(
            page,
            email,
            password,
        )
