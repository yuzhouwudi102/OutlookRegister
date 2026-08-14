from pathlib import Path
import difflib
import hashlib
import json
import shutil
import stat
import subprocess
import tempfile
import zipfile

ROOT = Path.cwd().resolve()
ART = ROOT / "artifacts" / "recovery_auto_authorize_20260814"
ART.mkdir(parents=True, exist_ok=True)
FILES = [
    ("recovery_mailbox.py", "baseline_recovery_mailbox.py"),
    ("controllers/base_controller.py", "baseline_base_controller.py"),
    ("tests/test_recovery_mailbox.py", "baseline_test_recovery_mailbox.py"),
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def run(cmd, cwd):
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.returncode, result.stdout


diff_parts = []
for rel, baseline_name in FILES:
    before = (ART / baseline_name).read_text(encoding="utf-8").splitlines(keepends=True)
    after = (ROOT / rel).read_text(encoding="utf-8").splitlines(keepends=True)
    diff_parts.extend(
        difflib.unified_diff(before, after, fromfile=f"a/{rel}", tofile=f"b/{rel}", n=3)
    )
diff_path = ART / "DIFF_FILE.patch"
diff_path.write_text("".join(diff_parts), encoding="utf-8")

rollback_path = ART / "ROLLBACK.sh"
rollback_path.write_text(
    """#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"
TARGET_ROOT=\"${1:-$(pwd)}\"
cp \"$SCRIPT_DIR/baseline_recovery_mailbox.py\" \"$TARGET_ROOT/recovery_mailbox.py\"
mkdir -p \"$TARGET_ROOT/controllers\" \"$TARGET_ROOT/tests\"
cp \"$SCRIPT_DIR/baseline_base_controller.py\" \"$TARGET_ROOT/controllers/base_controller.py\"
cp \"$SCRIPT_DIR/baseline_test_recovery_mailbox.py\" \"$TARGET_ROOT/tests/test_recovery_mailbox.py\"
echo \"ROLLBACK_OK: restored recovery_mailbox.py, controllers/base_controller.py, tests/test_recovery_mailbox.py\"
""",
    encoding="utf-8",
    newline="\n",
)
rollback_path.chmod(rollback_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

zip_path = ART / "MODIFIED_FILE.zip"


def ignore(_directory, names):
    return {name for name in names if name in {".git", ".venv", "artifacts", "__pycache__", ".pytest_cache"}}


work = Path(tempfile.mkdtemp(prefix="recovery_auto_authorize_verify_"))
baseline_tree = work / "baseline"
rollback_tree = work / "rollback"
shutil.copytree(ROOT, baseline_tree, ignore=ignore)
shutil.copytree(ROOT, rollback_tree, ignore=ignore)
for rel, baseline_name in FILES:
    destination = baseline_tree / rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ART / baseline_name, destination)

python = str(ROOT / ".venv" / "Scripts" / "python.exe")
baseline_cmd = [python, "-m", "unittest", "discover", "-s", "tests", "-v"]
modified_cmd = [python, "-m", "unittest", "discover", "-s", "tests", "-v"]
compile_cmd = [python, "-m", "py_compile", "recovery_mailbox.py", "controllers/base_controller.py", "tests/test_recovery_mailbox.py"]
baseline_rc, baseline_out = run(baseline_cmd, baseline_tree)
compile_rc, compile_out = run(compile_cmd, ROOT)
modified_rc, modified_out = run(modified_cmd, ROOT)

bash_candidates = [r"C:\\Program Files\\Git\\bin\\bash.exe", r"C:\\Program Files\\Git\\usr\\bin\\bash.exe", r"C:\\Program Files (x86)\\Git\\bin\\bash.exe"]
bash = next((Path(item) for item in bash_candidates if item and Path(item).exists()), None)
if bash:
    rollback_cmd = [str(bash), str(rollback_path), str(rollback_tree)]
else:
    rollback_cmd = [python, "-c", "import shutil,sys; from pathlib import Path; a=Path(sys.argv[1]); r=Path(sys.argv[2]); shutil.copy2(a/'baseline_recovery_mailbox.py',r/'recovery_mailbox.py'); shutil.copy2(a/'baseline_base_controller.py',r/'controllers/base_controller.py'); shutil.copy2(a/'baseline_test_recovery_mailbox.py',r/'tests/test_recovery_mailbox.py'); print('ROLLBACK_OK')", str(ART), str(rollback_tree)]
rollback_rc, rollback_out = run(rollback_cmd, ROOT)

baseline_hashes = {rel: sha(ART / baseline_name) for rel, baseline_name in FILES}
modified_hashes = {rel: sha(ROOT / rel) for rel, _ in FILES}
rollback_hashes = {rel: sha(rollback_tree / rel) for rel, _ in FILES}
restored = rollback_hashes == baseline_hashes

verification_path = ART / "VERIFICATION.txt"
verification = f"""Changed branch/field:
- recovery_mailbox.py / RecoveryMailboxClient.authorize_with_browser: page-transition action waits changed from 600 ms to 1000 ms; 250 ms idle polling unchanged.
- controllers/base_controller.py / choose_recovery_mailbox + authorize_recovery_mailbox: an unapproved recovery mailbox is authorized through the existing automated OAuth flow with the controller browser/fingerprint profile; JSON and outlook_token.txt persistence are both retained.

Artifacts (absolute paths):
- MODIFIED_FILE: {zip_path}
- DIFF_FILE: {diff_path}
- VERIFICATION.txt: {verification_path}
- executable ROLLBACK.sh: {rollback_path}

BASELINE
Command: {subprocess.list2cmdline(baseline_cmd)}
Input: isolated tree with this turn's baseline snapshots
Literal output/result:
{baseline_out}
Exit status: {baseline_rc}

MODIFIED-COMPILE
Command: {subprocess.list2cmdline(compile_cmd)}
Input: modified workspace files
Literal output/result:
{compile_out or '<no output>'}
Exit status: {compile_rc}

MODIFIED
Command: {subprocess.list2cmdline(modified_cmd)}
Input: modified workspace with new regression tests
Literal output/result:
{modified_out}
Exit status: {modified_rc}

ROLLBACK
Command: {subprocess.list2cmdline(rollback_cmd)}
Input: separate modified copy at {rollback_tree}
Literal output/result:
{rollback_out}
Exit status: {rollback_rc}
Restored behavior/status: {'PASS' if restored else 'FAIL'}; rollback-copy SHA256 values match the pre-change baseline.

SHA256 baseline:
{json.dumps(baseline_hashes, ensure_ascii=False, indent=2)}
SHA256 modified workspace (left changed):
{json.dumps(modified_hashes, ensure_ascii=False, indent=2)}
SHA256 rollback copy:
{json.dumps(rollback_hashes, ensure_ascii=False, indent=2)}
"""
verification_path.write_text(verification, encoding="utf-8")

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
    for rel, _ in FILES:
        archive.write(ROOT / rel, rel)
    for path in (diff_path, verification_path, rollback_path):
        archive.write(path, path.name)
    for _, baseline_name in FILES:
        archive.write(ART / baseline_name, baseline_name)

assert baseline_rc == 0, baseline_out
assert compile_rc == 0, compile_out
assert modified_rc == 0, modified_out
assert rollback_rc == 0, rollback_out
assert restored
assert diff_path.stat().st_size > 0
with zipfile.ZipFile(zip_path) as archive:
    assert archive.testzip() is None
    assert "VERIFICATION.txt" in archive.namelist()

print(json.dumps({
    "MODIFIED_FILE": str(zip_path),
    "DIFF_FILE": str(diff_path),
    "VERIFICATION": str(verification_path),
    "ROLLBACK": str(rollback_path),
    "baseline_exit": baseline_rc,
    "compile_exit": compile_rc,
    "modified_exit": modified_rc,
    "rollback_exit": rollback_rc,
    "rollback_restored": restored,
}, ensure_ascii=False, indent=2))
