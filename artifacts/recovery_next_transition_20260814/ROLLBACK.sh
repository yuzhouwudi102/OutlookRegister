#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 TARGET_ROOT" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="$1"

cp "$SCRIPT_DIR/BASELINE_base_controller.py" \
  "$TARGET_ROOT/controllers/base_controller.py"
cp "$SCRIPT_DIR/BASELINE_test_recovery_mailbox.py" \
  "$TARGET_ROOT/tests/test_recovery_mailbox.py"

echo "ROLLBACK_OK: restored controllers/base_controller.py and tests/test_recovery_mailbox.py"
