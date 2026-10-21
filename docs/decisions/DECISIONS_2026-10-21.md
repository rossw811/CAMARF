# Decisions, 2026-10-21

Ross: "i sign off on those" — all five proposals as presented in chat on 2026-10-21.

| # | Decision | Approved content |
|---|---|---|
| 1 | Amendment 5 + full chain re-run (BUG-D119, BUG-D120) | A trade spanning a price hole of more than 5 trading days in either leg is unrealizable: excluded from P&L and counted. The BUG-D118 > 5x split rule applies between consecutive valid prices (holes in between do not hide a jump). The pool is the point-in-time-eligible set itself, not a subset of a whole-history BH rejection set |
| 2 | Sealed holdout at the loader for every source | Daily-and-coarser data stops at 2025-12-31 (`SEALED_FROM` 2026-01-01). Intraday seal moves to forward-recorded bars from 2026-10-21 (all yfinance intraday is 2024+). The 2026 Compustat Global and intraday data already seen is disclosed |
| 3 | Johansen trios | Restricted-constant Johansen as a comparison arm first; the earlier det_order 0 approval is not applied (11.7% size at nominal 5%) |
| 4 | `report.py` LaTeX paper | Retire the generated narrative; keep only the figures |
| 5 | N14 null design | Stationary block bootstrap of each candidate pair's joint returns, re-integrated to prices: keeps the pair's correlation, removes cointegration |
