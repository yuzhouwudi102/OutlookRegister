#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_ROOT="${1:-$(pwd)}"
cp "$SCRIPT_DIR/baseline_recovery_mailbox.py" "$TARGET_ROOT/recovery_mailbox.py"
mkdir -p "$TARGET_ROOT/controllers" "$TARGET_ROOT/tests"
cp "$SCRIPT_DIR/baseline_base_controller.py" "$TARGET_ROOT/controllers/base_controller.py"
cp "$SCRIPT_DIR/baseline_test_recovery_mailbox.py" "$TARGET_ROOT/tests/test_recovery_mailbox.py"
echo "ROLLBACK_OK: restored recovery_mailbox.py, controllers/base_controller.py, tests/test_recovery_mailbox.py"
