#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 TARGET_ROOT" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="$1"

cp "$SCRIPT_DIR/BASELINE_config.json" "$TARGET_ROOT/config.json"
cp "$SCRIPT_DIR/BASELINE_requirements.txt" "$TARGET_ROOT/requirements.txt"
cp "$SCRIPT_DIR/BASELINE_authorize_recovery_mailbox.py" "$TARGET_ROOT/authorize_recovery_mailbox.py"
cp "$SCRIPT_DIR/BASELINE_recovery_mailbox.py" "$TARGET_ROOT/recovery_mailbox.py"
cp "$SCRIPT_DIR/BASELINE_patchright_controller.py" "$TARGET_ROOT/controllers/patchright_controller.py"
cp "$SCRIPT_DIR/BASELINE_playwright_controller.py" "$TARGET_ROOT/controllers/playwright_controller.py"
rm -f "$TARGET_ROOT/proxy_utils.py" "$TARGET_ROOT/tests/test_proxy_utils.py"

echo "ROLLBACK_OK: restored SOCKS5-related files to baseline"
