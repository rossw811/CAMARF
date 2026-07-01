# CAMARF — Project Context for Claude Code

**Read this first, every session.** For full history, bug-by-bug post-mortems,
and detailed design rationale, see `DEVELOPMENT.md` in this same directory —
that file is the canonical project memory. This file is the fast-orientation
layer: what the project is, what's locked in, what NOT to re-suggest, and how
to work with Ross (the developer) effectively.

---

## Claude Behavioral Guidelines (Karpathy method, adapted)

**Think before coding.** State assumptions explicitly. If multiple interpretations
exist, surface them. If a simpler approach exists, say so. If something is
genuinely unclear, stop and ask — don't silently pick the wrong path.

**Simplicity first.** Minimum code that solves the problem. No speculative
features. No abstractions for single-use code. No "flexibility" that wasn't
asked for. If 200 lines could be 50, rewrite it.

**Surgical changes.** Touch only what's required. Don't "improve" adjacent code
or formatting. Don't refactor things that aren't broken. Match existing style.
Every changed line should trace directly to the user's request.

**Goal-driven execution.** For multi-step tasks, confirm success criteria before
implementing. A strong definition of "done" means fewer re-dos.

**Tradeoff note:** These guidelines bias toward caution over speed.
For trivial, obviously-scoped tasks, apply judgment — don't over-process.

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

7. **Honest, ethical, methodologically true and fair, and reproducible —
   non-negotiable, not aspirational.** This governs every claim, number,
   and finding in this project, not just the bias-audit entries in rule 6.
   Concretely: never inflate a confidence score, Sharpe ratio, or reliability
   rating to make a result look stronger than the evidence supports — if a
   finding is genuinely contested in the literature or the data, say so and
   report the honest number, don't engineer around it. When citing external
   research, represent both sides of a genuine dispute, not just the side
   that favors CAMARF's thesis. Every empirical claim should be reproducible
   by an independent party: document the exact data range, universe
   snapshot, and parameters used for any headline result (see "Data Test
   Range & Reproducibility" below) so someone with no access to this
   repository's cached data could re-fetch equivalent data and verify the
   claim independently.

---

## Data Test Range & Reproducibility

Every headline result in `PAPER.md` must be traceable to the exact data an
independent party could re-fetch to verify it — not just to a cached parquet
file in this repo. For each full pipeline run reported in `PAPER.md` or
`Development.md`, record: the universe snapshot date and source (e.g. S&P
Composite 1500 constituents as of a given date, scraped from a named
Wikipedia revision or index provider), the exact calendar date range fetched
per timeframe (yfinance's own per-interval lookback limits mean 1m/2m/3m
history is much shorter than 1D/1h — see `_YF_INTRADAY_MAP` in
`Known-Resolved Issues` above), and the yfinance/pyarrow/statsmodels versions
pinned in `requirements.txt` at the time of that run. `reproduce.py` is the
existing mechanism for mapping a `PAPER.md` finding to the script that
generated it — extend it (or a paired document) so a reader can also
regenerate the *data* an entry depends on, not just re-run the analysis code
against whatever happens to be sitting in `output/cache/`.

**Current canonical data footprint (Session 22 full pipeline run, verified
against `latest_run_data.log`, not assumed):**

- **Universe snapshot:** 1,608 candidate symbols (S&P Composite 1500 +
  international equities/ADRs/FX spots), `data.py` run completed
  **2026-06-30 10:10**, runtime 5.6 minutes, config_hash `0c0e67a6b00ff0bb`.
  1,357 symbols resumed from existing cache; 0 excluded; 0 cache-contamination
  clears this run.
- **Per-timeframe yfinance fetch windows** (`_YF_INTRADAY_MAP`,
  `data.py:1869-1878`): `1m`/`3m` → 5 calendar days (3m is derived by
  resampling 1m, not fetched separately — Yahoo's 1m interval has an 8-day
  hard limit, 5d stays safely inside it); `2m` → 55 days; `5m`/`15m`/`30m` →
  60 days; `1h`/`4h` → 730 days (4h derived by resampling 1h with
  session-aligned bins, `origin="start_day", offset="9h30min"`); `1D`/`1M` →
  full available history via yfinance `period="max"`.
- **Pinned versions:** see `requirements.txt`, in particular `pyarrow==24.0.0`
  (cross-version pyarrow reads misreport valid parquet as corrupted — see
  Known-Resolved Issues above).

An independent party can regenerate statistically equivalent data by running
`data.py` with these same parameters against a current S&P Composite 1500
constituent list, without needing this repo's `output/cache/` directory at
all. Update this block whenever a new full pipeline run becomes the
canonical one for `PAPER.md`'s reported numbers — don't let it drift stale
the way `README.md` did before this section existed.

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

- **`_clean_close()` returns `np.ndarray`, not `pd.Series` (BUG-D51).**
  Calling `.rename()` on its return value raises `AttributeError`. Always wrap
  with `pd.Series(_clean_close(df), index=df.index, name="colname")` before
  using pandas operations (`.rename()`, `pd.concat` axis-alignment, etc.).
  Applies anywhere `_clean_close` is used outside data.py itself.

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

See `DEVELOPMENT.md` Sessions 10–22 for full detail. Headline items:

- **Session 22 (2026-06-30)**: Full architecture audit + fixes + full pipeline rerun. **COMPLETE.**
  - Architecture: F01 (ibkr_supplement_reader.py), F02 (IBKR config mutation removed),
    F03 (public API), F05 (session_edge_postopen), F06 (--entry-z), F07 (BUG-D49 filter wired).
  - **23 confirmed pairs**: IS Sharpe **5.2935** (1028 trades), OOS Sharpe **5.2443** (296 trades, 0.9% decay)
  - **Best variant**: risk_parity OOS Sharpe **5.8689** (+0.63 vs baseline) — recommended production
  - **WFA**: baseline expanding/rolling 3.13/3.27; mm_exec 3.82/3.96 (best); session_edge 3.34/3.58
  - **GGR distance**: Sharpe -0.208 vs CAMARF 11.741 (mean pair Sharpe, 17 @1h)
  - **ADV $25M Pareto-optimal**: Sharpe 7.412, 16 pairs, 174 trades
  - **session_edge reversal**: +0.87 on 5-pair set → −0.04 on 23-pair set; no longer recommended
  - **PAPER.md**: §3, §5, §6.1–§6.6, §7.1–§7.10 all updated with 2026-06-30 numbers
- **Session 21 (2026-06-29)**: BUG-D52 fixed (FDR_ALPHA 0.01→0.05, restored all 5 confirmed pairs).
  Full pipeline run: 5 1h pairs, Sharpe IS=3.2246, OOS=3.149, permutation p=0.86 IS / 0.67 OOS.
- **Session 19 (2026-06-29)**: distance.py (prior GGR Sharpe=-6.33 on 5-pair set), sensitivity.py,
  data_ibkr.py 38-symbol fetch, analysis.py kalman_drift_velocity field added.
- **Always run scripts via
  `C:\Users\RossW\anaconda3\envs\trading\python.exe`**, not bare
  `python` (see Known-Resolved Issues).
- **Next priorities**:
  - **SPY/VOO exclusion**: Remove trivial pair from confirmed_pairs_manifest.json next session
  - **STORM literature survey**: Raise monthly spend limit at claude.ai/settings/usage; run with
    `--depth standard` + Sonnet 4.6 (session 23)
  - **ML gate**: ~2 weeks from 2026-06-30 for training data accumulation (23-pair set clock reset)
  - **New modules** (planned): `corporate_actions.py`, `coint_frac_window_grid.py`,
    `cross_session_leadlag.py`, universe expansion (NASDAQ, Russell, crypto)
  - **Known issue**: entry z=2.5 is optimal in sensitivity grid (10.59 vs 9.18 for z=2.0);
    evaluate promoting to production default once 6+ months OOS history available

---

## File Map

**Production pipeline (root) — runs daily, ~6pm scheduled rerun for fresh data:**
- `data.py` — yfinance-primary fetch pipeline (~4,960 lines)
- `data_ibkr.py` — IBKR supplemental deep-history pipeline for confirmed pairs
- `ibkr_supplement_reader.py` — parquet-only reader for IBKR supplements (no ib_insync); imported by both data_ibkr.py and analysis.py
- `analysis.py` — full analysis pipeline (correlation, EG, eigenportfolio,
  Hurst, regimes, trios) (~5,300 lines)
- `ml.py` — spread-resolution meta-labeler (Stage 1; Stage 2 + SHAP pending)
- `backtest.py` — event-driven backtest engine (Layer 1 baseline + Layer 2 stub)
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
