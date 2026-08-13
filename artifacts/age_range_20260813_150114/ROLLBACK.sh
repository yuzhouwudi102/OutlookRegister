#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cp "$ROOT/artifacts/age_range_20260813_150114/baseline/controllers/base_controller.py" "$ROOT/controllers/base_controller.py"
cp "$ROOT/artifacts/age_range_20260813_150114/baseline/tests/test_signup_flow.py" "$ROOT/tests/test_signup_flow.py"