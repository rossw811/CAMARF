"""
Regression test for code-review B7 (confirmed 2026-09-26, fixed 2026-10-03, bug recheck T14.4): --decay-rate-sizing
(and --decay-rate-modifier) with --holdout read weights from a precomputed detail file whose source trades can span
the OOS window -- the same lookahead risk the code already warned about for --regime-age-sizing, but silently. Fix:
warned too, and every such holdout run's output label carries "_lookaheadrisk" (also regime-age).
Check (source -- main() runs the whole pipeline): the label tag is applied for all three sizers under --holdout, and
the decay-rate warning exists.
Run: python debug/_verify_backtest_lookahead_label.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "backtest.py"), encoding="utf-8").read()
checks = {
    "tag_applied": 'label += "_lookaheadrisk"' in src,
    "all_three_sizers": all(n in src for n in ('("--regime-age-sizing", args.regime_age_sizing)',
                                               '("--decay-rate-sizing", args.decay_rate_sizing)',
                                               '("--decay-rate-modifier", args.decay_rate_modifier)')),
    "decay_rate_warning": bool(re.search(r"if args\.holdout and \(args\.decay_rate_sizing or args\.decay_rate_modifier\):"
                                         r"\s*log\.warning", src)),
}
for k, v in checks.items():
    print(f"[{'PASS' if v else 'FAIL'}] {k}")
print(); print(f"{sum(checks.values())}/{len(checks)} checks passed")
sys.exit(0 if all(checks.values()) else 1)
