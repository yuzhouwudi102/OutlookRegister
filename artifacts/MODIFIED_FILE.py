import os
import time
import json
import random
import threading
from datetime import datetime, timezone
from faker import Faker
from abc import ABC, abstractmethod
from recovery_mailbox import RecoveryMailboxClient


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
        self.recovery_email = data.get('recovery_email', '').strip()
        self.recovery_mailbox_enabled = data.get('recovery_mailbox', {}).get('auto_fetch', False)
        self.recovery_mailbox = RecoveryMailboxClient(data, self.proxy)

        self.thread_local = threading.local()
        self.cleanup_lock = threading.Lock()
        self.recovery_lock = threading.Lock()
        self.active_resources = []  # 记录资源以便关闭

        self.results_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Results')
        os.makedirs(self.results_dir, exist_ok=True)


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

    def handle_recovery_email_prompt(self, page, target_email=""):
        """填写 Microsoft 强制显示的备用邮箱页面。"""
        if not self.recovery_email:
            return None

        recovery_input = page.locator(
            '#EmailAddress, input[name="EmailAddress"], '
            'input[type="email"], input[placeholder="someone@example.com"]'
        ).first

        try:
            recovery_input.wait_for(state='visible', timeout=8000)
        except Exception:
            return None

        recovery_input.fill(self.recovery_email)
        requested_at = datetime.now(timezone.utc)

        next_button = None
        for selector in (
            '#iNext',
            '[data-testid="primaryButton"]',
            'button:has-text("下一步")',
            'input[type="submit"][value="下一步"]',
        ):
            candidate = page.locator(selector).first
            try:
                if candidate.count() > 0 and candidate.is_visible():
                    next_button = candidate
                    break
            except Exception:
                continue

        if next_button is None:
            print('[Error: Recovery Email] - 已填写备用邮箱，但未找到“下一步”按钮。')
            return True

        self.smooth_click(page, next_button)
        if not self.recovery_mailbox_enabled:
            print(
                f'[Action: Recovery Email] - 已填写 {self.recovery_email}。'
                '自动取码未启用，请手动输入安全代码。'
            )
            return True

        try:
            with self.recovery_lock:
                code = self.recovery_mailbox.wait_for_code(
                    self.get_thread_browser(),
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
                print('[Action: Recovery Email] - 已自动读取并填写备用邮箱验证码。')
        except Exception as exc:
            print(f'[Error: Recovery Email] - 自动取码或填写失败：{exc}')
            return False
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
        """
        通用逻辑:注册邮箱
        """

        self.reset_last_pos()
        fake = Faker()

        lastname = fake.last_name()
        firstname = fake.first_name()
        year = str(random.randint(1960, 2005))
        month = str(random.randint(1, 12))
        day = str(random.randint(1, 28))

        try:
            page.goto("https://outlook.live.com/mail/0/?prompt=create_account", timeout=20000, wait_until="domcontentloaded")
            consent_btn = page.get_by_text('同意并继续')
            consent_btn.wait_for(timeout=30000)
            start_time = time.time()
            self.wait_random_ratio(page, 0.06)
            self.smooth_click(page, consent_btn)
        except Exception:
            print("[Error: IP] - IP质量不佳，无法进入注册界面。")
            return False

        try:
            if self.email_suffix == "@hotmail.com":
                self.wait_random_ratio(page, 0.06)
                domain_btn = page.get_by_text("@outlook.com")
                self.smooth_click(page, domain_btn)
                option_btn = page.locator(f'[role="option"]:text-is("@hotmail.com")')
                self.smooth_click(page, option_btn)


            email_input = page.locator('[aria-label="新建电子邮件"]')
            self.smooth_type(page, email_input, email)

            primary_btn = page.locator('[data-testid="primaryButton"]')
            self.smooth_click(page, primary_btn)
            self.wait_random_ratio(page, 0.04)

            pwd_input = page.locator('[type="password"]')
            self.smooth_type(page, pwd_input, password)
            self.wait_random_ratio(page, 0.03)
            self.smooth_click(page, primary_btn)
            self.wait_random_ratio(page, 0.03)

            if page.get_by_text("请重试。如果仍然不起作用，请稍后再试。").count() > 0:
                print("[Error: IP or browser] - 当前IP注册频率过快。检查IP与是否为指纹浏览器并关闭了无头模式。")
                return False

            year_input = page.locator('[name="BirthYear"]')
            if year_input.count() > 0:
                self.smooth_click(page, year_input)
                year_input.fill(year)

            month_btn = page.locator('[name="BirthMonth"]')
            self.smooth_click(page, month_btn)
            self.wait_random_ratio(page, 0.03)
            m_opt = page.locator(f'[role="option"]:text-is("{month}月")')
            self.smooth_click(page, m_opt)

            self.wait_random_ratio(page, 0.03)
            day_btn = page.locator('[name="BirthDay"]')
            self.smooth_click(page, day_btn)
            self.wait_random_ratio(page, 0.03)

            d_opt = page.locator(f'[role="option"]:text-is("{day}日")')
            if d_opt.count() > 0:
                try:
                    d_opt.scroll_into_view_if_needed()
                except Exception:
                    pass
            self.smooth_click(page, d_opt)

            self.smooth_click(page, primary_btn)

            lname_input = page.locator('#lastNameInput')
            lname_input.wait_for(state='visible', timeout=8000)
            self.smooth_type(page, lname_input, lastname)

            self.wait_random_ratio(page, 0.02)
            fname_input = page.locator('#firstNameInput')
            fname_input.wait_for(state='visible', timeout=8000)
            self.smooth_type(page, fname_input, firstname)

            if time.time() - start_time < self.wait_time / 1000:
                page.wait_for_timeout(self.wait_time - (time.time() - start_time) * 1000)

            self.smooth_click(page, primary_btn)
            page.locator('span > [href="https://go.microsoft.com/fwlink/?LinkID=521839"]').wait_for(state='detached', timeout=22000)
            page.wait_for_timeout(400)

            if page.get_by_text('一些异常活动').count() or page.get_by_text('此站点正在维护，暂时无法使用，请稍后重试。').count() > 0:
                print("[Error: IP or browser] - 当前IP注册频率过快。检查IP与是否为指纹浏览器并关闭了无头模式。")
                return False

            if page.locator('iframe#enforcementFrame').count() > 0:
                print("[Error: FunCaptcha] - 验证码类型错误，非按压验证码。")
                return False

            captcha_result = self.handle_captcha(page)
            if not captcha_result:
                raise TimeoutError

        except Exception:
            print("[Error: IP] - 加载超时或因触发机器人检测导致按压次数达到最大仍未通过。")
            return False

        filename = os.path.join(self.results_dir, 'logged_email.txt' if self.enable_oauth2 else 'unlogged_email.txt')
        with open(filename, 'a', encoding='utf-8') as f:
            f.write(f"{email}{self.email_suffix}: {password}\n")
        print(f'[Success: Email Registration] - {email}{self.email_suffix}: {password}')

        if not self.enable_oauth2:
            return True

        recovery_email_status = self.handle_recovery_email_prompt(
            page, f"{email}{self.email_suffix}"
        )
        if recovery_email_status is False:
            return False
        recovery_email_required = recovery_email_status is True

        if not recovery_email_required:
            start_skip_time = time.time()
            while time.time() - start_skip_time < 20:
                try:
                    btn_skip = page.get_by_text("暂时跳过")
                    if btn_skip.count() > 0 and btn_skip.is_visible():
                        self.smooth_click(page, btn_skip)
                        page.wait_for_timeout(random.randint(1000, 1500))
                    else:
                        btn_skip.wait_for(timeout=7000)
                except Exception:
                    break

        try:
            if recovery_email_required:
                inbox_timeout = 60000 if self.recovery_mailbox_enabled else 300000
            else:
                inbox_timeout = 32000
            page.locator('[aria-label="新邮件"]').wait_for(timeout=inbox_timeout)
            return True
        except Exception:
            print('[Error: Timeout] - 邮箱未初始化，无法正常收件。')
            return False
