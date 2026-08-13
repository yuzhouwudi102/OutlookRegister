#!/usr/bin/env python3
from pathlib import Path
import shutil
import sys
script_dir = Path(__file__).resolve().parent
target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if target is None or not (target / 'tests').is_dir():
    print('ROLLBACK_ERROR: provide the target project root', file=sys.stderr)
    raise SystemExit(2)
files = [
    ('authorize_recovery_mailbox.py', 'authorize_recovery_mailbox.py'),
    ('recovery_mailbox.py', 'recovery_mailbox.py'),
    ('test_recovery_mailbox.py', 'tests/test_recovery_mailbox.py'),
]
for source_name, destination_name in files:
    destination = target / destination_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(script_dir / 'baseline' / source_name, destination)
print(f'ROLLBACK_OK: restored 3 files in {target}')
