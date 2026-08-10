"""
Synthetic verification for research/cross_tf_break_divergence.py (2026-08-04).

find_divergence_events() operates on break-history lists (the same dict
shape structural_break_onset_detection.py's find_all_breaks() returns), so
these checks construct synthetic break histories directly rather than
synthetic price series -- the function under test is pure logic over
already-detected breaks, not a statistical estimator itself (that estimator
is already verified in debug/_verify_structural_break_onset_detection.py).

Usage:
    python debug/_verify_cross_tf_break_divergence.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research"))

from cross_tf_break_divergence import find_divergence_events


def _brk(date_str, break_type, pre_phi=0.9, post_phi=0.1):
    return {"break_date": pd.Timestamp(date_str), "break_type": break_type,
            "pre_phi": pre_phi, "post_phi": post_phi}


def check_1_divergence_detected():
    """Broken side decouples 2024-06-01; intact side has no break after
    that date -- must be flagged."""
    broken = [_brk("2024-06-01", "decoupling", pre_phi=0.1, post_phi=0.9)]
    intact = [_brk("2022-01-01", "onset")]  # a break, but well BEFORE the decoupling date
    events = find_divergence_events(broken, intact)
    ok = len(events) == 1 and events[0]["intact_side_ever_broke"] is True
    print(f"[{'PASS' if ok else 'FAIL'}] divergence detected when intact side's only break predates decoupling")
    return ok


def check_2_no_divergence_when_intact_also_breaks_after():
    """Intact side ALSO breaks shortly after the broken side's decoupling
    -- both sides moved, not a divergence -- must NOT be flagged."""
    broken = [_brk("2024-06-01", "decoupling", pre_phi=0.1, post_phi=0.9)]
    intact = [_brk("2024-07-01", "decoupling")]  # after the broken side's break date
    events = find_divergence_events(broken, intact)
    ok = len(events) == 0
    print(f"[{'PASS' if ok else 'FAIL'}] no divergence flagged when the 'intact' side also breaks afterward")
    return ok


def check_3_ignores_non_decoupling_breaks_on_broken_side():
    """An 'onset' (not 'decoupling') break on the broken side should never
    trigger a divergence event -- onset means the relationship got
    STRONGER, not that it broke."""
    broken = [_brk("2024-06-01", "onset")]
    intact = []
    events = find_divergence_events(broken, intact)
    ok = len(events) == 0
    print(f"[{'PASS' if ok else 'FAIL'}] onset breaks (not decoupling) never trigger a divergence event")
    return ok


def check_4_intact_side_never_broke_at_all():
    """Intact side has NO break history whatsoever -- strongest case,
    must still be correctly flagged with intact_side_ever_broke=False."""
    broken = [_brk("2024-06-01", "decoupling")]
    intact = []
    events = find_divergence_events(broken, intact)
    ok = len(events) == 1 and events[0]["intact_side_ever_broke"] is False
    print(f"[{'PASS' if ok else 'FAIL'}] intact side with zero break history flagged correctly")
    return ok


def check_5_multiple_decouplings_each_checked_independently():
    """Two decoupling breaks on the broken side, one followed by an intact-
    side break (no divergence) and one not (divergence) -- both must be
    resolved independently and correctly."""
    broken = [
        _brk("2020-01-01", "decoupling"),  # followed by an intact-side break -> no divergence
        _brk("2024-06-01", "decoupling"),  # not followed -> divergence
    ]
    intact = [_brk("2020-06-01", "decoupling")]
    events = find_divergence_events(broken, intact)
    ok = len(events) == 1 and events[0]["broken_side_break_date"] == pd.Timestamp("2024-06-01")
    print(f"[{'PASS' if ok else 'FAIL'}] multiple decoupling breaks resolved independently")
    return ok


if __name__ == "__main__":
    results = [
        check_1_divergence_detected(),
        check_2_no_divergence_when_intact_also_breaks_after(),
        check_3_ignores_non_decoupling_breaks_on_broken_side(),
        check_4_intact_side_never_broke_at_all(),
        check_5_multiple_decouplings_each_checked_independently(),
    ]
    print(f"\n{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
