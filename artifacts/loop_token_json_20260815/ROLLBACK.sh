#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 TARGET_ROOT" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="$1"

cp "$SCRIPT_DIR/BASELINE_main.py" "$TARGET_ROOT/main.py"
cp "$SCRIPT_DIR/BASELINE_recovery_mailbox.py" "$TARGET_ROOT/recovery_mailbox.py"
cp "$SCRIPT_DIR/BASELINE_test_recovery_mailbox.py" "$TARGET_ROOT/tests/test_recovery_mailbox.py"
cp "$SCRIPT_DIR/BASELINE_outlook_token.txt" "$TARGET_ROOT/Results/outlook_token.txt"
rm -f "$TARGET_ROOT/Results/recovery_mailbox_token/tkhzplsvplot_outlook.com_1390633a67.json"

echo "ROLLBACK_OK: restored loop-token code and source token file"
