"""
Guard test for the 2026-07-20 Grand Sweep finding: wfa.py hardcoded its own
copy of ENTRY_ZSCORE/EXIT_ZSCORE/STOP_ZSCORE/N_SHARES/COMMISSION/SLIPPAGE_BPS/
MAX_HOLD_MULT with a comment claiming they matched Config.BACKTEST -- three
of them (EXIT_ZSCORE, SLIPPAGE_BPS, MAX_HOLD_MULT) had silently drifted, so
the WFA Sharpe figures already cited in CLAUDE.md/PAPER.md were computed
under a materially different strategy than backtest.py's own headline run,
despite being presented as a robustness check of the SAME strategy.

Fixed by making wfa.py import these directly from Config.BACKTEST instead of
duplicating them, which makes this specific drift structurally impossible
going forward -- this test is a regression guard in case a future edit
reverts wfa.py back to hardcoded literals, not a test of live behavior.

Also serves as the template for the general check requested (2026-07-20):
a lightweight guard against config-value duplication drifting silently,
distinct from the existing debug/_verify_*.py tests (which check
correctness-in-isolation, not cross-file agreement).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wfa
from config import Config

# (wfa.py attribute name, Config.BACKTEST attribute name)
_CHECKS = [
    ("ENTRY_ZSCORE", "ENTRY_ZSCORE"),
    ("EXIT_ZSCORE", "EXIT_ZSCORE"),
    ("STOP_ZSCORE", "STOP_ZSCORE"),
    ("N_SHARES", "N_SHARES_PER_TRADE"),
    ("COMMISSION", "COMMISSION_PER_SHARE"),
    ("SLIPPAGE_BPS", "SLIPPAGE_BPS"),
    ("MAX_HOLD_MULT", "MAX_HOLD_MULTIPLIER"),
]


def main() -> None:
    failures = []
    for wfa_attr, config_attr in _CHECKS:
        wfa_val = getattr(wfa, wfa_attr)
        config_val = getattr(Config.BACKTEST, config_attr)
        if wfa_val != config_val:
            failures.append(
                f"wfa.{wfa_attr} = {wfa_val} != Config.BACKTEST.{config_attr} = {config_val}"
            )

    # MIN_HALF_LIFE is deliberately NOT checked against Config.BACKTEST.MIN_HALF_LIFE_BARS --
    # confirmed these are distinct parameters (a numerical clip floor vs. an entry-filter
    # threshold), not a naming collision that should be unified. Documented here so a future
    # session doesn't "fix" this into a false match.
    if wfa.MIN_HALF_LIFE == Config.BACKTEST.MIN_HALF_LIFE_BARS:
        pass  # coincidentally equal is fine; they're just not required to match

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("All wfa.py / Config.BACKTEST consistency checks passed.")
        for wfa_attr, config_attr in _CHECKS:
            print(f"  wfa.{wfa_attr} == Config.BACKTEST.{config_attr} == {getattr(wfa, wfa_attr)}")


if __name__ == "__main__":
    main()
