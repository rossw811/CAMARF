#!/usr/bin/env python
"""
PreToolUse hook guarding confirmed_pairs_manifest.json (a live CAMARF production artifact).

Motivated directly by BUG-D63 (2026-07-13): test-placeholder symbols contaminated this exact
file once already (PAPER.md Section 9 Example 3), got a per-script backup/restore fix, and then
recurred via a different script that never got the same fix -- because the manifest path has no
test/production override (the real, root-cause fix, tracked as CAMARF's own task #44). This hook
is a backstop underneath that structural fix, not a replacement for it: it does not know whether
a given Write/Edit is "safe" (e.g. a legitimate manual correction, like the BUG-D63 cleanup
itself), it only flags that this specific file is high-risk and asks for a second look.

Reads the Claude Code PreToolUse hook JSON payload on stdin. Blocks (exit 2, message on stderr)
only for Write/Edit tool calls whose file_path targets confirmed_pairs_manifest.json. Allows
everything else (exit 0) without inspecting it further -- deliberately narrow, not a general
file-access policy.
"""
import json
import sys

TARGET = "confirmed_pairs_manifest.json"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        # Can't parse the hook payload -- fail open (allow) rather than block on a parsing bug.
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    file_path = str(tool_input.get("file_path", ""))

    if TARGET in file_path:
        sys.stderr.write(
            f"BLOCKED: direct {tool_name} to {file_path}.\n"
            "This is a live CAMARF production artifact (confirmed_pairs_manifest.json).\n"
            "BUG-D63 (2026-07-13) documents this exact file getting contaminated with test "
            "placeholder data once already. If this edit is a deliberate, real correction "
            "(e.g. removing genuine contamination, matching a real manifest change from "
            "analysis.py's own logic), re-run with explicit confirmation. If this is coming "
            "from a debug/_verify_*.py script exercising _save_tf_results or similar, use the "
            "manifest-path override (task #44) instead of touching the real file.\n"
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
