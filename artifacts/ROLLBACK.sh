#!/usr/bin/env sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "usage: $0 TARGET BASELINE" >&2
  exit 2
fi

target=$1
baseline=$2
cp "$baseline" "$target"
echo "RESTORED target=$target from=$baseline"
