import os
import time
import json
from get_token import get_access_token
from concurrent.futures import ThreadPoolExecutor
from utils import random_email, generate_strong_password
from controllers.patchright_controller import PatchrightController
from controllers.playwright_controller import PlaywrightController
from recovery_mailbox import (
    build_loop_token_payload,
    validate_loop_creation,
    write_loop_backup_accounts,
    write_recovery_mailbox_token,
)



# --- 不确定有无帮助 ---
# 0. 视窗大小
# 1. CDP 检测：wait_for_timeout --> time.sleep()
# 2. 使用 launch_persistent_context 
# 3. 避免短时间访问
# 4. 模拟真人轨迹
# 时区

def process_single_flow(controller, loop_account=None):
    page = None
    email = None
    password = None

    try:
        email = random_email()
        password = generate_strong_password()
        print(
            f"[Attempt: Email Registration] - "
            f"{email}{controller.email_suffix}: {password}",
            flush=True,
        )

        if loop_account is not None:
            controller.set_loop_recovery_account(loop_account)

        page = controller.get_thread_page()

        # 调用 controller 特定的注册方法 
        result = controller.outlook_register(page, email, password)

        if result and not controller.enable_oauth2:
            return True
        elif not result:
            return False

        token_result = get_access_token(page, email)
        if token_result[0]:
            refresh_token, access_token, expire_at =  token_result
            with open(os.path.join(os.path.dirname(__file__), 'Results', 'outlook_token.txt'), 'a', encoding='utf-8') as f2:
                f2.write(f"{email}{controller.email_suffix}---{password}---{refresh_token}---{access_token}---{expire_at}\n") 
            print(f'[Success: TokenAuth] - {email}{controller.email_suffix}')

            if controller.loop_creation_enabled:
                token_payload = build_loop_token_payload(
                    f"{email}{controller.email_suffix}",
                    refresh_token,
                    access_token,
                    expire_at,
                )
                with controller.loop_creation_lock:
                    created_accounts = getattr(
                        controller,
                        "loop_created_accounts",
                        None,
                    )
                    if not isinstance(created_accounts, dict):
                        created_accounts = {}
                        controller.loop_created_accounts = created_accounts
                    created_accounts[
                        f"{email}{controller.email_suffix}".strip().lower()
                    ] = password
                    write_loop_backup_accounts(
                        controller.config,
                        created_accounts,
                        token_payload,
                    )
                    token_path = write_recovery_mailbox_token(
                        controller.config,
                        token_payload,
                    )
                    print(
                        f"[Saved: Recovery Token] - {token_path}",
                        flush=True,
                    )
            return True
        else:
            return False

    except Exception as e:
        print(e)
        return False
    
    finally:

        controller.clean_up(page, "done_browser")

def run_concurrent_flows(
    controller,
    concurrent_flows=10,
    max_tasks=100,
    loop_accounts=None,
):
    task_counter = 0
    succeeded_tasks = 0
    failed_tasks = 0

    if loop_accounts is not None:
        # Start a fresh next-generation backup for this Loop Creation run.
        # process_single_flow updates it while holding loop_creation_lock.
        controller.loop_created_accounts = {}

    with ThreadPoolExecutor(max_workers=concurrent_flows) as executor:
        running_futures = set()

        while task_counter < max_tasks or len(running_futures) > 0:
            done_futures = {f for f in running_futures if f.done()}
            for future in done_futures:
                try:
                    if future.result():
                        succeeded_tasks += 1
                    else:
                        failed_tasks += 1
                except Exception as e:
                    failed_tasks += 1
                    print(e)
                running_futures.remove(future)

            while len(running_futures) < concurrent_flows and task_counter < max_tasks:
                loop_account = (
                    loop_accounts[task_counter]
                    if loop_accounts is not None
                    else None
                )
                new_future = executor.submit(
                    process_single_flow,
                    controller,
                    loop_account,
                )
                running_futures.add(new_future)
                task_counter += 1
                if max_tasks > 1 and task_counter % (max_tasks // 2) == 0:
                    print(f"已提交 {task_counter}/{max_tasks} 任务.")
                elif max_tasks == 1:
                    print(f"已提交 {task_counter}/{max_tasks} 任务.")

            time.sleep(0.5)

    print(f"\n[Result] - 共: {max_tasks}, 成功 {succeeded_tasks}, 失败 {failed_tasks}")


if __name__ == "__main__":

    with open('config.json', 'r', encoding='utf-8') as f:
        data = json.load(f) 
    os.makedirs("Results", exist_ok=True)

    max_tasks = data["max_tasks"]
    concurrent_flows = data["concurrent_flows"]
    try:
        loop_creation_enabled, loop_accounts = validate_loop_creation(
            data,
            max_tasks,
        )
    except (TypeError, ValueError) as exc:
        print(str(exc))
        raise SystemExit(1)

    if data["choose_browser"] =="patchright":
        selected_controller = PatchrightController()
    elif data["choose_browser"] =="playwright":
        selected_controller = PlaywrightController()
    else:
        print("不支持的浏览器类型，填写patchright或者playwright")
  

    try:
        run_concurrent_flows(
            selected_controller,
            concurrent_flows,
            max_tasks,
            loop_accounts if loop_creation_enabled else None,
        )
    finally:
        selected_controller.clean_up(type="all_browser")
