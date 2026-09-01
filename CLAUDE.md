# CAMARF — Project Context for Claude Code

Read this first, every session. Full history, bug post-mortems, and design rationale live in
`DEVELOPMENT.md` (canonical project memory) — this file is orientation + non-negotiable rules
only. Current open items: `docs/HANDOFF.md`. Reproducibility numbers/data ranges: `PAPER.md`.

## What This Project Is

CAMARF (Cross-Asset Co-Movement Arbitrage Research Framework): institutional-grade statistical
arbitrage research. **Standing direction (confirmed 2026-09-01): use the full ~44,700-symbol
WRDS-merged universe (`universe_loader.load_full_universe()`) everywhere a script can, not the
smaller ~1,500-1,700-symbol S&P Composite 1500 / yfinance-only cache** — the S&P Composite 1500 is
this project's historical starting baseline (still `config.py`'s `UniverseConfig` default for
daily-fetch scoping), but the ~44,700-symbol pool (WRDS full US market + international GVKEY-
labeled listings + yfinance + IBKR intraday + Binance crypto) is the actual target scope for
research/discovery scripts — this is precisely what the 2026-08-24 universe-undercount bug fix
(5 `research/*.py` scripts silently reinventing their own universe loader instead of calling the
shared one) was about, and the standing rule going forward. Also spans crypto/forex/commodities/
futures/ETFs. Built by Ross, sole developer, partly to support MFE applications (Baruch, Berkeley,
Columbia) — the codebase is both the research project and the thesis.

A connected but separate project: a live NQ/ES futures pairs-trading system (Goldbach levels,
FVGs, digital root timing, "17→71" lead-lag signal). Directional, not mean-reversion. Separate
codebase and session log — shares conventions with CAMARF, don't conflate the two.

**Thesis:** cross-asset co-movement exhibits regime-dependent, volatility-normalized arbitrage
structure, predictable at statistically significant rates via multiclass ML.

## Architecture Rules (non-negotiable)

1. **`data.py` fetches, `analysis.py` analyzes — never reversed.** `analysis.py` always calls
   `builder.build(connect=False)`, never touches IBKR/yfinance directly.
2. **yfinance is primary daily fetch.** WRDS/CRSP is primary for daily-and-coarser US
   equity/ETF (CRSP total-return-adjusted, Compustat Global fallback). `data_ibkr.py` is a
   separate, manual, supplemental deep-history fetch for confirmed pairs only — never merge its
   fetching into `data.py`'s path (see DEVELOPMENT.md Session 5-7 for why). IBKR's cache is,
   however, the only source in this project for real intraday depth (1m–4h) and is used for
   discovery via `universe_loader.py` (`include_ibkr=True`). IBKR has zero forex/commodity data.
3. **GapFlag governs all gap handling.** DATA_GAP (>5 consecutive missing bars) is masked to
   NaN via `_gap_aware_returns()`/`_clean_close()` — never forward-filled into a correlation or
   cointegration calc. `_clean_close()` returns `np.ndarray`, not `pd.Series` — wrap with
   `pd.Series(...)` before any pandas op (BUG-D51).
4. **No bandaid fixes, no menus of options.** Root-cause fix, single recommendation, verified
   against a reproducing test before it's presented as done — not three alternatives to choose
   from, not a fix that's merely documented as done.
5. **Production-ready, single-file output.** No fragmented artifacts needing manual assembly.
6. **Never silently correct away a known bias.** Kelly lookahead, in-sample stop comparison,
   survivorship (current-constituent-only universe), small-n filtering — always disclosed.
7. **Honest over impressive.** Never inflate a Sharpe/confidence/reliability number. Report
   contested findings honestly, both sides. Every headline claim needs its exact data range,
   universe snapshot, and params documented so an independent party could reproduce it.
8. **Document what was tried and reverted, not just what was kept**, in `DEVELOPMENT.md` — the
   full attempt, how it was verified, the real (not guessed) failure mode, why it was reverted.

## Known-Resolved Issues — do not re-suggest these fixes

- **Run scripts via `C:\Users\RossW\anaconda3\envs\trading\python.exe`, never bare `python`.**
  Base anaconda lacks yfinance and has a mismatched pyarrow (24.0.0 vs 19.0.0) — cross-version
  pyarrow reads misreport valid parquet as corrupted.
- **yfinance 0.2.66+ manages its own session** — never pass a custom `requests.Session()`.
- **yfinance period limits are fixed, don't reinvent:** 1m/3m→5d (3m is resampled from 1m, not
  fetched — Yahoo's 1m hard limit is 8 days), 2m→55d, 5m/15m/30m→60d, 1h/4h→730d, 1D/1M→max.
  Always key the day-count by the actual Yahoo interval requested, not the CAMARF timeframe
  label — a prior bug kept the wrong key and 7x-overshot the limit.
- **8h timeframe doesn't exist** — removed, no native yfinance interval, no analytical value.
- **4h is resampled from 1h with session-aligned bins**: `resample("4h", origin="start_day",
  offset="9h30min")`. Clock-aligned bins break on the 9:30–16:00 session. Filter gaps >8h
  (overnight/weekend) before computing the frequency-validation median.
- **S&P 400/600 Wikipedia scrapers are correct; failures are network flakiness**, not a parsing
  bug (verified via isolated standalone test). Don't re-investigate the parser — increase
  retry/delay if still flaky.
- **Never cache an empty constituent-fetch result** — only write on non-empty `fresh_tickers`.
- **Universe-size guard (`len(raw_assets) < 1000`) must stay** — caught a real silent-shrink
  incident once already.
- **Verify file edits actually landed** — grep for a unique string or diff after any edit;
  don't trust a tool call succeeded without a positive-content check.
- **CFTC COT dataset ID is `6dca-aqww`**, not `jun7-7nt5`. Contract prefixes: `"E-MINI S&P 500"`
  (ES), `"NASDAQ MINI"` (NQ). Use `requests.get(url, params=dict)`, never hand-encode the URL.
- **`ibkr_supplement_reader.py`, not `data_ibkr.py`, for reads** — `analysis.py`/other consumers
  import the read-only reader (no `ib_insync` dependency), never `data_ibkr.py` directly.

## Environment

Surface, Snapdragon X Elite (ARM64), 12 cores, 16GB RAM, Windows 11. The `trading` conda env's
Python is x86-64 running under ARM emulation (Prism), not native ARM64 — a real, unquantified
performance cost on top of MKL not being tuned for this chip. 16GB RAM is adequate, not
generous — expect existing OOM guards to trip on `DataAligner`'s dense intraday reindex or the
full-universe correlation matrix on a lower-RAM machine.

Second machine: CachyOS, SSH key-auth as `rw`. **Prefer Tailscale first**: `rw@100.64.64.126`
(hostname `cachyos-x8664`) — installed 2026-08 as the durable fix after CachyOS's WiFi turned out to
have client isolation enabled, which silently breaks LAN-IP SSH independent of whether the LAN IP
itself is current. Check `& "C:\Program Files\Tailscale\tailscale.exe" status` for reachability/
last-seen before assuming a hang. LAN fallback: `rw@10.0.1.9` (IP as of 2026-08-23 — check
`docs/HANDOFF.md` if stale; a `10.0.1.0/24` port-22 scan finds it if the IP has moved again). CachyOS
has also shown recurring hard hangs with no diagnosable cause (non-ECC RAM, no EDAC/thermal trail) —
an Intel TCO watchdog (`iTCO_wdt`) is armed so a hang auto-recovers in ~30-60s instead of needing a
physical power-cycle; a prolonged Tailscale "offline" reading may mean a hang the watchdog didn't
catch, not just a network issue.

## Working Style

- **New methodology, metric, or architecture pattern → explain it, get Ross's buy-in, before
  building.** This is his thesis; he directs every methodological choice. Applies even under
  autonomous/auto-mode operation — pause on concept-level decisions specifically.
- **A concept from research never goes straight into production.** Build it as a comparison
  arm/variant alongside the existing method first, discuss the comparison, then decide.
- **When stuck ~3 attempts on the same root cause, stop and ask for raw, unsummarized
  evidence** instead of guessing a 4th time. Distrust third-party tool summaries of technical
  output the same way — ask for the literal raw text when something doesn't add up.
- **Push back plainly, including on Ross's own proposals**, when something has a real problem —
  a methodological flaw, a result that won't hold up. Silence/agreement when something's wrong
  is a failure mode here, not politeness.
- **One agent/subagent dispatch at a time for audits and sweeps** — never parallel, even for
  independent read-only work. Run sequentially, wait for each result, then dispatch the next.
- **Before running a new pipeline stage or research script, self-check it against known bug
  classes first** (lookahead, in-sample circularity, gap-masking, survivorship) — don't wait
  for a dedicated audit to catch it after the fact.
- **Avoid hardcoding — derive values, don't fix them.** Worker/thread counts from
  `os.cpu_count()`, window/threshold constants from an actual empirical test of what produces a
  valid result, not a number that "seemed right" once. When you fix one hardcoded value, check
  whether the SAME value is hardcoded elsewhere too — `n_workers=12` was fixed once (2026-08-20,
  `Config.RUNTIME.N_WORKERS`) and still recurred twice more (`analysis.py`'s own `--workers`
  CLI default, `pit_wfa.py`, both found 2026-08-23) because the first fix didn't grep for the
  same literal value elsewhere.
- **When a backtest result is weak, question the pair-*selection* criteria before concluding
  the trading idea doesn't work** — loose FDR threshold, single-window confirmation, candidate-
  pool lookahead have each been the real cause before (BUG-D112).
- **Portfolio-level, capital-constrained (`--capital-sim`) PIT backtest results are the
  headline** over per-pair backtests — per-pair is fine as a diagnostic, never the reported
  result.
- **Read `latest_run_data.log` / `latest_run_analysis.log` first** when diagnosing a `data.py`/
  `analysis.py` run — structured, LLM-readable, written automatically after every run.
- **Run the 5 `council-*` agents together at real milestones, never one alone** — independent
  blind convergence is the point. `/code-review` after any nontrivial change to
  `data.py`/`analysis.py`/`backtest.py`/`ml.py`. Don't install `ponytail` (its "avoid
  over-engineering" stance conflicts with this project's verify-everything discipline).

## File Map

- `data.py` (yfinance-primary fetch), `data_ibkr.py` (IBKR supplemental, confirmed pairs only),
  `ibkr_supplement_reader.py` (read-only reader), `data_wrds.py` (WRDS/CRSP fetch)
- `analysis.py` (correlation/EG/eigenportfolio/Hurst/regimes/trios), `ml.py` (meta-labeler),
  `backtest.py` (event-driven engine), `macro.py` (FRED regime context), `config.py`
- `research/` — standalone comparison/diagnostic scripts, not part of the production pipeline.
  Each tests one claim, has a synthetic check in `debug/`, writes to `output/research/*.parquet`.
  Run from project root (`python research/foo.py`), not from inside `research/`.
- `debug/_verify_*.py` — synthetic proofs backing `research/` scripts' claims, not scratch.
- `DEVELOPMENT.md` (canonical memory, full bug registry), `docs/BUG_LOG.md` (one-line index into
  it), `docs/HANDOFF.md` (current open items), `PAPER.md` (living thesis draft),
  `docs/FINDINGS.md` (full-depth writeups PAPER.md summarizes)

## graphify

Knowledge graph at `graphify-out/`. For codebase questions, run `graphify query "<question>"`
first when `graphify-out/graph.json` exists — `graphify path`/`graphify explain` for
relationships/concepts. Read `GRAPH_REPORT.md` only for broad architecture review. Run
`graphify update .` after code changes.
