#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET=${1:-"$SCRIPT_DIR/../.."}
cp "$SCRIPT_DIR/baseline/controllers/patchright_controller.py" "$TARGET/controllers/patchright_controller.py"
cp "$SCRIPT_DIR/baseline/controllers/base_controller.py" "$TARGET/controllers/base_controller.py"
cp "$SCRIPT_DIR/baseline/tests/test_signup_flow.py" "$TARGET/tests/test_signup_flow.py"
cp "$SCRIPT_DIR/baseline/tests/test_recovery_mailbox.py" "$TARGET/tests/test_recovery_mailbox.py"
