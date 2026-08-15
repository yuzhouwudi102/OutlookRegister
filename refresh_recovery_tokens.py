"""逐步检查并刷新 Results/recovery_mailbox_token 下的 OAuth JSON 令牌。"""

import argparse
import json
import time
from pathlib import Path

from recovery_mailbox import (
    OUTLOOK_TOKEN_SEPARATOR,
    RecoveryMailboxAccount,
    RecoveryMailboxClient,
    _atomic_write_json,
    get_outlook_token_file,
    get_token_dir,
    save_outlook_token_record,
)


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def read_outlook_records(path):
    """Return email -> password for the existing outlook_token records."""
    records = {}
    if not path.exists():
        return records
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        parts = line.split(OUTLOOK_TOKEN_SEPARATOR, 4)
        if len(parts) != 5:
            print(f"[跳过 outlook_token] 第 {line_number} 行字段数不是 5")
            continue
        email = parts[0].strip().lower()
        if email:
            records[email] = parts[1]
    return records


def token_needs_refresh(token, now=None, skew_seconds=60):
    now = time.time() if now is None else float(now)
    try:
        expires_at = float(token.get("expires_at", 0))
    except (TypeError, ValueError):
        return True
    return expires_at <= now + float(skew_seconds)


def refresh_token_file(
    config,
    token_path,
    outlook_passwords,
    skew_seconds=60,
    dry_run=False,
):
    """Check one JSON file, refresh it when needed, then sync outlook_token.txt."""
    try:
        token = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return "failed", f"JSON 读取失败：{exc}"

    email = str(token.get("email", "")).strip().lower()
    if not email:
        return "failed", "缺少 email"

    try:
        expires_at = float(token.get("expires_at", 0))
    except (TypeError, ValueError):
        expires_at = 0

    if not token_needs_refresh(token, skew_seconds=skew_seconds):
        return "skipped", f"未过期（expires_at={expires_at:.3f}）"

    refresh_token = str(token.get("refresh_token", ""))
    if not refresh_token:
        return "failed", "已过期且没有 refresh_token"

    account = RecoveryMailboxAccount(
        email=email,
        password=outlook_passwords.get(email, ""),
    )
    client = RecoveryMailboxClient(
        config,
        config.get("proxy", ""),
        account=account,
    )

    if dry_run:
        return "would_refresh", f"需要刷新（expires_at={expires_at:.3f}）"

    refreshed = client._refresh_token(refresh_token)
    _atomic_write_json(token_path, refreshed)

    password = outlook_passwords.get(email)
    if password is None:
        return (
            "updated_json_only",
            "JSON 已更新；outlook_token.txt 中没有对应邮箱记录",
        )

    save_outlook_token_record(config, account, refreshed)
    return "updated", "JSON 与 outlook_token.txt 均已更新"


def run(config, skew_seconds=60, dry_run=False):
    token_dir = get_token_dir(config)
    outlook_path = get_outlook_token_file(config)
    outlook_passwords = read_outlook_records(outlook_path)
    if not token_dir.exists():
        raise FileNotFoundError(f"找不到令牌目录：{token_dir}")

    json_files = sorted(token_dir.glob("*.json"))
    if not json_files:
        print(f"令牌目录为空：{token_dir}")
        return 0

    counts = {
        "skipped": 0,
        "updated": 0,
        "updated_json_only": 0,
        "would_refresh": 0,
        "failed": 0,
    }
    print(f"开始检查 {len(json_files)} 个 JSON 令牌：{token_dir}")
    for index, token_path in enumerate(json_files, start=1):
        print(f"[{index}/{len(json_files)}] 检查 {token_path.name}")
        try:
            status, detail = refresh_token_file(
                config,
                token_path,
                outlook_passwords,
                skew_seconds=skew_seconds,
                dry_run=dry_run,
            )
        except Exception as exc:  # keep processing the remaining files
            status, detail = "failed", f"刷新异常：{exc}"
        counts[status] += 1
        print(f"  [{status}] {detail}")

    print(
        "处理完成："
        f"更新 {counts['updated']}，"
        f"仅更新 JSON {counts['updated_json_only']}，"
        f"未过期 {counts['skipped']}，"
        f"待刷新 {counts['would_refresh']}，"
        f"失败 {counts['failed']}。"
    )
    return 1 if counts["failed"] else 0


def main():
    parser = argparse.ArgumentParser(
        description="逐步检查并刷新 recovery_mailbox_token 下的 JSON 令牌"
    )
    parser.add_argument(
        "--skew-seconds",
        type=float,
        default=60,
        help="提前多少秒视为即将过期（默认 60）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查，不写入 JSON 或 outlook_token.txt",
    )
    args = parser.parse_args()
    return run(load_config(), args.skew_seconds, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
