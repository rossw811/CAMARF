# Inconsistency sweep — 2026-09-27 (Ross: "find all these")

Scope: every production module and research script. Target: things that disagree with each other — the same concept
computed two ways, labels/units/calendars that don't line up across sources, silent fallbacks, constants that shadow
config. Every entry is verified against code or real data before it is listed; "checked, consistent" entries are
kept too, so the sweep's coverage is visible. Fixes follow the project rules (failing test first, root cause, backups).

## Categories and status

| # | Category | Status |
|---|---|---|
| 1 | Labels / identity across sources and asset classes | D16, D17 fixed; loader disjoint-source rule |
| 2 | Units and scale | macro thresholds consistent; pence vs pounds pending FX/ADR check |
| 3 | Calendars and time | D13, M8/M9, U2/U3 fixed; weekend-exit booking (S1) |
| 4 | Duplicated logic that has drifted | Sharpe: consistent after P1; `_eg_pvalue`, `build_spread_z`, `load_log_close`, `_load_spread` pending |
| 5 | Constants shadowing config | pending |
| 6 | Silent fallbacks | M12 retry loop swallowed errors (fixed for the new guard); systematic grep pending |
| 7 | Price column semantics (close / close_total_return / close_usd) | D18 open |

## Findings

**M12 FIXED — CFTC COT E-mini Nasdaq history truncated to 2022.** `macro.COTFeed` matched contracts by name prefix.
CFTC renamed the contract ("E-MINI NASDAQ 100 STOCK INDEX" 1999; "NASDAQ-100 STOCK INDEX (MINI)" 1999-2022 at IMM
then CME; "NASDAQ MINI" 2022-), and the prefix "NASDAQ MINI" matched only the last: NQ positioning began 2022-02-08
(242 weeks) instead of 1999-06-29 (1,422 weeks). ES was complete (its three names share the prefix; 0 duplicate
dates). Fix: exact chronological name lists; one-row-per-report-date guard that now fails loudly (the fetch's retry
loop swallowed every exception at debug level). Test `_verify_cot_contract_history.py` 4/4 (live). Macro regime
suite 25/25. My first test draft required ≤3-week gaps everywhere — ES has genuine 14-25 day gaps in 1998 (first
year of E-mini reporting); the check was narrowed to the rename boundaries.

**S1 OPEN (minor) — weekend exits booked on the preceding Friday.** `portfolio_math.daily_pnl_from_exits` conserves
P&L but books a Saturday/Sunday exit (24/7 assets) on the Friday BEFORE it happened. Harmless for Sharpe; slightly
early for equity-curve / drawdown timing and any join with other daily series. The following Monday is the honest date.

**Checked, consistent — Sharpe implementations.** 18 definitions outside `portfolio_math`. Every one that feeds a
result builds its daily series through `portfolio_math.daily_pnl_from_exits`/`daily_pnl_from_trades` (business days,
zero-filled over the evaluation window) and then applies mean/std·√252; the remaining standalone formulas
(`stats._portfolio_sharpe`, `regime_conditional_entry_gate._sharpe`, `decay_proxy._window_sharpe` (unannualized,
used as a ranking score), portfolio-optimiser objectives) take an already-built series. ddof differs (0 vs 1) —
negligible.

**Checked, consistent — macro regime thresholds vs units.** T10Y2Y (pp, −1.08..2.91) vs 0.0/1.5; HY OAS and BAA10Y
(percent) vs percent thresholds; VIX level vs 15/25/35; VXV/VIX ratio vs 0.95/1.00/1.10; COT net spec (fraction of
OI, −0.51..0.61) vs −0.10/0.15; Sahm (pp, max 9.43 in 2020) vs 0.5. Known, documented limit: HY OAS only 752 days
(keyless FRED cap), so `credit_regime` is never "wide".
