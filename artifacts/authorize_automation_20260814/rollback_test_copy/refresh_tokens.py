import json
import os
import tempfile
import time
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
TOKEN_PATH = BASE_DIR / "Results" / "outlook_token.txt"
TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
SEPARATOR = "---"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = json.load(file)

    oauth2 = config.get("oauth2", {})
    client_id = oauth2.get("client_id", "").strip()
    scopes = oauth2.get("Scopes", [])
    if not client_id:
        raise ValueError("config.json 中缺少 oauth2.client_id")
    if not scopes:
        raise ValueError("config.json 中缺少 oauth2.Scopes")

    return config, client_id, scopes


def parse_record(line, line_number):
    parts = line.split(SEPARATOR, 4)
    if len(parts) != 5:
        raise ValueError(f"第 {line_number} 行不是 5 个字段")

    email, password, refresh_token, access_token, expire_at_text = parts
    if not email or not refresh_token:
        raise ValueError(f"第 {line_number} 行缺少邮箱或 refresh_token")

    try:
        expire_at = float(expire_at_text)
    except ValueError as exc:
        raise ValueError(f"第 {line_number} 行的过期时间无效") from exc

    return email, password, refresh_token, access_token, expire_at


def refresh_access_token(session, client_id, scopes, refresh_token, proxy):
    proxies = {"http": proxy, "https": proxy} if proxy else None
    response = session.post(
        TOKEN_ENDPOINT,
        data={
            "client_id": client_id,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(scopes),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        proxies=proxies,
        timeout=30,
    )

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Microsoft 返回了非 JSON 响应（HTTP {response.status_code}）") from exc

    if not response.ok:
        error = result.get("error", f"HTTP {response.status_code}")
        description = result.get("error_description", "未知错误").splitlines()[0]
        raise RuntimeError(f"{error}: {description}")

    access_token = result.get("access_token")
    expires_in = result.get("expires_in")
    if not access_token or expires_in is None:
        raise RuntimeError("Microsoft 响应中缺少 access_token 或 expires_in")

    new_refresh_token = result.get("refresh_token", refresh_token)
    expire_at = time.time() + float(expires_in)
    return new_refresh_token, access_token, expire_at


def atomic_write(path, lines, trailing_newline):
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write("\n".join(lines))
            if trailing_newline and lines:
                file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)


def main():
    config, client_id, scopes = load_config()
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"找不到 token 文件：{TOKEN_PATH}")

    original_text = TOKEN_PATH.read_text(encoding="utf-8")
    lines = original_text.splitlines()
    trailing_newline = original_text.endswith(("\n", "\r"))
    proxy = (config.get("proxy") or "").strip()
    updated_count = 0
    failed_count = 0
    skipped_count = 0
    output_lines = []

    with requests.Session() as session:
        for line_number, original_line in enumerate(lines, start=1):
            if not original_line.strip():
                output_lines.append(original_line)
                continue

            try:
                email, password, refresh_token, access_token, expire_at = parse_record(
                    original_line, line_number
                )
            except ValueError as exc:
                print(f"[跳过] {exc}")
                failed_count += 1
                output_lines.append(original_line)
                continue

            if expire_at > time.time():
                print(f"[未过期] {email}")
                skipped_count += 1
                output_lines.append(original_line)
                continue

            try:
                new_refresh_token, new_access_token, new_expire_at = refresh_access_token(
                    session,
                    client_id,
                    scopes,
                    refresh_token,
                    proxy,
                )
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                print(f"[刷新失败] {email}: {exc}")
                failed_count += 1
                output_lines.append(original_line)
                continue

            output_lines.append(
                SEPARATOR.join(
                    (
                        email,
                        password,
                        new_refresh_token,
                        new_access_token,
                        str(new_expire_at),
                    )
                )
            )
            updated_count += 1
            print(f"[已更新] {email}")

    if updated_count:
        atomic_write(TOKEN_PATH, output_lines, trailing_newline)
        print(f"已原子更新文件：{TOKEN_PATH}")
    else:
        print("没有成功刷新的记录，原文件未改动。")

    print(
        f"处理完成：更新 {updated_count}，未过期 {skipped_count}，失败或格式错误 {failed_count}。"
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f"[程序错误] {exc}")
        raise SystemExit(1)
