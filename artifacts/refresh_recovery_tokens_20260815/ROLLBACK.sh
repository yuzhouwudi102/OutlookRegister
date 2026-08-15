#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 TARGET_ROOT" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="$1"

cp "$SCRIPT_DIR/BASELINE_recovery_mailbox.py" "$TARGET_ROOT/recovery_mailbox.py"
cp "$SCRIPT_DIR/BASELINE_test_recovery_mailbox.py" "$TARGET_ROOT/tests/test_recovery_mailbox.py"
cp "$SCRIPT_DIR/BASELINE_outlook_token.txt" "$TARGET_ROOT/Results/outlook_token.txt"
rm -f "$TARGET_ROOT/refresh_recovery_tokens.py"
rm -f "$TARGET_ROOT/tests/test_refresh_recovery_tokens.py"

echo "ROLLBACK_OK: removed standalone refresh script and restored baseline files"
