# Claims registry

Every claim this project makes in a paper or summary is registered here BEFORE it is cited. A claim is citable only
when its status is **REPLICATED** on the current data. Anyone may attack any entry — see
`.github/ISSUE_TEMPLATE/find_a_hole.md`; every report is verified, then fixed or disclosed, and the outcome is logged
under the entry and in the errata (docs/CODE_REVIEW_2026-09-26.md, docs/INCONSISTENCY_SWEEP_2026-09-27.md).

**Fields:** claim · hypothesis / falsification test (what result would refute it) · data & universe snapshot ·
exact parameters · how to reproduce (script, command, output path) · lineage seed or commit · status · history.
**Statuses:** REGISTERED (stated, not yet re-derived on current data) · REPLICATED (re-derived on current data by
the reproduce command, numbers below) · CORRECTED (re-derivation changed the claim; old and new kept) ·
WITHDRAWN (refuted or unsupportable) · PENDING-DATA (waits on a data fix or run in progress).
**Data note for outside reviewers:** CRSP / Compustat / TAQ licences forbid redistributing the data. The code,
queries, lineage manifests and derived statistics are public; replication needs your own WRDS access. Claims on
free data (yfinance, FRED, CFTC, Binance) are fully reproducible without it.

---

## Every cited claim: status table (2026-10-07, plan W4.3 / S20)

`docs/claims_table.csv` (built by `scripts/build_claims_table.py`, check `debug/_verify_build_claims_table.py`) lists
every claim row of the section-by-section scrutiny (`docs/PAPER_SCRUTINY_2026-09-27.md`, sections 2-3) with a status:

| Scrutiny verdict | Registry status | Meaning |
|---|---|---|
| WITHDRAW | WITHDRAWN | rests on a confirmed defect; not citable. Plan S34 may move a thesis-central claim back to fix-and-re-derive |
| REPLACE | CORRECTED | a committed corrected value exists (CR-1..CR-7); cite it with its stated scope |
| STANDS / QUALIFY / UNVERIFIED | REGISTERED | stated, not yet re-derived on current data -- nothing is REPLICATED until it is |

Counts (455 claim rows): PAPER.md 313 = 107 WITHDRAWN, 11 CORRECTED, 195 REGISTERED; PAPER_MAGNITUDE.md 142 = 52
WITHDRAWN, 0 CORRECTED, 90 REGISTERED. Note: the scrutiny document's own summary table says 284 rows; its tables hold
455 (the summary was not updated as rows were added) -- the table counts are the ones used here.
Since the scrutiny (2026-09-27) more defects were confirmed (2026-10-07 bug recheck, docs/bug_recheck/): e.g. S5 (the
Reality Check p-values), S6 (the Gold/Silver/Bronze tiers), the engine-level dollar P&L gap and A5/A7/A8 (the
coint-fraction override). REGISTERED rows that cite those results move to WITHDRAWN when the paper is redrafted.
The C-entries below are claims re-derived one by one on current data.

## C-001 — Full-sample cointegration can be stale: NTRS/STT
- **Claim:** Northern Trust / State Street pass a full-sample Engle-Granger test with p = 0.000046 over 10,098
  overlapping trading days (1985-12-03 to 2025-12-31), but fail the identical test on the last five years
  (p = 0.561, 1,256 days). A full-sample screen cannot tell a deployment whether the relationship is current.
- **Falsification:** the full-sample p ≥ 0.05, or the recent-window p < 0.05, on the same data and test.
- **Data:** CRSP daily `close_total_return` (WRDS cache, labels verified against the CIZ v2 security master after
  the D17 relabel: NTRS = permno 58246, STT = permno 72726). Controls: XOM/CVX, JPM/BAC, KO/PEP, SHW/UNP.
- **Parameters:** `analysis._eg_worker` (production; both legs aligned on common dates, longest gap-free run),
  constant trend, autolag AIC; recent window = last 5 calendar years.
- **Reproduce:** `python research/durability_vs_currency_wrds.py` → `output/research/durability_vs_currency_wrds.parquet`.
- **Status:** **CORRECTED → REPLICATED (2026-10-02).** p-values reproduce exactly. The previously stated sample
  ("13,373 daily obs since 1972", PAPER.md:130-137) was wrong: the script counted calendar rows, including the years
  before either stock has a price. Fixed in the script (commit in this registry's history); JPM/BAC was likewise
  overstated (11,741 days from 1979, not 13,373 from 1972). Caveat that travels with the claim: the recent window
  has ~8× fewer observations, so part of the gap may be power (P-075 / R8.12) — the universe-wide deep dive
  (docs/SCRUTINY_WHAT_HELD_UP_2026-09-28.md #1) is designed to separate the two.
- **Controls (same run):** XOM/CVX 0.082 / 0.482 (26,301 d); JPM/BAC 0.935 / 0.881 (11,741 d); KO/PEP 0.105 / 0.963
  (26,301 d); SHW/UNP 0.061 / 0.054 (14,238 d).

## C-002 — Calendar-padding artifact in rolling z-scores
- **Claim:** a z-score over a window padded with calendar (non-trading) rows is bounded by (n−1)/√n
  (= 15.81 at n = 252), producing spurious extreme z at the market open.
- **Falsification:** a counterexample exceeding the bound, or the bound not being attained by the construction.
- **Reproduce:** `python debug/_verify_calendar_padding_bound.py` (3/3, 2026-10-05).
- **Status:** analytic part **REPLICATED (2026-10-05)**: attained exactly by n-1 equal values whatever the move size
  (15.8115 at n = 252; pandas rolling z reproduces it) and never exceeded over 200,000 random windows. It is
  **Samuelson's inequality** (Samuelson 1968, "How deviant can you be?", JASA 63) for the sample standard deviation
  (ddof = 1) -- cite it as such, not as a new result; the contribution is the padding mechanism that attains it.
  The empirical "4 of 32 examples |z| > 10" (PAPER.md:803-812) is still REGISTERED: re-derive on current intraday data.

## C-003 — Purged ML predicts z-convergence, not profitability
- **Claim:** with purged + 1%-embargoed CV, AUC ≈ 0.61 (RF 0.6085 [0.600, 0.616]) for z-convergence after a
  |z| = 1.5 crossing (74,732 events / 1,301 pairs); AUC 0.47-0.54 for the strategy's own trades' dollar profit.
- **Falsification:** purged AUC ≤ 0.5 within its CI on the convergence label.
- **Reproduce:** `python research/ml_model_comparison_purged.py` → `output/research/ml_model_comparison_purged.parquet`
  (+ `_trials.json`).
- **Status:** PENDING-DATA — computed before the D13-D19 data fixes (labels, identities, FX, total return).
  Re-derive on the re-run pools.

## C-004 — The engine executes its rules; the rules are defective
- **Claim:** 0 rule violations in 101,700 trades; 54-68% of entries at or past the stop; 32-40% stopped after a
  favourable move; 19-38% re-entry within one bar of a stop.
- **Reproduce:** `python research/strategy_rule_invariants.py` → `output/research/strategy_rule_invariants.parquet`
  (reads `output/backtest/trades_layer1*storm_*gate_pairsoverride.parquet`).
- **Status:** PENDING-DATA (pre-fix pools); the invariant code (`research/strategy_rule_invariants.py`) is unchanged.

## C-005 — Entry clustering
- **Claim:** entries per business day are negative binomial (mean 1.90, variance 5.15), so iid nulls are misspecified.
- **Reproduce:** `python research/distribution_fits.py` → `output/research/distribution_fits.parquet` (default trades
  `output/backtest/trades_layer1_storm_momgate_pairsoverride.parquet`).
- **Status:** PENDING-DATA (pre-fix pools). Basis for the planned Hawkes null.

## C-006 — Pre-registered strategy search: no robust signal (first pass)
- **Claim:** no configuration met the pre-registered criterion (holdout > 0, DSR ≥ 0.95, PBO < 0.20 in all four
  splits) in either pool.
- **Reproduce:** `python research/strategy_search.py run` then `python research/strategy_search.py eval` →
  `output/research/strategy_search/` (pools `output/research/purity_pairs_pit_k{1,2}_clean.parquet`).
- **Status:** REGISTERED for the first pass only (docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md); second
  labelled pass (Amendment 2) pending the discovery re-run.
