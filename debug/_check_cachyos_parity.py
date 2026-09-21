"""
debug/_check_cachyos_parity.py -- reports every tracked .py file whose
content differs between the local working tree and CachyOS's checkout, in
one pass. Replaces the manual `scp`+`diff` ritual this project has relied on
all session (found stale copies of build_comparison_arm_pairs.py, ml.py,
backtest.py on CachyOS three separate times, each caught only because a run
was about to use that exact file and someone happened to diff-verify first).

Compares by content hash over SSH (no file transfer needed for the compare
itself -- only diverging files get pulled for a human-readable diff), so
this scales to the whole tracked tree cheaply. Line-ending differences
(CRLF/LF) are normalized before hashing -- this project's own .gitattributes
already treats those as non-divergences (see the 2026-09 "Reconcile CachyOS
checkout with origin" commit), and treating them as real drift would just
reproduce the noise that commit was written to eliminate.

Usage:
    python debug/_check_cachyos_parity.py                       # all tracked .py files
    python debug/_check_cachyos_parity.py --path backtest.py     # one file
    python debug/_check_cachyos_parity.py --show-diff            # print full diffs, not just filenames
"""
import argparse
import hashlib
import os
import subprocess
import sys

_SSH_HOST = "rw@100.64.64.126"
_REMOTE_ROOT = "~/CAMARF"


def _local_tracked_py_files() -> list:
    result = subprocess.run(
        ["git", "ls-files", "*.py"], capture_output=True, text=True, check=True
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _local_hash(path: str) -> str:
    with open(path, "rb") as f:
        content = f.read().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def _remote_hashes(paths: list) -> dict:
    """One SSH call for ALL files, not one per file -- 256+ tracked .py files
    would mean 256+ round-trips otherwise, exactly the kind of thing this
    script exists to make cheap.

    Writes the script to a local temp file and scp's it over rather than
    inlining it as an SSH command-line string, then runs it with
    `bash /tmp/....sh` on the remote end. Two real, distinct problems with
    the inline-string approach, both hit directly while building this:
    (1) CachyOS's default remote shell is fish, not bash (hit repeatedly
    this session) -- bash's `for/if/else/fi` syntax is not fish-compatible
    on its own. (2) Even wrapped as `bash -c '...'`, a long (~500-file,
    ~20KB) command string breaks with `fish: Unexpected end of string,
    quotes are not balanced` -- confirmed directly this is NOT an OS
    ARG_MAX limit (20KB is far under it); something in how a long
    multiply-quoted string transits SSH-then-fish's own parsing breaks
    before bash ever sees it. Uploading a real script file sidesteps
    both: fish just execs the interpreter named on the command line
    (`bash /tmp/x.sh`), no shell-level parsing of the SCRIPT's own content
    happens on the remote side at all."""
    import tempfile

    inner_script = (
        "#!/bin/bash\n"
        "cd " + _REMOTE_ROOT + " && for f in " +
        " ".join(f'"{p}"' for p in paths) +
        '; do if [ -f "$f" ]; then printf "%s " "$f"; '
        'tr -d "\\r" < "$f" | sha256sum | cut -d" " -f1; else echo "$f MISSING"; fi; done\n'
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False, newline="\n") as f:
        f.write(inner_script)
        local_script_path = f.name

    remote_script_path = "/tmp/_camarf_parity_check.sh"
    try:
        subprocess.run(["scp", local_script_path, f"{_SSH_HOST}:{remote_script_path}"],
                        capture_output=True, text=True, timeout=30)
        result = subprocess.run(
            ["ssh", _SSH_HOST, "bash", remote_script_path],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        os.unlink(local_script_path)
        subprocess.run(["ssh", _SSH_HOST, "rm", "-f", remote_script_path],
                        capture_output=True, text=True, timeout=15)
    hashes = {}
    for line in result.stdout.splitlines():
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        path, val = parts
        hashes[path] = val
    return hashes


def check_parity(paths: list) -> dict:
    """Returns {'in_sync': [...], 'diverged': [...], 'missing_remote': [...], 'local_error': [...]}."""
    local_hashes = {}
    local_errors = []
    for p in paths:
        try:
            local_hashes[p] = _local_hash(p)
        except Exception as e:
            local_errors.append((p, str(e)))

    remote_hashes = _remote_hashes(list(local_hashes.keys()))

    in_sync, diverged, missing_remote = [], [], []
    for p, lh in local_hashes.items():
        rh = remote_hashes.get(p)
        if rh is None or rh == "MISSING":
            missing_remote.append(p)
        elif rh == lh:
            in_sync.append(p)
        else:
            diverged.append(p)

    return {"in_sync": in_sync, "diverged": diverged,
            "missing_remote": missing_remote, "local_error": local_errors}


def main():
    p = argparse.ArgumentParser(description="Check local vs CachyOS file parity")
    p.add_argument("--path", default=None, help="Check only this one file (relative path)")
    p.add_argument("--show-diff", action="store_true", help="Print full diffs for diverged files")
    args = p.parse_args()

    paths = [args.path] if args.path else _local_tracked_py_files()
    print(f"Checking {len(paths)} file(s) against {_SSH_HOST}:{_REMOTE_ROOT} ...\n")

    result = check_parity(paths)

    print(f"IN SYNC: {len(result['in_sync'])}")
    if result["diverged"]:
        print(f"\nDIVERGED ({len(result['diverged'])}):")
        for f in result["diverged"]:
            print(f"  *** {f}")
        if args.show_diff:
            for f in result["diverged"]:
                print(f"\n--- diff for {f} ---")
                diff = subprocess.run(
                    ["bash", "-c", f'diff <(ssh {_SSH_HOST} "cat {_REMOTE_ROOT}/{f}" | tr -d "\\r") <(cat "{f}" | tr -d "\\r")'],
                    capture_output=True, text=True,
                )
                print(diff.stdout[:3000])
    if result["missing_remote"]:
        print(f"\nMISSING ON CACHYOS ({len(result['missing_remote'])}):")
        for f in result["missing_remote"]:
            print(f"  {f}")
    if result["local_error"]:
        print(f"\nLOCAL READ ERRORS ({len(result['local_error'])}):")
        for f, e in result["local_error"]:
            print(f"  {f}: {e}")

    n_issues = len(result["diverged"]) + len(result["missing_remote"])
    print(f"\n{'='*70}")
    print(f"{n_issues} file(s) need attention" if n_issues else "All files in sync.")
    sys.exit(1 if n_issues else 0)


if __name__ == "__main__":
    main()
