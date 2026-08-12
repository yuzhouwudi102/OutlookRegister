#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:?target file is required}"
BASELINE="${2:?baseline file is required}"

cp -- "$BASELINE" "$TARGET"
printf 'RESTORED target=%s from=%s\n' "$TARGET" "$BASELINE"
