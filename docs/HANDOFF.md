# CAMARF Handoff — Full Verification Sweep (post-Session 27)

**Written:** 2026-07-10, end of Session 27 (the longest session this project has had — full
pipeline reruns, a Kalman promotion attempt + rigorous revert, portfolio-construction research,
and a 13-module backlog clear-out). This document is a directive for the NEXT Claude session:
verify everything claimed below is actually true, not just documented — then keep going.

**Read `CLAUDE.md` first, in full, before anything else.** It has the non-negotiable architecture
rules, the working-style conventions, and the "Current State" section (which this handoff updates
the pointer for, but CLAUDE.md itself is the fast-orientation layer you should internalize before
touching code). This document assumes you've read it.

---

## Why this handoff exists

Session 27 ran very long and covered an unusual amount of ground: a full pipeline rerun (twice —
once with a Kalman change, once reverted), a real bug found and fixed in the permutation test, a
promoted-then-reverted Kalman filter change (with a rigorous 3-way comparison proving the revert
was correct), portfolio-construction research (convex optimization, ERC vs. simple sizing), and 13
new comparison-arm modules built in one sustained pass. That's a lot of surface area for something
to have drifted, been documented inconsistently, or missed a verification step under time pressure.

Nothing here is reported as broken — a validation pass at the end of the session found the codebase
internally consistent (all modules import cleanly, documentation doesn't contradict itself, the
pipeline output is in a clean, correct state). But "I didn't find a problem in a quick pass" is not
the same bar as "a dedicated, adversarial sweep found nothing" — that's YOUR job in this session.

---

## Ground truth to verify (don't just trust this list — confirm each item)

### 1. Pipeline state
- `output/results/*/pairs.parquet` and `spread_series_*.parquet` should reflect the LATEST clean
  `analysis.py` run (post-Kalman-revert). Confirmed at end of Session 27: 1h=18 pairs, 3m=1, 1M=1
  (20 total). **Verify this is still true** — `output/backtest/trades_layer1.parquet` should show
  `hedge_method` counts of 521 `ols` / 521 `kalman` (near-identical Sharpe between the two, since
  Kalman is back to origin-only and doesn't drive its own signal — confirm this, since if the two
  hedge methods diverge again, something changed back or a new bug was introduced).
- IS Sharpe should be ~5.40, OOS Sharpe ~5.24 (`output/backtest/portfolio_layer1.parquet` /
  `portfolio_layer1_holdout.parquet`). If these numbers have drifted materially, figure out why
  before trusting anything downstream of them.
- Full pipeline order, if you need to rerun it: `data.py` → `analysis.py` → `ml.py` → `backtest.py`
  → `stats.py` → `wfa.py` → `distance.py` → `sensitivity.py` → `report.py`. `data_ibkr.py` is
  separate, manual, requires IB Gateway running — only run it if explicitly asked, and see the
  "IBKR breaker" note below before expecting it to work cleanly.
- Always use `C:\Users\RossW\anaconda3\envs\trading\python.exe`, never bare `python`.
- **Known issue, unresolved twice now (Session 25 and Session 27):** `data_ibkr.py`'s historical
  data requests fail intermittently against IB Gateway with NO IB-side error ever surfacing — a
  genuine client-side silent timeout. Session 27 tested and REFUTED the hypothesis that the
  15-second `RequestTimeout` (data.py:2639, may have shifted line numbers since) was simply too
  short (0/6 succeeded at 15s, 0/6 at 60s — ruling out "just needs more time"). Per this project's
  own "stop after ~3 attempts, ask for raw evidence instead of guessing again" discipline, do NOT
  attempt a 4th guessed root cause without new evidence — the only remaining lead is IB Gateway's
  own local API message log, which needs Ross's direct access. If you're asked to fix this, START
  by reading Development.md's two existing investigation writeups (Session 25 "IBKR Circuit-Breaker
  Investigation" and Session 27's re-investigation) so you don't re-derive already-ruled-out
  hypotheses.

### 2. Kalman filter state — make sure the revert actually stuck
Session 27 promoted a 2-state (slope+intercept) Kalman filter to production, found it performed
genuinely worse in a rigorous 3-way comparison (fixed-share/gross/position-normalized), and
reverted via `git checkout ebc281fb -- analysis.py backtest.py debug/_verify_kalman_slope_intercept.py`.
**Verify:**
- `analysis.py`'s `HedgeRatioEstimator.kalman()` returns a 2-tuple `(beta_series, mean_beta)` —
  NOT a 4-tuple. If it returns 4 values, the revert didn't stick or was undone.
- `backtest.py` has NO `col_spread`/`col_z`/`col_hl` selection logic, no `spread_scale_normalize`
  STORM flag — these were Kalman-era additions, correctly absent post-revert.
- `debug/_verify_kalman_slope_intercept.py` should PASS when run directly — it's testing the
  RESTORED origin-only production filter against a starting synthetic case, not the reverted
  slope+intercept code.
- `research/kalman_slope_intercept.py` (the ORIGINAL comparison-arm script, untouched) should still
  run correctly — it calls production `kalman()` expecting the 2-tuple, valid again post-revert.
- Full narrative, the actual measured numbers, and the real mechanism (Kalman's intercept
  genuinely tracks real long-run drift and shrinks the residual ~27,800x — not a bug — but
  `backtest.py`'s fixed-share position sizing wasn't built for that scale difference, so fixed
  per-share commission ate the shrunk gross edge) is in Development.md's "Kalman slope+intercept
  promoted to production, then reverted" entry. Read it before touching this again.

### 3. New modules from the backlog clear-out — spot-check, don't just trust the docstrings
13 new files, all under `research/` except `options.py` (project root) and `backtest.py`'s new
`--storm-continuous-forecast-carver`/`--storm-continuous-forecast-linear` flags (the only backlog
item that touched production code, not just a comparison arm):

| File | What it does | Real result to verify still holds |
|---|---|---|
| `research/weak_exogeneity_test.py` | VECM `pvalues_alpha` per confirmed pair | 14/20 pairs show `symbol_a` leading |
| `research/financial_turbulence_index.py` | Mahalanobis turbulence, Ledoit-Wolf shrunk | 90th-pct threshold ~57.70 |
| `research/caviar_dynamic_var.py` | Dynamic VaR, SAV spec, Nelder-Mead w/ bounds | IS VaR range $354-$966 |
| `research/quantile_regression_forest.py` | True Meinshausen QRF on RandomForestRegressor | Only 13 real examples — same insufficient-data wall as ml.py |
| `research/graphical_lasso_clusters.py` | Sparse precision matrix, partial correlation | INCONCLUSIVE at current N (alpha≈0, no real sparsity) — don't treat as a positive result |
| `research/multiscale_entropy.py` | Sample entropy across 5 coarse-grained scales | All 19 pairs: low-then-rising entropy signature |
| `research/bias_budget.py` | Aggregates existing DSR/permutation/gap numbers | No new computation — will show STALE numbers if run without first re-running deflated_sharpe.py (see below) |
| `research/convex_portfolio_construction.py` | SLSQP max-Sharpe/Sortino, 2 constraint sets | Max-Sharpe +0.08-0.09 over equal-weight |
| `research/portfolio_position_sizing_correction.py` | ERC vs. inverse-cluster-size | Inverse-cluster-size WINS (0.72 vs ERC's 0.69) |
| `research/network_momentum.py` | Simplified lead-lag spillover (not a real GNN) | +0.036 corr, explicitly IN-SAMPLE, not walk-forward validated |
| `research/short_term_factor_alpha.py` | Reversal + day-of-week seasonality | Modest (+0.018, +0.004) |
| `research/portfolio_effective_bets.py` | Grinold-Kahn/Meucci/Carver on full portfolio | Meucci ENB~9.78 of 21 nominal pairs |
| `research/fill_timing_sensitivity.py` | Same-bar vs. lagged-fill backtest | Lagged is SLIGHTLY BETTER (reassuring, no lookahead inflation) |
| `research/jump_diffusion_spread_analysis.py` | Threshold jump detection vs. real trades | ~1-2% of bars are jumps, ~72-76% of variance |
| `options.py` | Realized-vol-proxy Black-Scholes overlay | Overlay INCREASES drawdown — genuine negative result, not a bug (verify the put/call-by-side fix is still there) |

Every one of these was verified via a synthetic test with known ground truth BEFORE being trusted
on real data, and every real bug found during that verification is documented in Development.md's
"Session 27 addendum — Full backlog clear-out" entry, including two that were caught by the
RESULT looking wrong (not a unit test): the weak-exogeneity verdict-label swap, and options.py's
put-instead-of-call direction bug (caught because the "hedged" drawdown was impossibly worse than
unhedged). If you're re-verifying these, the fastest path is re-reading that Development.md entry
first, then spot-running 2-3 of the scripts to confirm the real numbers still match.

### 4. Known staleness to actually fix (not just note)
- **`output/stats/deflated_sharpe.json` and anything `research/bias_budget.py` reports is stale.**
  `trial_registry.json` grew from 34 to 38 trials during Session 27's own comparison-arm testing
  (Carver scaling runs, position-sizing verification runs — genuine trials per `trial_registry.py`'s
  own "re-running IS itself a trial" philosophy, but not really new candidate configurations under
  consideration). Re-run `deflated_sharpe.py` once, then `research/bias_budget.py`, and update any
  place that cites "34 trials" if you touch those sections (Development.md, PAPER.md §2.3/§6.7).
- **Graphify's knowledge graph is stale.** Built at commit `27093654`, BEFORE all 13 new research
  scripts and `options.py` existed. Run `graphify update .` (no LLM/API cost, pure AST re-extraction)
  before relying on it for navigation — see the Graphify section below.
- **`CLAUDE.md`'s "Current State" section headline items are from Session 22** (2026-06-30) — I
  added a pointer at the top to Session 27, but the old Session 22 bullet points below it are now
  quite old and could be trimmed/archived once Session 27's own numbers are copied in properly (I
  did not do a full rewrite of that section — just added a redirect, to avoid a large, rushed edit
  at the end of an already very long session).
- **`README.md` has not been touched this session.** It's a high-level overview (Strictness Paradox
  headline finding, etc.) — spot-check it still accurately represents the project's current state
  and headline claims; it may not mention Session 27's work at all, which is fine if README.md is
  meant to describe the STABLE headline finding rather than track every session, but confirm that's
  actually the intent rather than an oversight.

### 5. Git state
12,878 changed files as of end of Session 27, essentially all `output/cache/`+`output/results/`
churn from pipeline reruns (gitignored-but-legacy-tracked from before that rule existed — see
CLAUDE.md/Development.md for that history) plus the genuine code changes: `CLAUDE.md`,
`Development.md`, `PAPER.md`, `backtest.py`, `deflated_sharpe.py`, 13 new `research/*.py` files,
`options.py`. **Nothing has been committed since commit `27093654`** ("Fix permutation-test null
inflation via day-level block bootstrap") — Session 27's later work (Kalman revert, backlog
clear-out) is entirely uncommitted. Do not run `git add -A` — stage the specific meaningful files
only, matching this project's standing convention (see CLAUDE.md). Confirm with Ross before
committing anything, per his own explicit standing instruction elsewhere in this doc's source
conversation.

---

## What "full code sweep, architecture sweep, pipeline run, data hygiene check" should mean here

Concretely, in priority order:

1. **Data hygiene check first** — this is the cheapest, highest-value pass. Confirm:
   - `GapFlag`/`DATA_GAP` masking is actually applied everywhere it should be (grep for
     `gap_flag` usage across `research/*.py` — every script that touches `spread_series_*.parquet`
     should mask `gap_flag_a != 4 & gap_flag_b != 4` before computing anything; this exact bug
     (forgetting this mask) was caught and fixed multiple times across Sessions 25-27 in different
     scripts — it's a recurring failure mode worth a dedicated grep sweep, not just spot-checking).
   - The fill-timing self-test and lookahead concerns flagged by this session's data-hygiene
     literature review (see Development.md's "data hygiene literature + GitHub guides" entry) — a
     mechanical "lag every feature by one bar, confirm performance degrades" self-test was
     identified as still missing. Consider building it if you have time; it's cheap and mechanical.

2. **Architecture sweep** — use Graphify (see below) to get a structural map, then specifically
   check: does every `research/*.py` script actually follow the "read-only, never fetches, never
   modifies production" convention it claims in its own docstring? Does `backtest.py`'s new
   `continuous_forecast_carver`/`continuous_forecast_linear` STORM flags interact correctly with
   the OTHER STORM flags if combined (they weren't tested in combination with e.g. `garch_stop` or
   `mm_exec` — only in isolation against the binary-sizing baseline)?

3. **Full pipeline run** — re-run the whole sequence end to end (data.py through report.py) to
   confirm everything still reproduces cleanly with ZERO errors, matching the "clean post-revert"
   state this handoff describes. If IB Gateway happens to be open, `data_ibkr.py` can be attempted,
   but see the known-issue note above — don't spend more than one attempt on it without new
   diagnostic evidence.

4. **Documentation alignment** — the actual ask ("Development.md showing everything correctly, bug
   log, PAPER.md, README, everything"). Concretely:
   - Development.md's bug registry (search for `BUG-D` prefixed entries) — confirm the numbering
     is still sequential/non-conflicting, and that Session 27's fixes (permutation-test bug, the
     weak-exogeneity label bug, CAViaR's optimizer-bounds bug, options.py's put/call bug) are
     either already logged there with a `BUG-D` number or intentionally logged differently (some
     of Session 27's bugs were logged inline in the relevant Development.md addendum rather than
     given a `BUG-D` number — confirm this is consistent with how OTHER research-script bugs from
     prior sessions were logged, or standardize it).
   - PAPER.md's reference list — **already fixed as of the end of this session**: entries 25-32
     were added for Kritzman & Li 2010, Engle & Manganelli 2004, Meinshausen 2006, Friedman/Hastie/
     Tibshirani 2008, Costa/Goldberger/Peng 2002 (+ Richman & Moorman 2000), Maillard/Roncalli/
     Teiletche 2010, Pu/Roberts/Dong/Zohren 2023, and Blitz et al. 2023 — all marked `[TBD]` (author/
     year/venue correct, exact page numbers not independently re-verified this session, matching
     this list's own existing convention for unverified entries). Spot-check a couple of these for
     accuracy rather than assuming they're perfect — I did not independently verify bibliographic
     detail (page ranges especially) the way the `[VERIFIED]` entries were.
   - If PBO/CSCV (Bailey, Borwein, López de Prado & Zhu 2015) ever gets its own dedicated
     implementation (not built this session — judged as substantially covered by the existing
     DSR + `trial_registry.py` mechanism), add that citation at that time; not added now since
     nothing in the codebase cites it yet.

---

## Using Graphify

Ross installed the `graphify` CLI (`uv tool install graphifyy`) and its Claude Code integration
(`graphify claude install` — wrote a section to `CLAUDE.md` + a PreToolUse hook in
`.claude/settings.json`). Read the `## graphify` section near the end of `CLAUDE.md` for the exact
usage convention it specifies (query/path/explain commands, when to consult `GRAPH_REPORT.md` vs.
the wiki vs. raw source).

**Before using it this session: run `graphify update .` first** (AST-only, no LLM/API cost) — the
existing graph at `graphify-out/` was built at commit `27093654`, missing all 13 new research
scripts and `options.py`, and won't have picked up the Kalman revert either (though that reverted
`analysis.py`/`backtest.py` back to what the graph's commit already reflects, so those two
specifically may be fine — don't assume, just rebuild). The graph also indexes Development.md's own
markdown session headers as nodes, which is genuinely useful for navigating that document's ~9,700+
lines without grepping blindly — worth leaning on for exactly the "is everything documented
correctly" sweep this handoff asks for.

If you want the interactive visual map (not required for the sweep, but useful for a human
reviewing the results): `graphify-out/graph.html` depends on an external CDN (unpkg.com for
vis-network) and will render blank in a sandboxed/CSP-restricted viewer — if you need to hand this
to Ross through a render pane rather than a normal browser, inline the library first (see how
Session 27 did this: downloaded `vis-network@9.1.6` via `curl`, string-replaced the `<script src=...>`
tag with an inline `<script>...</script>` block, saved as `graph_standalone.html`).

---

## Standing behavioral notes for this session (from how Session 27 actually went, not just CLAUDE.md's general rules)

- **Verify before claiming done, always** — every real bug found this session (5 of them, across
  weak-exogeneity, CAViaR twice, options.py) was caught specifically by comparing against a
  synthetic case with KNOWN ground truth, or by noticing a real-data result that looked impossible
  (a "hedge" that made things worse, an exceedance rate 19x the target). If a number looks too clean
  or too surprising, that's the moment to dig in, not the moment to write it up.
- **Report honest nulls as clearly as positive findings** — graphical lasso's inconclusive result,
  QRF's insufficient-data wall, and options.py's negative overlay result are all reported in
  Development.md/PAPER.md with the same care as the positive findings, not buried or softened. Keep
  that standard.
- **Don't force a "winner" when the evidence is a genuine tradeoff** — the Carver/linear forecast
  scaling comparison (better raw PnL, worse Sharpe) was reported as a tradeoff, not artificially
  resolved into a single recommendation. If your sweep finds something similarly ambiguous, resist
  the urge to manufacture a clean verdict.
- **Ross's own suggested future project**: a dedicated synthesis of when added complexity helps vs.
  hurts in this codebase (HRP loses to risk-parity, ERC loses to inverse-cluster-size, and the
  slope+intercept Kalman filter lost in production — three instances of simple beating complex — but
  Meucci's eigenvalue method caught real concentration risk Grinold-Kahn's simpler math structurally
  can't see — one clear instance of complex winning). Noted in Development.md's Session 27 addendum.
  Worth building if you have spare capacity after the verification sweep, not a launch blocker.

---

## What "perfect" actually means here (a calibration note, not a lower bar)

Ross asked for everything to be "perfect." Read that as: every claim in Development.md/PAPER.md/
README.md should be independently reproducible from the code and data as they actually exist right
now — not that every possible improvement has been made. This project's own CLAUDE.md rule 7 is the
right standard: "Honest, ethical, methodologically true and fair, and reproducible — non-negotiable,
not aspirational." A "perfect" handoff-verification pass finds and fixes real inconsistencies; it
doesn't invent new work to look thorough, and it doesn't skip real problems to finish faster.
