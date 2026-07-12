## STATUS 2026-07-12: everything below is DONE and migrated into Development.md's permanent
## record. Also fixed since the last update here: BUG-D59 (distance.py Sharpe aggregation),
## BUG-D58 (survivorship false positives), BUG-D57 (exchange-aware session handling) — all three
## found, fixed, verified, and the full pipeline re-run with all fixes applied. Development.md,
## BUG_LOG.md, PAPER.md's Abstract, and README.md's Current Results are all updated with final
## numbers. Safe to delete this file now — kept only because Ross hasn't asked for cleanup yet.

# temp_tasks.md — Session 28 handoff / token-limit backup plan

**Purpose**: this is a scratch handoff document, not a permanent project file. Written 2026-07-11
because this session is long and Ross is concerned it may hit a token limit mid-work. If that
happens, a fresh session (or this one resuming) should read this file first, then `Development.md`'s
most recent entries (search for "2026-07-11" — everything from the "Second-pass Development.md
staleness triage" entry onward is this session), to reconstruct exactly where things stand.

**Delete this file once its contents are either done or migrated into `Development.md`'s permanent
record** — it is not meant to be a long-lived project doc like `HANDOFF.md`.

---

## Live blocker — Phase 3 pipeline rerun (in progress RIGHT NOW in Ross's own terminal)

`analysis.py` has been killed 3 times when launched via Claude Code's own tracked background-task
mechanism this session (once ~6 min in, once ~12 min in, once at the ~25-30 min mark in an earlier
session) — looks like a ceiling on the tracking tool itself, not a script bug. Ross is now running it
directly:
```powershell
cd C:\Users\RossW\Projects\CAMARF
C:\Users\RossW\anaconda3\envs\trading\python.exe analysis.py 2>&1 | Tee-Object -FilePath latest_run_analysis_session28h.log
```
**Check `latest_run_analysis_session28h.log` for current progress before doing anything below that
depends on fresh data.** Once `analysis.py` completes, the remaining production pipeline order (per
`CLAUDE.md`'s Non-Negotiable Architecture Rule #1) is:
```
data.py (already run this session, read-only re-run not needed) → analysis.py (running now)
→ ml.py → backtest.py → stats.py → wfa.py → distance.py → sensitivity.py → report.py
```
Run each with the project's real python: `C:\Users\RossW\anaconda3\envs\trading\python.exe <script>.py`
— never bare `python` (see `CLAUDE.md` Known-Resolved Issues).

---

## Tasks blocked on Phase 3 — STATUS UPDATE: Phase 3 completed 2026-07-11 14:15 (301.7 min runtime,
## clean, no errors). Working through this list now, updating status inline.

1. **`ml.py`** — ✅ DONE. Ran clean; still insufficient data to train (17 examples/2 classes, need
   ≥30/class) — honest, expected result, not a failure. No `model_stage1.pkl` produced yet.
2. **`research/ml_lookahead_selftest.py`** — still queued (low priority now — ml.py confirmed only 17
   examples exist, so this will just re-confirm "insufficient data," not produce a new finding).
3. **BUG-D56 real comparison** — ✅ DONE. `latest_run_backtest_session28_d56_carveronly.log` vs.
   `latest_run_backtest_session28_d56_composed.log`: composing coint_frac_sizing with the carver
   forecast scaling took max drawdown from **$6,721.74 → $313.19** (~95% reduction) while Sharpe
   IMPROVED slightly (5.0619 → 5.1875), same 737 trades both runs. Real, meaningful result — the
   fix isn't just correct, it materially changes the strategy's risk profile for the better.
4. **Layer 2 comparison arm** — ✅ DONE. `latest_run_backtest_session28_layer1_ols.log` vs.
   `latest_run_backtest_session28_layer2.log`: regime conditioning alone (ML gate still a
   pass-through, no trained model) improved Sharpe **5.0435 → 5.3156** and P&L **$212,612 →
   $248,356**, identical 737 trades and $7,684.97 drawdown both runs (regime conditioning affected
   sizing, not entry/exit gating, in this dataset).
5. **`research/lo2002_sharpe_correction.py`** — ✅ DONE, and this is the big one. Real headline
   numbers: IS Sharpe 5.1717 (17 pairs, 1516 trades), OOS Sharpe 4.3877 (319 trades) — both notably
   below the OLD published 5.2935/5.2443 (expected, universe/data refreshed since Session 22).
   **The earlier "no material effect" conclusion from thin/partial data was WRONG on real data** —
   re-ran and found lag-1 autocorrelation IS statistically significant in both samples now (IS
   z=-3.36, OOS z=-4.44, both negative/mean-reverting). Fixed the script to compute significance
   explicitly instead of a static caveat. Corrected Sharpe (rho_1-only, the reliable estimator):
   **5.8130 IS, 6.9951 OOS** — naive UNDERSTATES by 11-37%. Full write-up + correction-in-place in
   Development.md ("CORRECTION — Lo (2002) re-run against the real Phase 3 headline data reverses
   the 'no effect' conclusion"). **OPEN DECISION FOR ROSS**: whether to promote the corrected Sharpe
   into PAPER.md's headline figures, or keep it as a comparison-arm/robustness finding only — the
   corrected numbers being HIGHER means promoting them needs care to not read as cherry-picking,
   even though the statistics are sound (verified via the same 200-shuffle null check as before).
6. **stats.py gold/silver/fat-tail counts (BUG-D55)** — ✅ DONE. Fresh, final: **17 gold / 8 silver /
   0 bronze** (25 testable of 26), **16/26 fat-tailed**. Supersedes both the old published numbers
   and this session's earlier BUG-D55-verification numbers (both were non-final data states).
7. **Task #7 (trial count)** — ✅ DONE. `deflated_sharpe.py`: **N trials = 47** (was 34/38). DSR
   z=6.23 IS / z=2.18 OOS (was z=11.02/6.48 — margin narrowed as expected, still clears the null).
   Holdout exposure now 28 (was 27). Fixed `README.md`:76 and `PAPER.md`:81. PAPER.md's Abstract got
   an explicit reconciliation-status flag since the surrounding Sharpe/pair/WFA numbers in that same
   paragraph are still Session 22 vintage — full Abstract renumbering is the next real item (below).

## Update: full pipeline rerun completed (2026-07-11) — wfa.py/distance.py/sensitivity.py/report.py

All ran clean against fresh Phase 3 data. Fresh numbers: WFA baseline 3.288/2.832 (exp/roll),
mm_exec best at 4.512/4.345, session_edge 3.628/3.517, cfrac_sizing notably low 1.146/1.052 (worth a
second look — not investigated further this pass). Distance-method comparison shifted favorably:
GGR Sharpe 7.865 (was -0.208), cointegration mean pair Sharpe 20.435 (was 11.741). Sensitivity grid:
entry_z=1.5 now best (9.105), differs from the old "z=2.5 optimal" note — worth re-checking that
CLAUDE.md backlog item against this fresh grid. report.py: 26/26 figures regenerated clean.

**Also root-caused (not just noted) the 17-vs-24-pairs gap while doing this**: found a real, new bug
— **BUG-D58**. `survivorship_exclusions.csv` conflates "removed from the S&P 500 index" with
"delisted/no longer trading" — DD, NOV, and FHN were all demoted out of the S&P 500 at some point
but are real, currently-trading, currently-confirmed-pair symbols with real 2023-2026 price data.
The survivorship OOS-truncation logic silently zeroed out 7/24 confirmed 1h pairs (29%) this run
because of this. Root-caused precisely (not guessed), quantified, NOT fixed — flagged for Ross
alongside the other open decisions since fixing it changes the pair-inclusion set and would move
every headline number again. Full write-up in Development.md, indexed in BUG_LOG.md.

## Remaining — full Phase 4 doc-alignment pass (not yet done)

The Abstract (PAPER.md ~line 75-89) and README.md's "Current Results" section still cite Session
22's IS/OOS Sharpe (5.2935/5.2443), 1028/296 trade counts, 23-pair breakdown by TF, and WFA range
(3.1-4.0) — none of these have been reconciled to this session's fresh Phase 3 numbers yet (fresh:
IS 5.1717/1516 trades, OOS 4.3877/319 trades, 17 backtestable pairs not 23). This needs:
- WFA rerun (`wfa.py`) — not done this session, needed before touching the WFA range figure.
- Reconciling WHY backtest.py only used 17 pairs when analysis.py's summary showed 24 @1h (worth
  root-causing, not just noting — likely a hedge-ratio or half-life validity filter, not investigated
  yet this session).
- Then a single coordinated rewrite of the Abstract + README's Current Results section together, so
  every number in one place is from the same run (not a repeat of the "trial count fixed, surrounding
  numbers stale" partial-fix pattern from this pass).

## Phase 4 — doc alignment pass (do AFTER the above numbers are fresh)

- `README.md` "Current Results (Session 22...)" section — replace with fresh pipeline numbers.
- `PAPER.md` cointegration tier counts, fat-tail counts — replace stale numbers per item 6 above.
- `PAPER.md` §9's `[TODO before finalizing]` note (still open, not touched this session): verify
  each target MFE program's (Baruch/Berkeley/Columbia) actual required AI-disclosure format —
  content is ready, presentation format against a specific program's rules is not yet confirmed.

## Real, unresolved decision points for Ross (not blocked on Phase 3 — can discuss any time)

- **BUG-D57** (found this session, NOT fixed): `DataCleaner._standardize()` (`data.py:1498-1500`)
  strips timezone before `snap_timestamps()`'s exchange-aware `.L`/`.T`/`.HK` session logic ever sees
  it — confirmed via a real live fetch (`debug/_verify_exchange_aware_live_fetch.py`) that the
  exchange-aware code is currently dead in production despite passing its synthetic test. A real fix
  means making `DataCleaner.clean()` itself exchange-aware (gap-filling, NYSE-session assumptions in
  `_fill_gaps`/`_get_nyse_sessions` too) — a shared function touching the IBKR path and all 1500+
  existing US symbols, not a small change. Needs Ross's go/no-go before touching it.
- **IBKR circuit-breaker** — still unresolved after 3 investigation sessions; only remaining lead is
  Ross checking IB Gateway's own local API message log directly, not further code-side debugging.
- **Tail-risk-vs-Sharpe framing** — only 2 data points so far (earnings blackout, regime "bad
  bucket"); needs 1-2 more risk-reducing variants compared on Sortino/Calmar before it's a real
  section, not attempted this session.
- **Bounded-lookback primary screen / PairCharacteristicsAnalyzer** — both gated on more data
  (universe expansion decision, and the ~2-week ML-gate accumulation clock respectively) — no action
  needed until those land.

## Lower-priority, not yet done, no urgency

- ~~`requirements.txt` pandas 3.0.3 drift's root-cause timeline~~ — **RESOLVED 2026-07-11** while
  waiting on Phase 3: `pandas-3.0.3.dist-info` created 2026-06-18 via conda, 4 days before
  `requirements.txt`'s first-ever commit (2026-06-22) pinned 2.3.2 — the file was wrong from the
  start, not a later drift. See Development.md's write-up.
- ~~Universe-growth Stage 4 (international/ADR layer) introducing session date~~ — **RESOLVED
  2026-07-11**: `git log -S "INTL_ADRS" -- config.py` pins it exactly to commit `6f4ca8b5`,
  2026-06-30 17:31:20, Session 22. See Development.md's write-up.
- Corporate-actions reconciliation — still just a 4-symbol spot-check, scoped as lower priority.

## Housekeeping

- **Not yet committed/pushed this session.** Current uncommitted work (per `git status`):
  modified `CLAUDE.md`, `Development.md`, `PAPER.md`, `backtest.py`, `ml.py`; new
  `BUG_LOG.md`, `debug/_verify_bug_d56_compose.py`, `debug/_verify_exchange_aware_live_fetch.py`,
  `debug/_verify_ml_feature_lag.py`, `research/lo2002_sharpe_correction.py`,
  `research/ml_lookahead_selftest.py`. Several `latest_run_*.log` files also touched (auto-generated,
  fine to include or let `.gitignore` handle per its existing pattern). **Do not commit/push without
  Ross's explicit go-ahead** — per this project's standing git safety rule, never assume prior
  approval carries forward.
- This file itself (`temp_tasks.md`) should be deleted once no longer needed.

---

## Quick index of what THIS session already completed (for orientation, not action)

Doc fixes: File Inventory table, Cointegration Hierarchy/Hedge Ratio Methods tables, Bar Alignment
8h-row removal, Session 3/3b rename, Model Recommendations table refresh, Comprehensive Outline
superseded-banner — all in `Development.md`. `BUG_LOG.md` built (pure index, 60 entries). Lo(2002)
correction applied to real data (clean negative result, verified via permutation null check).
BUG-D56 fixed + synthetically verified. `vix_ts_regime` investigated — audit's original diagnosis was
wrong, corrected in place, no code bug (Layer 2 simply never run in production — this is what item 4
above now addresses). Mechanical lookahead self-test built, caught and fixed its own design bug via a
synthetic check before trusting it. BUG-D57 found and root-caused (not fixed) via a real
international-symbol fetch. PAPER.md §9 restructured against the AID Framework's real 14-category
taxonomy (Weaver 2024/arXiv:2408.01904), including a self-caught fix to a stale "no web search was
ever used" claim. Full detail for all of the above is in `Development.md`'s 2026-07-11 entries, in
this order.
