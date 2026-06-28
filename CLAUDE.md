# CAMARF — Project Context for Claude Code

**Read this first, every session.** For full history, bug-by-bug post-mortems,
and detailed design rationale, see `DEVELOPMENT.md` in this same directory —
that file is the canonical project memory. This file is the fast-orientation
layer: what the project is, what's locked in, what NOT to re-suggest, and how
to work with Ross (the developer) effectively.

---

## What This Project Is

CAMARF (Cross-Asset Co-Movement Arbitrage Research Framework) is an
institutional-grade statistical arbitrage research framework targeting
1,500+ assets (S&P Composite 1500 + crypto/forex/commodities/futures/ETFs).
Built by Ross, sole developer, in part to support MFE program applications
(Baruch, Berkeley, Columbia).

A connected but separate project: a live futures pairs-trading system
(NQ/ES, MNQ/MES) using Goldbach price levels, FVGs, liquidity voids, digital
root timing, and a lead-lag "17→71" signal propagation system. This is
explicitly NOT mean-reversion — NQ structural setups are directional filters
for ES entries during 7–10 AM EST killzones. Separate codebase, separate
session log registry, shares methodology/infrastructure conventions with
CAMARF but do not conflate the two.

**Research thesis (CAMARF):** cross-asset co-movement relationships exhibit
regime-dependent, volatility-normalized arbitrage structure predictable at
statistically significant rates using multiclass ML.

---

## Non-Negotiable Architecture Rules

1. **`data.py` fetches. `analysis.py` analyzes. Never the reverse.**
   `analysis.py` must always call `builder.build(connect=False)`. It must
   never touch IBKR or yfinance. If you see analysis.py doing a fetch,
   that's a regression — fix it immediately, don't rationalize it.

2. **yfinance is primary. IBKR is supplemental-only, run separately.**
   `data.py` is yfinance-only (`connect=False` default) and must complete
   in ~30-40 minutes with no IBKR dependency. `data_ibkr.py` is a SEPARATE
   script, run manually, that fetches 10-year deep history for CONFIRMED
   PAIRS ONLY (read from `confirmed_pairs_manifest.json`), enabling the
   episodic cointegration test. Never merge IBKR fetching back into the
   main data.py path — this was tried, it was the source of weeks of
   instability, see DEVELOPMENT.md Session 5-7 bug registry before ever
   reconsidering this.

3. **GapFlag system governs all gap handling.** Six codes: NONE, FILL,
   NO_ACTIVITY, HALT, DATA_GAP, SPARSE. DATA_GAP (>5 consecutive missing
   bars) is masked to NaN in EG/correlation via `_gap_aware_returns()` /
   `_clean_close()`. Never silently forward-fill a DATA_GAP bar into a
   correlation or cointegration calculation.

4. **No bandaid fixes. No multiple alternative solutions offered.** Ross
   wants the single best fix for the actual root cause, verified before
   being presented as done. See "Working Style" below — this is the most
   important behavioral instruction in this file.

5. **Production-ready, single-file output.** No fragmented artifacts
   requiring manual assembly. Complete files only.

6. **Bias documentation is non-negotiable.** Known biases (Kelly lookahead,
   in-sample stop comparison, survivorship from current-constituent-only
   universe, small-n filtering) are documented, never silently corrected
   away or ignored.

---

## Known-Resolved Issues — Do Not Re-Suggest These Fixes

This list exists because Ross and a prior Claude session spent real time
re-discovering each of these. Check here BEFORE proposing a fix that touches
yfinance, the Wikipedia scrapers, or the universe-construction pipeline.

- **Run project scripts with the `trading` conda env, not base anaconda.**
  `C:\Users\RossW\anaconda3\envs\trading\python.exe` is the project's real
  environment (yfinance, pyarrow 24.0.0 pinned, everything in
  requirements.txt). Bare `python` on PATH resolves to base anaconda, which
  is missing yfinance entirely and caused a real, hard-to-diagnose failure
  (every confirmed pair in an `ml.py` run silently skipped with a swallowed
  `ModuleNotFoundError`) — see DEVELOPMENT.md BUG-D44. If you ever need an
  ad-hoc pip install to inspect something, do it in a throwaway/no
  consequence way — installing into base previously downgraded pyarrow and
  made every parquet file written by `trading`'s pyarrow 24.0.0 look
  corrupted to base's pyarrow 19.0.0 (it wasn't corrupted — cross-version
  pyarrow incompatibility, "Repetition level histogram size mismatch").

- **yfinance 0.2.66+ requires its own internal `curl_cffi` session.**
  NEVER pass a custom `requests.Session()` to `yf.Ticker()`. It will raise
  `YFDataException: Yahoo API requires curl_cffi session`. Use plain
  `yf.Ticker(symbol).history(period=..., interval=...)` — yfinance manages
  its own session/cookie/crumb caching internally.

- **yfinance period strings: use what's in `_YF_INTRADAY_MAP`, don't
  reinvent.** 1m→5d, 3m→5d (derived from 1m, NOT a separate long period —
  3m's underlying interval is 1m, which has Yahoo's 8-day hard limit), 2m→55d,
  5m/15m/30m→60d, 1h→730d. A prior fix attempt built a day-count table keyed
  by the wrong variable (tf_label instead of yf_interval) and silently
  requested 55 days at 1m granularity — 7x over the limit. Don't repeat
  this class of bug: always key by the ACTUAL interval being requested from
  Yahoo, not the logical CAMARF timeframe label.

- **8h timeframe does not exist.** Removed entirely. yfinance has no native
  8h interval and it added no analytical value over 1D. If you see 8h
  referenced anywhere, that's stale code — remove it.

- **4h is derived from 1h via resample, and must use session-aligned bins.**
  `pd.resample("4h")` defaults to clock-aligned bins (00:00, 04:00, 08:00...),
  NOT market-open-aligned. A 9:30-16:00 session under clock alignment
  produces irregular bin counts with the overnight gap dominating naive
  median-gap frequency checks. MUST use
  `resample("4h", origin="start_day", offset="9h30min")`. Frequency
  validation on the derived output must filter gaps > 8h (structural
  overnight/weekend gaps) before computing the validation median, or every
  valid 4h derivation will incorrectly fail validation.

- **S&P 400/600 Wikipedia scrapers: verified correct logic, genuinely
  flaky network/Wikipedia behavior.** Confirmed via isolated standalone
  testing (table[3], col='Symbol', 579/603 tickers parsed correctly) that
  the scraping logic itself is NOT the bug. Failures are intermittent —
  same exact code succeeds sometimes, fails other times, no code-level
  fix found despite extensive investigation. `seed_sp_caches.py` includes
  retry logic (5 attempts, 8s delay) for this reason — don't try to
  "fix" this further with more diagnostic code; if it's still flaky,
  increase retry count/delay, don't re-investigate the parsing logic.

- **Never let `_fetch_constituents_cached` write an empty result to the
  cache file.** A prior version unconditionally cached whatever the live
  fetch returned, including empty lists — this silently overwrote a good
  manually-seeded cache the moment ONE transient failure occurred. Current
  version only writes when `fresh_tickers` is non-empty. Don't revert this.

- **Universe size sanity check exists for a reason.** A guard fires if
  `len(raw_assets) < 1000` with a loud `!!!` banner. This caught a real
  incident (universe silently shrank to 86 assets, went unnoticed for
  multiple runs). Don't remove or weaken this guard.

- **Always verify file changes actually landed before trusting them.**
  Multiple incidents this project: edits were correctly generated but
  failed to persist due to assertion-before-write ordering bugs, or the
  user's local file got out of sync with what was provided. ALWAYS run a
  positive-content check (e.g. `grep` for a unique string from the new
  code, or an MD5 comparison) after any file edit before assuming it's
  live. Don't just trust that a `str_replace` or `create_file` call
  succeeded — verify the actual file state.

- **CFTC COT API: dataset ID is 6dca-aqww, not jun7-7nt5 (BUG-D50).**
  Correct dataset: `https://publicreporting.cftc.gov/resource/6dca-aqww.json`
  (Legacy Futures Only). Correct contract name prefixes: `"E-MINI S&P 500"` (ES)
  and `"NASDAQ MINI"` (NQ). Old "E-MINI NASDAQ-100 STOCK INDEX" was a pre-2000
  contract name; "E-MINI NASDAQ 100 STOCK INDEX - INTERNATIONAL MONETARY MARKET"
  is a legacy alias that hasn't been current for 20+ years. Use `requests.get(
  url, params=dict)` — never hand-encode `%27`/`%25` in the URL template, which
  breaks when test strings go through PowerShell (dollar signs eaten) and
  produces opaque LIKE-filter failures at the server if encoding is wrong.

---

## Hardware / Environment Specs (added 2026-06-24)

Ross's current development machine: **Microsoft Surface, Snapdragon(R) X
Elite X1E80100 (ARM64), 12 cores @ 3.40 GHz, 16 GB LPDDR5 RAM, Windows 11.**

**Important, found during the 2026-06-24 audit, not previously
documented:** the `trading` conda environment's Python is an **x86-64
(AMD64) build running under Windows' ARM64 emulation layer (Prism)**, not
a native ARM64 build — confirmed directly: `platform.machine()` reports
`AMD64` while `platform.processor()` reports the real underlying chip
(`ARMv8 ... Qualcomm`). `numpy`'s BLAS backend is Intel MKL, which is
heavily optimized for genuine Intel x86 silicon — running an x86-emulated
MKL build on ARM hardware is a real, likely nontrivial performance
penalty (emulation overhead stacked on top of a BLAS library not
optimized for this CPU at all), not just a theoretical concern. This is
a plausible contributing factor to this session's slower-than-expected
runtimes (e.g. the ~90-minute `DataAligner`-routed universe-wide
near-miss rescan) — not confirmed as the dominant factor (the
`align_intraday` row-bloat dead-code bug, fixed this session, is a more
directly-verified contributor), but a real, previously-unconsidered
variable worth keeping in mind for any future performance work. A
native-ARM64 conda/Python build, if one exists with adequate scientific-
stack support, would be worth investigating separately — not something
to switch to casually given how much of this project's reproducibility
story already depends on the current `trading` environment's exact
pinned versions (pyarrow 24.0.0 especially, see below).

**Minimum practical specs to run this project**, inferred from observed
behavior, not benchmarked: 16 GB RAM is adequate but not generous —
`DataAligner`'s dense intraday reindex (even with the OOM guard at
500,000 rows/symbol) and the vectorized `_pairwise_corr` correlation
matrix over the full ~1,500-symbol universe have both been observed
using several GB at once. A machine with less RAM should expect to hit
the existing OOM guards more often, not crash, but should be tested
before assuming it'll run an identical full pipeline pass cleanly.

See `requirements.txt` for exact pinned package versions — already
verified against the actual installed environment (not assumed), with
one known, unresolved version conflict flagged inline (`shap`/`numba`
vs. `numpy>=2.4`).

---

## Working Style — How to Collaborate With Ross

This is as important as the technical rules above.

- **This is a learn-as-you-go research thesis for Ross, not an execution
  exercise for Claude.** Every new concept, technique, or design idea — a
  new ML methodology, a new architectural pattern, a new metric, anything
  not already locked in this file or DEVELOPMENT.md — goes through Ross
  first: explain what it is, why it's relevant, the tradeoffs, and get
  explicit buy-in BEFORE building it. Ross wants to understand and direct
  each methodological choice, with Claude as a teaching/implementation
  partner, not a black box that silently picks the "right" answer. This is
  a different category from the bug-fixing rules below (e.g. "one best
  fix, not three alternatives" is about technical correctness once
  direction is already set — it does not mean skip the discussion when
  introducing something new). Even under autonomous/auto-mode operation,
  pause on concept-level decisions for Ross's input rather than treating
  "technically the right call" as sufficient justification to proceed
  alone.
- **Full comprehension before code.** Walk through the actual logic before
  touching anything. No code changes based on a guessed root cause.
- **One best fix, not three alternatives.** Ross doesn't want "Option A vs
  Option B" — find the single correct fix for the actual problem.
- **Verify before claiming done.** Write a synthetic test that reproduces
  the bug, confirm the fix resolves it, THEN present the fix. This project
  has a clear track record: code presented without verification has had
  bugs; code verified with a reproducing test case has not.
- **When stuck after ~3 fix attempts on the same issue, STOP and ask for
  raw evidence instead of guessing a 4th time.** This project's biggest
  time sinks were extended guessing loops on yfinance failures and the
  sp600 scraper — both were eventually solved in one step once asked for
  literal, unsummarized output instead of continuing to theorize.
- **Distrust third-party summaries of technical output.** When Ross pastes
  a summary of a log (from DeepSeek or another tool) rather than the raw
  text, treat it as a hypothesis, not ground truth — these summaries have
  contained outright contradictions and fabricated detail (e.g. claiming
  a nonexistent traceback). Ask for the literal raw text when something
  doesn't add up logically.
- **Don't curse, keep it direct and technical, no excessive hedging.**
  Ross wants production-ready answers, not a menu of possibilities.
- **Use `latest_run_data.log` / `latest_run_analysis.log`** — these are
  structured, LLM-readable run summaries written automatically after every
  `data.py` / `analysis.py` run. Ask for these directly instead of raw
  console scrollback.

---

## Recommended Plugins / Tools

- **`context7`** (installed) — use before writing/debugging code against
  yfinance, ib_insync, statsmodels, or scikit-learn, where exact current
  version behavior matters more than general training knowledge.
- **`feature-dev`** (official, bundled with Claude Code) — use this for
  the upcoming `ml.py`, `backtest.py`, `analyzer.py`, `macro.py` builds.
  These are genuine new-feature work, not bug-fixing — the structured
  explore/architect/review workflow fits.
- **`claude-md-management`** (official) — keep this file from drifting
  into an unmaintained mess as the project grows.
- **`skill-creator`** — consider building a CAMARF-specific skill if
  recurring patterns emerge (e.g. "diagnose a data.py log" as a packaged
  skill).
- **Explicitly NOT recommended: `ponytail`.** Its "write minimum code,
  avoid over-engineering" philosophy conflicts with this project's
  verify-everything, no-bandaid-fixes discipline. Don't install.
- **draw.io** — noted for later, near v1 shipment, for architecture/
  pipeline diagrams. Not a current priority.

---

## Current State (update this section each session)

See `DEVELOPMENT.md` Sessions 10–12 for full detail. Headline items:

- **BUG-D50 (COT API, Session 12)**: CFTC Socrata dataset ID was wrong
  (`jun7-7nt5` → `6dca-aqww`), ES/NQ contract name filters were wrong,
  and URL was hand-encoded instead of using `requests.get(params=)`.
  Fixed and verified: ES 1,497 rows (since 1997), NQ 229 rows (NASDAQ
  MINI, newer contract). macro.py now produces cot_es and cot_nq regime
  distributions without warnings.
- **ml.py training threshold crossed (Session 12)**: 79 confirmed pairs,
  125 labeled entry events (up from 12). Trained on 75, 68% holdout
  accuracy on 25 examples. ConformalPredictor: 88% empirical coverage
  (target ≥90%), avg set size 1.52. Class imbalance (75% not_converged
  vs. 25% converged) — evaluation metric choice (precision on converged
  vs. overall accuracy) is a backtest.py discussion item.
- **EG permutation check updated (Session 12)**: 38/79 flagged (48%),
  mean null_frac_sig = 0.230 (4.6× expected 0.05). DD-hub pattern: 7/17
  DD pairs at 1h pass, 10/17 flagged (high null_frac_sig 0.50-0.57).
  APOG cluster at 3m also heavily flagged. Policy: comparison arm until
  backtest.py, `permutation_robust` flag on PairResult populated from
  research parquet on each analysis.py run.
- **8h timeframe removed (Session 12)**: Scrubbed from data.py,
  config.py, and all related sets/dicts. Was never a valid analytical
  timeframe; showed "0 assets" in every analysis.py run.
- **VIX term structure + CFTC COT added to macro.py (Session 12)**:
  VIX 3m via VXVCLS (FRED). COT via CFTC Socrata 6dca-aqww. Both
  producing regime distributions (vix_term_structure, cot_es, cot_nq).
- **thin_info_content + permutation_robust on PairResult (Session 12)**:
  New flags, populated by `_apply_research_screen_flags()` from research
  parquets. Not in current pairs.parquet (old analysis.py ran); will
  populate on next analysis.py run. ml.py already has skip logic for
  `thin_info_content=True`.
- **backtest.py**: No code written; standing instruction unchanged.
  `backtest_discussion_questions.md` prepared for Ross's review. Awaiting
  Ross's answers before interactive build session.
- **Always run scripts via
  `C:\Users\RossW\anaconda3\envs\trading\python.exe`**, not bare
  `python` (see Known-Resolved Issues).

---

## File Map

**Production pipeline (root) — runs daily, ~6pm scheduled rerun for fresh data:**
- `data.py` — yfinance-primary fetch pipeline (~4,960 lines)
- `data_ibkr.py` — IBKR supplemental deep-history pipeline for confirmed pairs
- `analysis.py` — full analysis pipeline (correlation, EG, eigenportfolio,
  Hurst, regimes, trios) (~5,300 lines)
- `ml.py` — spread-resolution meta-labeler (Stage 1)
- `macro.py` — FRED macro regime context
- `config.py` — all configuration parameters
- `seed_sp_caches.py` — standalone S&P 400/600 cache seeder with retry logic

**`research/` — standalone comparison/diagnostic scripts, NOT part of the
production pipeline (reorganized out of root 2026-06-24 for clarity).**
Each script tests exactly one claim, has its own synthetic verification in
`debug/`, and writes its findings to `output/research/*.parquet`. Examples:
`lead_lag_scan.py`, `copula_pairs.py`, `near_miss_lag_scan.py`,
`lead_lag_permutation_check.py`, `tail_dependence.py`,
`eg_permutation_check.py`, `aligned_pair_loader.py` (shared utility these
import). Run from the project root, e.g. `python research/lead_lag_scan.py`
— never `cd research` first, the scripts add the project root to `sys.path`
themselves.

**`debug/` — ad-hoc scratch utilities and synthetic verification tests.**
`_verify_*.py` files are NOT scratch — they're the synthetic proof each
`research/` script's claims rest on, cited throughout DEVELOPMENT.md. Keep
this name; it's referenced by exact path dozens of times in DEVELOPMENT.md.

- `DEVELOPMENT.md` — canonical project memory, full bug registry, session logs
- `PAPER.md` — living draft of the actual paper/thesis, started Session 10
  (2026-06-23). Sections marked [DRAFTED]/[OUTLINED]/[TBD] — update
  alongside DEVELOPMENT.md whenever a session produces a citable finding,
  not just at project completion.
- `latest_run_data.log` / `latest_run_analysis.log` — auto-generated run
  summaries, written after every run, read these first when diagnosing
