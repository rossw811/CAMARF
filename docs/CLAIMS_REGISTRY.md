# Claims registry

Every claim this project makes in a paper or summary is registered here BEFORE it is cited. A claim is citable only
when its status is **REPLICATED** on the current data. Anyone may attack any entry — see
`.github/ISSUE_TEMPLATE/find_a_hole.md`; every report is verified, then fixed or disclosed, and the outcome is logged
under the entry and in the errata (docs/archive/audits/CODE_REVIEW_2026-09-26.md, docs/archive/audits/INCONSISTENCY_SWEEP_2026-09-27.md).

**Fields:** claim · hypothesis / falsification test (what result would refute it) · data & universe snapshot ·
exact parameters · how to reproduce (script, command, output path) · lineage seed or commit · status · history ·
**market-structure reading** (what about market structure would make the claim fail; Ross 2026-10-20).
**Statuses:** REGISTERED (stated, not yet re-derived on current data) · REPLICATED (re-derived on current data by
the reproduce command, numbers below) · CORRECTED (re-derivation changed the claim; old and new kept) ·
WITHDRAWN (refuted or unsupportable) · PENDING-DATA (waits on a data fix or run in progress).
**Data note for outside reviewers:** CRSP / Compustat / TAQ licences forbid redistributing the data. The code,
queries, lineage manifests and derived statistics are public; replication needs your own WRDS access. Claims on
free data (yfinance, FRED, CFTC, Binance) are fully reproducible without it.

---

## Every cited claim: status table (2026-10-07, plan W4.3 / S20)

`docs/claims_table.csv` (built by `scripts/build_claims_table.py`, check `debug/_verify_build_claims_table.py`) lists
every claim row of the section-by-section scrutiny (`docs/archive/audits/PAPER_SCRUTINY_2026-09-27.md`, sections 2-3) with a status:

| Scrutiny verdict | Registry status | Meaning |
|---|---|---|
| WITHDRAW | WITHDRAWN | rests on a confirmed defect; not citable. Plan S34 may move a thesis-central claim back to fix-and-re-derive |
| REPLACE | CORRECTED | a committed corrected value exists (CR-1..CR-7); cite it with its stated scope |
| STANDS / QUALIFY / UNVERIFIED | REGISTERED | stated, not yet re-derived on current data -- nothing is REPLICATED until it is |

Counts (455 claim rows; 2026-10-07 build): PAPER.md 313 = 107 WITHDRAWN, 11 CORRECTED, 195 REGISTERED;
PAPER_MAGNITUDE.md 142 = 52 WITHDRAWN, 0 CORRECTED, 90 REGISTERED. **Current counts:** run `python scripts/build_claims_table.py` (prints them); not hand-copied here, so they
cannot go stale.
455 (the summary was not updated as rows were added) -- the table counts are the ones used here.
Since the scrutiny (2026-09-27) more defects were confirmed (2026-10-07 bug recheck, docs/bug_recheck/): e.g. S5 (the
Reality Check p-values), S6 (the Gold/Silver/Bronze tiers), the engine-level dollar P&L gap and A5/A7/A8 (the
coint-fraction override). REGISTERED rows that cite those results move to WITHDRAWN when the paper is redrafted.
The C-entries below are claims re-derived one by one on current data.

## C-001 — Full-sample cointegration can be stale: NTRS/STT
- **Claim:** Northern Trust / State Street pass a full-sample Engle-Granger test with p = 0.000046 over 10,098
  overlapping trading days (1985-12-03 to 2025-12-31), but fail the identical test on the last five years
  (p = 0.561, 1,256 days). A full-sample screen cannot tell a deployment whether the relationship is current.
- **2026-10-19 (claims evaluation, D13):** current rules give last-5y p = 0.599 (10,097 d); at the full-sample effect the
  5-year test has power 0.18 (Gaussian) / 0.34 (real blocks) and P(p >= 0.599) = 0.07 / 0.20 -- weak evidence either
  way. The claim stands as 'cannot vouch for the present', not 'has broken'. Controls: XOM/CVX shows the pattern
  (0.0415 / 0.3769); JPM/BAC (0.8955), KO/PEP (0.1124), SHW/UNP (0.0606) detect no full-sample effect, so they are
  not controls for losing one.
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
  (docs/archive/audits/SCRUTINY_WHAT_HELD_UP_2026-09-28.md #1) is designed to separate the two.
- **Controls (same run):** XOM/CVX 0.082 / 0.482 (26,301 d); JPM/BAC 0.935 / 0.881 (11,741 d); KO/PEP 0.105 / 0.963
  (26,301 d); SHW/UNP 0.061 / 0.054 (14,238 d).

- **Re-derivation 2026-10-10 (S34, central): CORRECTED.** `python research/rederive_durability_claims.py` →
  `output/research/rederive_durability_claims.parquet`, two arms on the same CRSP files. *as_published* (A-on-B only,
  `max_lag=None` → statsmodels picks the lag, ~48 at n≈26k, by AIC; no-trade days kept) reproduces every number above
  exactly. *current_rules* = the test discovery actually runs: S35 no-trade mask, max p over both directions,
  `max_lag = Config.ANALYSIS.EG_MAX_LAG = 10`. Full p / last-5y p:
  NTRS/STT 0.000039 / 0.599 (10,097 d) -- **claim holds**; the recent p is 0.599 (the B-on-A direction), not 0.561.
  XOM/CVX **0.041** / 0.377 (26,291 d) -- **now shows the NTRS/STT pattern**, so "none of the negative controls show
  the pattern" (PAPER.md §4.2) is false under the production test. JPM/BAC 0.895 / 0.881. KO/PEP 0.112 / 0.963
  (24,671 d). SHW/UNP 0.061 / 0.054 (directions: UNP-on-SHW 0.044 / 0.003 -- the published one-direction reading
  depended on leg order). Also corrected: §4.2 says the demo used production `_eg_worker` "unmodified: same test";
  the parameters were not production's (lag, direction). Caveat (independent review): "since 1985-12-03" is when the
  WRDS cache has prices for both legs; NTRS and STT have positive volume from 1982-11-01 with no price on 772 / 413
  days -- not checked against WRDS whether CRSP has returns for those days. "50+ years" in the NTRS/STT paragraph
  (PAPER.md §4.2) should read ~40. Checked by an independent adversarial review (2026-10-10), which found the lag
  error in the first version of the re-derivation script; fixed and re-run.
- **Market-structure reading:** fails if the recent-window loss of cointegration is a structural change in the two custody banks' businesses (an economic break the market priced), not test staleness; and at power 0.18-0.34 the last-5-years p = 0.599 cannot separate the two.

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
- **Market-structure reading:** fails if none for the bound itself (arithmetic); its relevance needs calendar mismatch in production paths (legs on exchanges with different holidays), which the common-calendar alignment may already remove.

## C-003 — Purged ML predicts z-convergence, not profitability
- **Claim:** with purged + 1%-embargoed CV, AUC ≈ 0.61 (RF 0.6085 [0.600, 0.616]) for z-convergence after a
  |z| = 1.5 crossing (74,732 events / 1,301 pairs); AUC 0.47-0.54 for the strategy's own trades' dollar profit.
- **Falsification:** purged AUC ≤ 0.5 within its CI on the convergence label.
- **Reproduce:** `python research/ml_model_comparison_purged.py` → `output/research/ml_model_comparison_purged.parquet`
  (+ `_trials.json`).
- **Status:** PENDING-DATA — computed before the D13-D19 data fixes (labels, identities, FX, total return).
- **Re-derived 2026-10-20 (N10; REGISTERED pending review, CORRECTED value).** `research/ml_model_comparison_purged.py`
  on the fixed chain: ml.build(pit_safe=True) on the k2 PIT pool, 21,695 events (109 dropped by the sealed holdout),
  positive (converged) rate 0.616; purged + 1% embargo split (R2.3 now also in ml.py): train 11,768 / val 2,654 / test
  3,766, test boundary 2016-06-03 (test ends 2025-12-31). Test AUC [bootstrap 95% CI]: random forest 0.587 [0.572,
  0.603], XGBoost 0.576 [0.562, 0.591], logistic L2 0.575 [0.559, 0.590], kNN 0.584, LightGBM 0.571, SVM 0.567, MLP 0.555.
  The claim's shape holds (above-chance prediction of z-convergence; profitability not addressed); the value is lower
  than the pre-fix 0.61. Log logs/ml_n10_20261020.log (CachyOS).
  Re-derive on the re-run pools.
- **Market-structure reading:** fails if the AUC comes from mechanical convergence -- stale or nonsynchronous prices in thin legs, bid-ask bounce at intraday bars -- rather than information; that would make 'predicts convergence' an artifact of quoting, not of the pairs.

## C-004 — The engine executes its rules; the rules are defective
- **Claim:** 0 rule violations in 101,700 trades; 54-68% of entries at or past the stop; 32-40% stopped after a
  favourable move; 19-38% re-entry within one bar of a stop.
- **Reproduce:** `python research/strategy_rule_invariants.py` → `output/research/strategy_rule_invariants.parquet`
  (reads `output/backtest/trades_layer1*storm_*gate_pairsoverride.parquet`).
- **Status:** PENDING-DATA (pre-fix pools); the invariant code (`research/strategy_rule_invariants.py`) is unchanged.
- **Market-structure reading:** fails if entries at or past the stop are caused by price discreteness (overnight gaps, opening jumps, limit moves) that any stop rule faces, so the defect is the market's, not the rules'.

## C-005 — Entry clustering
- **Claim:** entries per business day are negative binomial (mean 1.90, variance 5.15), so iid nulls are misspecified.
- **Reproduce:** `python research/distribution_fits.py` → `output/research/distribution_fits.parquet` (default trades
  `output/backtest/trades_layer1_storm_momgate_pairsoverride.parquet`).
- **Status:** PENDING-DATA (pre-fix pools). Basis for the planned Hawkes null.
- **Market-structure reading:** fails if the clustering is a common market-wide volatility shock hitting every spread at once; if conditioning on market volatility removes it, a volatility-conditioned iid null suffices and the Hawkes null is unneeded.

## C-006 — Pre-registered strategy search: no robust signal (first pass)
- **Claim:** no configuration met the pre-registered criterion (holdout > 0, DSR ≥ 0.95, PBO < 0.20 in all four
  splits) in either pool.
- **Reproduce:** `python research/strategy_search.py run` then `python research/strategy_search.py eval` →
  `output/research/strategy_search/` (pools `output/research/purity_pairs_pit_k{1,2}_clean.parquet`).
- **Status:** REGISTERED for the first pass only (docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md). The second
  pass (Amendment 3) ran 2026-10-14: 0 of 8 cells passed (holdout Sharpes k=1 -0.48/-0.14/+0.50/-0.15, k=2
  +0.08/+0.91/+0.33/+0.71). Independent review: verdict held, "k = 2 is a lead" overstated (98 of 216 configs
  positive in all splits; nested holdouts; SPY/VOO in the k = 2 pool; clustered pool). That pass is SUPERSEDED by
  BUG-D118 (Compustat Global price breaks; 29% of the k = 2 pool affected) and is being re-run under Amendment 4
  (committed 27b7d4a7 before any result). Disclosed evaluation deviations (kept for comparability): the DSR uses the
  selected configuration's unconstrained development Sharpe, and Var[SR] is over 216 trials while N = 432.
- **Amendment 4 result (2026-10-20, sealed; REGISTERED pending independent review).** Re-run chain on the fixed code
  (PIT pools, PIT spread fix 89ececc4, strict engine; HEAD bae863a9 for the run, eval re-run on 6b7f7d0a). Pools: k1 416
  clean pairs (411 1D + 5 1h), k2 48 (1D); 216 configurations x 2 pools x 4 splits = 1,728 trials (N = 432 per split).
  The first eval used trades to 2026-08-11 (Compustat Global runs past CRSP's end; the 2026-01-01 seal was never
  enforced -- ERRATA); it is kept as superseded (`output/research/strategy_search/_SUPERSEDED_unsealed_20261020/`) and
  the eval was re-run with every trade exiting on/after 2026-01-01 dropped (`strategy_search.seal_trades`). **Result: no
  selection passes in either pool.** Dev-selected configuration per split (holdout capital-sim Sharpe / DSR / PBO):
  k1 0.5 -0.353 / 0.000 / 0.60; 0.6 +0.428 / 0.011 / 0.52; 0.7 -0.015 / 0.034 / 0.28; 0.8 -0.135 / 0.000 / 0.17;
  k2 0.5 +0.284 / 0.000 / 0.31; 0.6 +0.314 / 0.000 / 0.92; 0.7 +0.436 / 0.069 / 0.84; 0.8 +0.438 / 0.215 / 0.64.
  Reported regardless (not significant): 80.3% of all 1,728 trials have a positive holdout Sharpe (median 0.303, best
  1.036 = k1 0.7 e2.0_legacy45_rearm0_x0.5_mh1_momentum, post hoc); k2 89-97% positive in every split, k1 58-74%. **Independent review (2026-10-21) --
  verdict QUALIFY, the "pool-level effect" reading REFUTED:** k2's near-universal positivity is one Compustat Global pair
  (GVKEY010137_01W / GVKEY015736_01W), mostly one trade carried through an 810-day hole in leg B's prices (no valid
  close_total_return 2023-09-29 -> 2025-12-17; total return 175.88 -> 11.56) and booked at exit_reason `data_gap` for
  +$21,958 per $10k (e2.5_legacy45_rearm1_x0.5_mh3_none; re-checked by hand). Without the top 5 pairs the share of k2
  configurations with a positive summed holdout falls from 84.3% to 1.4% (split 0.8) and from 96.3% to 10.2% (split 0.5);
  k1 82.4% -> 65.7%. Holdout P&L is NEGATIVELY correlated with the market (k2 -0.09 to -0.14; k1 split 0.8 -0.38); costs
  are applied ($0.005/share + 5 bps per side). Straddling trades dropped by the seal do not change the reading
  (marked at 2025-12-31 and added back: k2 positive shares 0.968/0.977/0.935/0.880). Two defects behind it (BUG-D119,
  BUG-D120, ERRATA): trades booked across multi-year price holes, and pool MEMBERSHIP set by a whole-history BH cutoff
  (only the eligibility DATE is point-in-time). The verdict "no robust signal" stands; both defects inflate, not hide. Output `output/research/strategy_search/{summary,all_trials}.parquet` (CachyOS, 2026-10-20 21:54).
- **Amendment 5 result (2026-10-23, CachyOS chain `debug/_tmp_chain_a5_20261021.sh`, HEAD dee7fcb5+; REGISTERED
  pending independent review, running 2026-10-24).** Fixes: BUG-D119 unrealizable trades excluded and counted (holes
  in each market's trading days), BUG-D118 rule on consecutive valid prices (15,082 labels re-segmented), BUG-D120 pool
  = the point-in-time-eligible set, sealed holdout at the data layer. Pools: k1 759 clean pairs (753 1D + 6 1h; arms
  547 US-US gated / 153 international / 53 mixed / 6 intraday), k2 64 (1D; 43 / 15 / 6). 432 fresh backtests.
  **Result: no robust signal in either pool; 0 of 8 cells pass.** Holdout capital-sim Sharpe / DSR / PBO of the
  dev-selected configuration: k1 0.5 -0.326 / 0.000 / 0.46; 0.6 -0.228 / 0.000 / 0.65; 0.7 +0.047 / 0.006 / 0.61;
  0.8 -0.668 / 0.000 / 0.04; k2 0.5 +0.076 / 0.004 / 0.37; 0.6 -0.110 / 0.031 / 0.84; 0.7 +0.300 / 0.125 / 0.83;
  0.8 +0.546 / 0.327 / 0.78. Positive-holdout share of trials: k1 53.0% (median +0.04), k2 63.5% (median +0.09), down
  from ~80% in Amendment 4. Trades dropped by the P&L basis: 0 in both pools (all 432 dropped logs empty). Amendment 4
  outputs kept in `output/research/_superseded_a4_20261020/`.
- **Market-structure reading:** fails if the cost and execution model is wrong for the pool: too harsh for liquid US large caps (a hidden signal), or too lenient for thin Compustat Global legs, borrow-constrained shorts and non-synchronous home-market closes (a hidden loss).

## C-007 — Code and arithmetic claims (S34 central; re-derived 2026-10-10)
- **Reproduce:** `python research/rederive_code_claims.py` → `output/research/rederive_code_claims.parquet` (production
  code on synthetic input with known answers, or production constants). Independent adversarial review 2026-10-10
  (its corrections are folded in below).
- **P-087 — CORRECTED.** `coint_fraction_rolling` is the fraction of rolling windows (default 252 bars, step 21) with
  p < 0.05 and MIN_COINT_FRAC = 0.70 -- as stated. Omitted by the paper: (1) the test is ONE direction (a on b) at a
  fixed lag of 1 (`_batched_eg_fixed_lag_tstat`, analysis.py:1832-1838), not discovery's max over both directions at
  max lag 10, so a borderline pair's fraction can depend on leg order; (2) a pair whose gap-free history is shorter
  than window+step gets NaN / `insufficient_history` and is KEPT as `untestable_kept` (analysis.py:1926-1933, 6338) --
  it never faces the 0.70 threshold; (3) for shallow timeframes the window is shrunk once per batch from the first
  pair's grid length (analysis.py:2271-2278).
- **P-088 — CORRECTED.** The override also requires n_overlap >= `_MIN_BARS_FOR_SECONDARY_EVIDENCE` = 756 bars
  (BUG-D68; analysis.py:6324, 6379-6380), which the paper omits. The FANG/OXY worked example (P-089) was verified
  2026-06-23, before BUG-D68 and A5, and must be re-checked against the 756-bar rule before it is cited.
- **P-091 — REPLICATED.** Production `SpreadModel.rolling_zscore` (ddof=1) gives 15.81151378755267 = 251/√252 at a
  252-bar window. Caveat: today's window is adaptive (8 × half-life, clipped to [30, 252]; since 2026-10-19 the half-life comes from
  the pair's formation bars on point-in-time paths); the artifact is
  (w-1)/√w at window w, and 15.8115 only at the 252 cap. "Matched to 10 significant digits in observed output" is
  not re-checkable here.
- **M-038 — CORRECTED.** `chunked_pearson_candidate_pairs` returns the same pair set as the direct call (1,800/1,800;
  1,843/1,843 with 30% NaNs) with correlations agreeing to ~1e-15 (floating-point summation order) -- equivalent,
  not "bit-exact". A pair could flip only within ~1e-15 of the threshold; none of 7,140 test pairs was within 1e-12.
- **M-039 — CORRECTED.** Same max-over-directions rule as `CointScanner.scan`, but the discovery scan dropped
  crashed tests from BH's m until BUG-D115 (fixed 2026-10-10). Effect measured, matching ERRATA: zero crashed tests
  on the 2026-10-12 re-run, and again on the 2026-10-20 1D discovery (CachyOS
  `logs/latest/latest_run_wrds_deep_history_episodic_scan.log`: Tier 1 `n_crashed_counted_p1: 0` of 1,058,994, Tier 2
  and Tier 3 "counted as p=1.0 in BH's m: 0"). The intraday scans do not log the count (not measured there).
- **M-040 — REPLICATED.** `_benjamini_hochberg` matches statsmodels `fdr_bh` exactly (20 × 500 p-values; ties,
  p = 0/1, p = kα/m). FDR_ALPHA = 0.05. Shared caveat: a NaN p-value makes every adjusted p-value NaN in both.
- **M-041 — CORRECTED.** EPISODIC_WINDOW_BARS = 2520 and STEP = 252 are right, but "unioning each window's
  qualifying pairs" describes only Tier 3's correlation prefilter. Confirmation is one BH correction over the whole
  (pair × window) family, a pair confirmed if at least one window survives (`episodic_bhfdr_confirm`; its docstring
  says it is not point-in-time safe -- the pools use the as-of version, S32).
- **Market-structure reading:** fails if none: statements about code and arithmetic.


## C-008 — Size of the production EG screen under the null (D11, 2026-10-18/19)
- **Claim:** on random pairs (full WRDS-merged universe at 1D/1M; the ~1,580-symbol yfinance cache at 15m/1h), the production two-direction EG screen (max p) rejects at or
  below nominal 5%: 15m 1.50% [0.55, 3.24], 1h 1.75% [0.71, 3.57], 1D 3.00% [1.56, 5.18], 1M 3.25% [1.74, 5.49]
  (400 pairs each, Clopper-Pearson). One direction alone rejects 6.75% / 6.75% / 7.75% / 8.75%. Replaces the
  pre-WRDS "7.75-12.75%, EG correctly guarding" result (PAPER.md §4.2.1, README), which paired series by row position,
  sampled the yfinance cache at 1D/1M and ran one direction.
- **Falsification:** a re-run on the same path rejecting materially above 5% (lower CI bound > 5%), or the
  synthetic check failing to recover a date-aligned cointegrated pair.
- **Data:** `load_full_universe(tf, columns=["close"])` (WRDS priority, IBKR off), `align_to_common_calendar` 10 years;
  1D 46,352 symbols (CachyOS 2026-10-19); 1M 2,858 symbols (WRDS monthly subset); 1h 1,581 and 15m 1,578 (yfinance).
- **Parameters:** `eg_pvalue_pair` both directions, max p; overlap floor max(`MIN_OVERLAP_BY_TF`, 60); pairs without
  repetition; seed 20260713.
- **Reproduce:** exactly `python research/eg_null_calibration_montecarlo.py --tf 1h 1M 15m --n-pairs 400` (Surface) and
  `--tf 1D --n-pairs 400` (CachyOS). One random generator runs through the `--tf` list in order, so running the
  timeframes one at a time gives different draws; each call overwrites
  `output/research/eg_null_calibration_montecarlo.parquet` (the 1D row exists only in the CachyOS copy). Check
  `debug/_verify_eg_null_calibration_d11.py`.
- **Code state:** 2ec0c521's script (Surface parquet written 2026-10-18 12:26, just before the commit; 6c2de4f9's later
  loader change affects mixed-frequency calls, not these single-TF runs); CachyOS 1D run on HEAD 7ae0f551
  (a HANDOFF-only commit on top of the same script).
- **Status:** **REPLICATED (2026-10-19)** for the stated scope: size on random pairs. Not measured: the screen's
  behaviour on the |corr| >= 0.6 candidate population (needs a correlation-matched null and a power study). CIs treat
  pairs as independent (legs reused, median 2, max 7, in the 1h review), so they are somewhat too narrow.
- **Market-structure reading:** fails if random pairs understate size on the real candidate set: cross-sectional dependence (industry and factor co-movement) among |corr| >= 0.6 pairs, and non-synchronous closes across exchanges, can inflate rejection there (N14 measures it).
