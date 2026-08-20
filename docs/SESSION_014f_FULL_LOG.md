# Session 014f6574 — Full Chronological Log

Source: `https://claude.ai/code/session_014f6574WEQZKywfguD4Dish` ("Design pair analysis
pipeline implementation", CAMARF project). This is the session whose RAM-crash on the local
machine produced the handoff already partially captured in `docs/HANDOFF.md`'s "2026-08-16
update" entry. This file is a from-scratch, exhaustive re-read done specifically to close gaps
the original 40-tick-jump scroll-through in that handoff entry likely missed, per Ross's
instruction: "also make sure you fully read the old chat for every detail and comprehension.
don't gloss over anything."

**Coverage note, stated plainly**: I scrolled from the very bottom (the crash point) upward in
small (10-25 tick) increments, capturing full page text at every stop, all the way back through
the entire international/WRDS-universe-expansion arc, Thread I/J/K/M/N/O, the gs-quant
comparison-arm work, and into Thread G Phase 2's Kelly-sizing root-cause investigation
(Findings #26/#27). **I did not reach the session's literal first message** — this is an
extremely long session (at least two internal auto-compactions, one saving ~897k tokens per the
parent's own read, one saving 904.3k tokens per mine — these may be the same event described
with a slightly different remembered number, or two genuinely separate compactions; I could not
fully disambiguate). The earliest point I reached is Thread G Phase 2's completion writeup and a
direct confirmation that, at that point in the session, WRDS had only been wired as a **data-source
swap** for the existing ~1,660-1,730-symbol universe (better-quality OHLC, not new tickers) — the
international/global expansion work described below all happens *after* this point,
chronologically. Anything before this point in the real session is NOT covered here.

Organized in **reverse-chronological-discovery order** (i.e., the order I actually read it,
newest-first) since that's how the scroll-back happened and preserves the real evidence trail.
Read bottom-to-top if you want strict chronological order.

---

## Section 12 (most recent) — Already fully covered in `docs/HANDOFF.md`

Thread J Test 1 launch/monitoring, the 3y/5y/10y full-universe cascade + its artifact (with the
GVKEY cross-listing-duplicate correction), the two OOM bug fixes
(`build_log_prices_and_returns_bounded`, `chunked_pearson_candidate_pairs`), `universe_loader.py`'s
`align_to_common_calendar`/`filter_exact_correlation_duplicates`, and the SPY/VOO
`filter_structural_pairs` fix are all already accurately captured in `docs/HANDOFF.md`. Not
repeated here. One thing I confirmed while re-reading this stretch: nothing in it contradicts the
handoff's account — the correction on my own part (the "3-way comparison is already done, not
pending" fix already applied to HANDOFF.md) still stands as the corrected version.

---

## Section 11 — Universe methodology audit request + rewiring (this same conversation, later turns)

Not part of the crashed session — this is the current, live conversation's own work (methodology
audit across old/new universe methodologies, the SPY/VOO `filter_structural_pairs` fix, rewiring
`k_bahc_candidate_discovery.py` and 3 more duplicated-loader scripts to `universe_loader.py`).
Already fully in this conversation's own context — not re-summarized here.

---

## Section 10 — Illiquid-bars / entry-exit-risk-management research-script integration (NEW, not in HANDOFF.md)

**Origin, Ross verbatim**: *"also reading through i realized there's a lot of data which is
unuseable or unfavorable so i was wondering what we can do to mitigate that? i also was wondering
if we can implement, for research use, for our entry exit risk management some of the research
scripts? thoughts? like i was thinking maybe implementing the jump diffusion as a criteria can be
useable and can be interesting. thoughts?"*

- **Bar-level illiquid-days finding** (international universe, from the Thread I threshold-
  sensitivity work): 15.2% of symbols (824) have hidden illiquid days despite passing the
  flat-average liquidity filter — median bar-level pass rate just 0.48 (nearly half their days
  are individually illiquid even though the symbol "passes" on average). Only 2.4% show the
  opposite problem. **Real conclusion: the current filter's risk is false positives (letting
  through nominally-liquid-but-actually-thin symbols), not false negatives.**
- Claude's mitigation menu (in priority order): (1) bar-level liquidity gating instead of pure
  symbol-level, (2) widen the tradeable universe (Thread K), (3) use intraday timeframes more,
  (4) block-bootstrap/resampling for thin-sample inference, (5) passive accumulation (some
  questions just need more calendar time). Explicit honest line: *"no data-cleaning trick makes
  a real negative Sharpe into a positive one, and per this project's own rule 7, I shouldn't
  try."*
- **Jump diffusion proposal**: `research/levy_jump_diffusion.py` already exists (Lee-Mykland 2008
  bipower-variation jump test), currently a pure diagnostic. Two concrete uses proposed: entry
  filter (skip/delay entry on a detected jump bar) and exit signal (tighten stop/force exit on a
  mid-hold jump). Causality of the Lee-Mykland local-vol estimator flagged as needing verification
  before wiring into live logic — **not yet verified or built, as far as this reconstruction shows**.
- Ross, verbatim, the actual standing directive for a large chunk of this session's remaining
  work: *"i like your idea - skip trades and avoid use of illiquid bars. counting illiquid bars
  will falsely spike our cointegration number. you should try data cleaning for the sharpe, if
  there's a data problem it should be addressed ASAP. i like those ideas let's get it implemented
  as a comparison for entry exit and risk management etc and let's consider other scripts to use
  as well like cycle detection k means average etc etc. i want all the research scripts which we
  can tested out in the strategy. this also includes momentum.*
- Ross, separately, a standing methodology directive: *"also for all of our results i want to
  investigate the why it happens and reasons behind it."*
- **`liquidity_bar_masking.py` built.** First hypothesis (illiquid bars inflate Pearson
  correlation) was WRONG — correlation is scale-normalized, zero-return days don't clearly bias
  it. Investigated further, found the REAL mechanism: **spread variance is suppressed during
  frozen illiquid blocks** (5.5e-17 vs 0.133 for liquid-only data on synthetic data) — stale bars
  make the spread look artificially mean-reverted, inflating ADF/EG apparent significance.
  Rewrote the diagnostic around this correct mechanism, 6/6 synthetic checks.
  - **Run against real Purity pairs — the synthetic mechanism did NOT hold**: mean
    `spread_std_ratio` = 1.05 (not below 1.0); only 14.4% (26/181) show meaningful suppression.
    Investigated why: for CAMARF's actual large/mid-cap domestic universe, illiquid days show
    HIGHER variance (1.1x-2.2x), not suppressed — thin holiday trading/halts/data glitches
    produce choppier, not stale, price action. The classic stale-quote effect applies more to
    genuinely thin small-cap/international names, not this universe. **Overturned the original
    hypothesis, documented honestly in Development.md, still built the entry filter anyway (well-
    motivated for a different reason — avoiding noisy/anomalous days, not "spurious
    cointegration").**
- **Entry filter built and wired into `backtest.py`** (`liquid_bar_mask` reused from the
  diagnostic), verified synthetically extending `_verify_dead_constants_comparison_arms.py`.
- **Real A/B Sharpe result (`liquidity_bar_filter` comparison arm, real Purity pairs)**: IS
  Sharpe improves -0.679 → -0.578; **OOS degrades slightly** -0.834 → -0.915. A genuinely mixed
  result, not a clean win.
- Ross's follow-up question (answered by Claude, grounded in what's already built, not starting
  fresh): *"can we try cointegration if we have averaged k means cross time frame + and or lead
  lag?"* — Claude's answer: k-BAHC clustering can only "rescue" candidates in bulk (never
  per-pair) per an already-verified mechanism finding; cross-timeframe cointegration (3 methods)
  is built but not yet run; lead-lag has a well-validated null (Finding #11, positive-control-
  verified search machinery). Recommendation: clustering-first + cross-timeframe is the
  worthwhile combination; lead-lag folds in as secondary diagnostic only.
- Ross: *"let's add a thread for when to run k bahc universe wise. i also like your ideas that you
  said"* — this is the literal origin of **Thread P** in the plan file.
- Thread K Part 2 finished around here: 971,066 (ticker, rdate) institutional-holding rows,
  20,335 distinct tickers with real 13F history.
- k-BAHC launched for real (1h) — background-timeout killed it mid-`DataAligner.align_universe()`
  (~10 min timeout, task needs up to ~90 min per project history) — relaunched detached (PID 1844).
  **This is the run whose "1h reconfirmed, 4h, 1D — fully complete, 0 new candidates" status
  report (already noted in my earlier read of the current conversation) turned out to be against
  the OLD ~1,573/1,730-symbol yfinance-only universe, NOT the WRDS-expanded one** — Ross caught
  this directly (*"your relaunch is NOT redoing already completed work. That was done on an
  older, limited dataset. Any tests done pre today are invalid given the universe expansion and
  must be retested"*), and Claude confirmed it directly: `load_full_universe()` in
  `k_bahc_candidate_discovery.py` only ever scanned `Config.DATA.CACHE_DIR` (old yfinance cache),
  never `output/cache/wrds/`. **This is the exact same root cause the current live conversation
  independently found and fixed today (2026-08-17) — confirms that finding was correct and not
  redundant.**

---

## Section 9 — Thread N sub-arms (#2 leverage cap, #5 VaR calibration), Thread L (event study) — NEW, not in HANDOFF.md

- **Thread L (event-study framework)**: built (`research/event_study_framework.py`), 5/5
  synthetic checks, run for real against a real Purity pair. **Finding #34**: a plausible pattern
  found — z-score dispersion narrows post-earnings-announcement as uncertainty resolves.
- **Thread N #5 (VaR backtest calibration, `var_backtest_calibration.py`)**: built with real
  investigation along the way —
  - Caught a **real Basel-methodology mismatch**: Basel's 4/9 traffic-light thresholds are
    calibrated for 99% VaR (1% expected exceedance), NOT 95% VaR (5% expected) — applying them to
    a 95% VaR result shows "red" even when perfectly calibrated. Fixed both the synthetic test and
    the driver to disclose this rather than mislabel a well-calibrated 95% result as failing.
  - Caught a **real degenerate-data artifact**: baseline/tiered arms' "0 exceptions" (naively
    looking like perfect calibration) was actually meaningless — every single one of the baseline
    arm's 392 "observations" has a **degenerate (zero) VaR estimate** (consistent with Thread M's
    finding that these arms are 81-82% exact-zero-P&L days). Fixed `count_exceptions` to report
    this honestly.
  - **Real, honest positive finding once fixed**: Purity/Hybrid's 99% VaR shows genuine calibration
    close to the 1% target (1.4-1.8% exception rate, yellow/green Basel zones). **Documented as
    Finding #35.**
- **Thread N #2 (leverage/gross exposure cap)**: built (`portfolio_sim.py` + `backtest.py` wiring).
  **Real architectural finding**: `portfolio_sim.py`'s existing capital-availability constraint
  already implicitly caps leverage at 1.0 (positions can never exceed available cash — no
  borrowing mechanism exists) — so `leverage_cap` only has a distinct effect for values BELOW 1.0
  (a tighter constraint); values ≥1.0 are already no-ops given the existing architecture. Test and
  finding updated to reflect this real property rather than treat it as a bug. **Finding #36.**
- Thread I (liquidity filter) was at ~53-70% through its THIRD (finally-working) run during this
  stretch — see Section 6 below for the full incident history of why it needed three attempts.

---

## Section 8 — The "4 dead config constants" investigation + `flat_risk_pct` wiring bug — NEW, not in HANDOFF.md

- **Real, substantial codebase-hygiene finding**: of Thread G-Full Tier 2's 5 parameters that
  showed exactly zero measured effect across their full grid, **4 are genuinely dead config
  constants** — `corr_exit_threshold`, `corr_exit_window`, `max_concentration_pct`, `max_half_life`
  are declared in `config.py`, described in docstrings as if they're active trading-logic
  conditions, but **confirmed via direct codebase grep to be read by NOTHING anywhere in the
  codebase.** `max_concentration_pct` had already been caught once before, in a 2026-07-20 "Tier 6
  doc-drift" session, and evidently never acted on — the other three are the same undiagnosed
  pattern, newly found this session.
- The 5th, `flat_risk_pct`, IS genuinely implemented but was a **real, fixable wiring bug**:
  frozen as a module-level constant (`_FLAT_RISK_PCT`) in `portfolio_sim.py` at import time,
  *before* `backtest.py`'s `--override` mechanism ever runs. **Fixed**: threaded the override
  value through explicitly at all 3 call sites in `replay_portfolio`, verified via a targeted
  synthetic test that monkeypatches price/risk-distance dependencies. Documented in
  `docs/FINDINGS.md` as an update to Finding #31.
- Claude explicitly did NOT unilaterally decide whether to implement the 4 dead constants for real
  or retire them — flagged as "a real fork... needs your sign-off before I build it."
- **Ross's decisive answer, verbatim**: *"instead of deleting the 4 dead config constants can we
  implement for comparison first? test everything discussed and keep working through the list and
  tasks. build the driver. i just want you to keep working through the entire list until there's
  literally nothing more you can possibly do. Any questions?"* — Claude: *"No blocking
  questions... Starting the full list now."* And separately, confirmed again: *"so you're good to
  work on the whole list until i stop you?"* → *"Yes — I'll keep working through the whole list
  autonomously until you tell me to stop, flagging anything genuinely notable as I go."*
- **All 3 backtest-level dead constants implemented as real, opt-in comparison arms** (NOT
  silently defaulted on) and run for real against Purity pairs:
  - `max_half_life_filter` — entry filter mirroring `min_half_life_bars`'s existing convention.
    **Hurts performance.**
  - `real_corr_exit` — correlation-based structural-breakdown exit using the already-available
    `coint_fraction_rolling_t` series. **Found and fixed a real overtrading bug**: naive
    implementation (no hysteresis/debounce) produced **269,707 trades** (vs. 146 baseline) —
    individual pairs racking up 500-1,000+ trades from threshold chattering near the 0.20 cutoff.
    Fixed by applying the SAME `hold_bars > 5` debounce guard the existing `corr_exit` heuristic
    already uses (Claude had omitted it from the new condition). **Also hurts performance** once
    fixed and cleanly re-run.
  - `concentration_cap` — added to `portfolio_sim.py`'s unified replay engine (portfolio-level,
    not per-pair), wired as its own `--capital-sim`-level CLI flag. **Near-null at its default
    value.**
  - All 3 verified against a minimal synthetic harness + a full regression check against existing
    `backtest.py` tests (no regressions). **Documented as Finding #33.**
- **Thread M expanded from 6 to 17 factors** (Ross: *"i like the factors thanks for explaining -
  let's use them and more if available."*) — full literature-grounded explanation of each of the
  original 6 (be_me/market_equity/ret_12_1/ni_be/at_gr1/beta_60m, with alternative-proxy
  discussion for each) given to Ross first, then 11 new characteristics added across a 7th new
  category (Liquidity: `dolvol_126d`, `ami_126d`, `zero_trades_252d`). Re-verified synthetically
  (5/5 unchanged), re-fetched from WRDS, re-ran: **momentum validation held at 0.8005 correlation
  with the trusted Fama-French `umd` factor** (unaffected, as expected).
- **Thread M's real driver run (`jkp_thread_m_driver.py`) — the honest null result already
  documented in `docs/FINDINGS.md` #32 was reached via this path.** Along the way: implausible
  t-stats (up to -67) investigated rather than trusted at face value → traced to baseline/tiered
  arms being 81% exact-zero-return months → added an explicit sparsity guard → **every one of the
  20 regressions across both options came back flagged untrustworthy, which IS the honest finding**
  (not a methodology failure). **4th recurrence this session of the pd.NA truthiness bug class**
  found in `build_portfolio_characteristic_exposure`'s `np.nanmean` call — fixed, then a
  deliberate codebase-wide sweep for the same pattern found no further un-fixed instances.
- Thread I crashed mid-stretch with a real bug: `pd.NA` truthiness ambiguity in
  `international_liquidity_filter.py` (same bug class as above, independently recurring in a
  different file) — fixed, relaunched (**PID 9976** — this is the run that later completed with
  2,930/15,094 international symbols passing, 19.4%).

---

## Section 7 — "Everything to discuss" list + full autonomous-mode confirmation — NEW, not in HANDOFF.md

- Claude proactively surfaced a 5-item "everything to discuss" list once Tier 2 was fully closed
  out: (1) Thread K Part 2 launch sizing/timing, (2) the 4 dead config constants fork (build vs.
  retire), (3) whether `flat_risk_pct` deserves a targeted re-sweep under `flat_2pct` sizing,
  (4) whether to build Thread M's driver now, (5) open invitation for anything else design-wise.
- This is where Ross's decisive "keep working through the entire list... any questions?" message
  (Section 8 above) actually landed as a direct reply.

---

## Section 6 — Thread I (international liquidity filter) — full incident history, NEW/expanded vs. HANDOFF.md

HANDOFF.md's "2026-08-16 update" only captures the LAST relaunch of this job (the pd.NA fix,
PID 9976, eventual 2,930/15,094 result). The real history is **three distinct, separate failure
incidents**, not one:

1. **Genuine multi-hour hang** (earliest incident found in this reconstruction). Ross had started
   the international-liquidity-filter run; after ~6.5+ hours with zero visible output, Ross said
   *"it's probably not working, stop polling until further notice."* Claude complied, stopped
   scheduling checks. Later, Ross asked *"check if it's hung or slower. also give me your
   thoughts on https://github.com/goldmansachs/gs-quant"* — Claude dug in properly (not just file
   existence) and found a **definitive stall, not just slowness**: PID 25132 had accumulated only
   1.46 CPU-seconds total across 8+ hours of wall-clock time (unchanged across every check), and
   the log file it should have been writing to hadn't been touched by it at all (only by Claude's
   own earlier synthetic test, which had clobbered the file). Root cause hypothesis: a raw network
   stall inside `db.raw_sql()` itself, which has no timeout at the psycopg2/driver level — Claude's
   retry wrapper only catches exceptions, never gets a chance against an indefinitely-hanging call.
   **Killed via taskkill, then hardened**: added a real statement-level timeout (`SET
   statement_timeout`) plus connection retry plus a timeout on the yfinance call (the other
   suspected hang point) plus periodic progress logging in the main loop.
   - **This is also the literal origin of the gs-quant research arc** (Section 8's "3 dead config
     constants" work is unrelated — this is the EWMA z-score / vol-swap volatility / spike-
     smoothing comparison-arm work, already summarized accurately in the plan file's master index
     as "DONE — Finding #29" and NOT contradicted by anything found here, just given much richer
     mechanism detail: the EWMA design was corrected BEFORE building to avoid literally repeating
     BUG-D45's known failure mode (decoupling mean/std windows) — built as a fully-coupled EWMA
     z-score instead; real result 0.846 correlation with production z-score, 86.7% entry-signal
     agreement, ~13% genuine divergence not yet explained. The vol-swap estimator gave an honest
     negative result (risk-per-share ~8.6x smaller — wrong direction for the Kelly-sizing problem).
     **BUG-D45 retested at scale** (Ross's direct request: *"the bug d45 is a single case and
     should be retested"*) — found something WORSE than the single-pair case suggested: 96.2% of
     pairs (453/471) fine or better under decoupling, but 3.8% (18 pairs) show catastrophic
     numerical blowups (e.g. BXMT/ECL mean z-score of -88,141). Ross asked directly: *"for the
     blow ups is that an opportunity for arbitrage/shorting maybe?"* — Claude checked rather than
     guessed and confirmed **NO, it's a pure numerical artifact** (the spread didn't move at all
     at the worst bar — change=0.0 — and the std-computation window had only 2 unique values
     across 185 bars, i.e. genuinely degenerate; production z-score at that exact bar was a
     totally unremarkable -0.53). Same underlying mechanism as BUG-D45's original bug, triggered
     by real price degeneracy (likely thin BXMT trading) rather than the original padding bug
     specifically.
   - The master thread-plan index (Thread A through M, later extended to P) was **created for the
     first time** in this same stretch.

2. **Query-shape/timeout stall** (second attempt). Relaunched; stalled again — this time on the
   currency-lookup query: submitting the entire remaining ~15,094-pair batch as one massive
   `IN (...)` clause on every retry, hitting the 120s statement timeout every time with zero pairs
   resolved (not a transient drop — the batch size itself was the problem, since a retry re-sent
   the same first batch rather than a growing one). Root cause dug into properly: the query had no
   lower bound on `datadate`, forcing a near-full scan of `comp_global_daily.g_secd`'s entire
   history per pair. **Timed comparison found all three candidate query shapes hit the same
   ~0.55-0.6s/pair wall regardless of phrasing, while a single-pair equality query ran 5x faster
   (0.11s)** — the table apparently can't use an efficient index for multi-tuple `(gvkey, iid)`
   matching. **Real architectural fix: rewrote to sequential per-pair queries, not batching at
   all.** Rewrote the verification test to match, timed a real 100-pair sample (~79 min
   extrapolated for the full run), relaunched (**PID 19744**).

3. **pd.NA crash** (third attempt, already captured in Section 8 above) → **PID 9976**, this is
   the one that finally completed cleanly (2,930/15,094 = 19.4% international symbols passing the
   liquidity filter).

4. **Real, non-blocking side effect found along the way**: the liquidity-filter module truncates
   its own log file on every import — Claude's synthetic verification test runs had repeatedly
   clobbered the real run's log content, making "check the log" an unreliable progress signal at
   several points in this saga. Flagged as cosmetic, never fixed (not urgent enough).

---

## Section 5 — Non-interactive WRDS connection capability + Ross's full-autonomy grant — NEW, not in HANDOFF.md

- **Real capability unlock, honestly caveated**: Claude found that `wrds.Connection` accepts a
  `wrds_username` constructor kwarg directly, which combined with the `.pgpass` file already set
  up, allows a **fully non-interactive WRDS connection with no Duo 2FA challenge** — tested live,
  confirmed working, wired into `data_wrds.py::_connect()` (both
  `wrds_global_index_universe_fetch.py` and `international_liquidity_filter.py` inherit this
  automatically via their shared `_connect` import). **Explicit, repeated honesty caveat from
  Claude, worth preserving**: *"I genuinely don't know why it succeeded without a 2FA challenge
  this time (most likely Duo's 'remember this device' trust window from your earlier logins
  today, which could expire). I'm not claiming this is a permanent fix, just that it works right
  now."* **If a future session finds WRDS suddenly requiring interactive auth again, this is
  expected/known, not a new regression — check whether the trust window expired.**
- **Ross's full-autonomy grant, verbatim**: *"Now that you have access you run everything yourself
  and monitor this, and all the other tasks. If you encounter questions, work on the next task
  available and when i see your question ill answer it, remind me about the question though."*
  — this is the actual origin of the extended autonomous-work mode that carried through most of
  the rest of the session. **Ross explicitly asked to be reminded of any pending open questions
  when he returns** — worth checking whether any were left dangling and never actually re-surfaced
  before the crash (not confirmed either way in this reconstruction; would need a further check
  against every "Open question for you" moment found across this log to see which ones Ross
  actually answered vs. which are still hanging).
- **Cross-thread dependency discipline, Ross's instruction**: *"if any threads require info from
  other threads hold off on running them until the threads are completed."* Claude responded with
  a real dependency audit (not assumed): Thread J Test 1 → depends on Thread I (correctly held);
  Thread K Part 2 → conceptually bundled with Part 1 (not yet started at that point, held); Thread
  J follow-up (regime-strength vs. PIT-precision) → no real dependency, proceeded; Thread M →
  standalone, proceeded; Thread O → explicitly gated by Ross on Thread I completing (held); Thread
  G-Full Tier 2, Thread L, Thread N → all independent, proceeded.
- **Thread J follow-up (regime-strength vs. Finding #23's PIT-precision) — built, verified, run
  for real.** Genuinely counter-intuitive real finding: pairs confirmed during a "strong" early
  regime show LOWER forward precision (0.304, n=23) than those confirmed during a "weak" regime
  (0.75, n=4) — the opposite of naive expectation. Small samples (23/4/1) explicitly flagged as a
  real caveat — interpreted as a plausible "winner's curse" effect (the most extreme-looking early
  discovery-sample signal tends to regress toward noise out-of-sample, a well-known statistical
  phenomenon). **Documented, but I did not find a Finding-number citation for this in this
  reconstruction — check `docs/FINDINGS.md` directly for whether this landed as its own numbered
  finding or only in Development.md.**
- Live WRDS table verification (once non-interactive access was confirmed) found:
  - `etfg_samp.constituents` and `mrktsamp_cds.cds2011` are **real dead ends** for Thread K/M as
    originally scoped — `etfg_samp` covers only November 2021 (11 ETFs total), `mrktsamp_cds` is
    literally a single day (2011-03-21). Neither is remotely sufficient.
  - `tr_13f.s34` (13F institutional holdings, SEC-regulated, not a sample subscription) — **127
    million rows, 1980-2025** — confirmed as the genuinely viable path for Thread K's fund-
    membership question. This became Thread K Part 2's real data source.
  - `contrib_global_factor.global_factor` — confirmed genuinely comprehensive (1925-2025, 444
    columns), became Thread M's real data source.
- Thread G-Full's Tier 2 sweep launched for real in this stretch: **PID 19736**, 12 parameters ×
  grids × IS/OOS, expected several hours (already known to have completed — Finding #31, already
  referenced in the plan file).

---

## Section 4 — Thread K Part 1 (full US market fetch) — NEW/expanded vs. HANDOFF.md

- **Origin, Ross verbatim**: *"let's make sure we also get the entire US market and all what
  assets we're when and where at what time"* — this is Thread K Part 1's real origin message.
- Real numbers: CRSP's full historical common-stock universe (active + delisted, major exchanges)
  = **29,366 distinct securities, 1925-2024** — about 16x the then-current ~1,700-symbol universe.
  Point-in-time security-master metadata (`crsp_a_stock.stocknames`) fetched first, cheaply:
  **63,388 spell-rows** (permno, exchange, ticker, validity date range), seconds to fetch.
- Real price-fetch cost sized BEFORE committing: a 200-symbol timed batch took 18s (0.09s/symbol);
  extrapolated to **~44 minutes for the full 29,366-symbol fetch** — a completely different order
  of magnitude than the international fetch (which was slow due to the currency-lookup query
  pattern specifically, not bulk price fetching itself).
- **Two real bugs found and fixed via direct sanity-checks on the live run, not assumed correct**:
  1. Some CRSP tickers are genuinely `None`/NULL in the data (not missing dict keys) —
     `dict.get(key, default)` only falls back on absent keys, not `None` values. Fixed.
  2. A subtler, second-order bug: after fixing #1, inconsistent results appeared between isolated
     tests and the real run — traced to `pd.NA` vs `None` vs `np.nan` behaving inconsistently
     across pandas dtype round-trips. Fixed by switching to a strictly type-based check that
     sidesteps the ambiguity entirely, then added a specific `pd.NA` regression test.
- **Real, final number**: 6,731 permnos (23% of the 29,366-symbol universe) needed the
  `PERMNO<n>` collision-fallback label due to genuine ticker reuse across different companies over
  a century — confirming this was a real risk to guard against, not overblown.
- Ross's follow-up, verbatim, shaping Thread K Part 2's eventual design: *"let's also make sure if
  it's in a fund we get it listed what when where and how long"* — a point-in-time,
  spell-based fund-holding history design (mirroring the same convention already used for S&P 500
  membership, Compustat Global membership, and now the CRSP security master itself).

---

## Section 3 — Thread G Phase 2 completion (Finding #27) — NEW, not in HANDOFF.md, potentially significant unaddressed recommendation

**This is the earliest point reached in this reconstruction and may be the single most
consequential item not already surfaced anywhere in `docs/HANDOFF.md`.**

- **Finding #27, full real result**: Thread G Phase 2's interaction study (entry_z × hedge method,
  a full factorial, not just marginal OAT picks) found a **genuine interaction** — the best hedge
  method flips depending on entry_z, on both IS and OOS. Concretely, at `entry_z=3.0`:
  - `hedge=kalman`: IS Sharpe +0.159 (best in the entire grid), but **OOS Sharpe -0.748 (worst of
    the 3 hedge methods at that entry_z)** — a real overfitting trap the full factorial catches
    that the OAT screen alone could not.
  - `hedge=both` (the current production default): IS Sharpe +0.146, **OOS Sharpe -0.179 (best in
    the entire grid)**.
  - If hedge method had been picked by IS Sharpe alone (the naive approach), you'd have grabbed
    Kalman and walked straight into the worst OOS outcome at that entry level.
- **Synthesized recommendation, across Phase 1 + Phase 2 + the Kelly/z-band investigation**: the
  one change with consistent, multi-angle evidence behind it is **raising `ENTRY_ZSCORE` from 2.0
  to 3.0**, leaving hedge method at its current default (`both`, not switching to OLS as the
  marginal-only view would suggest). Described as "the strongest lever found, best OOS cell in the
  entire study, and every angle (OAT screen, full factorial, the entry-overflow diagnosis) points
  the same direction."
- **Explicit, important honesty caveat Claude gave alongside the recommendation**: *"I want to be
  direct about what this isn't: OOS Sharpe is still -0.179, not positive. This is 'least bad of
  everything tested,' not 'the PIT-safe universe is now profitable.' Kelly/risk-based sizing stays
  unusable regardless (risk-per-share too small vs. account size) — that's the honest state of the
  182-pair universe."*
- **Claude explicitly did NOT promote `ENTRY_ZSCORE=3.0` to the production default unilaterally**:
  *"Promoting `entry_z=3.0` as the new production default is a real, defensible candidate given
  this evidence — your call, not done automatically."* **This reconstruction found no later
  message where Ross actually made this call, and `config.py`'s current `ENTRY_ZSCORE` value was
  not checked as part of this fork's task — worth checking directly whether this got applied or
  is still an open decision.**
- **Kelly-sizing root cause, Finding #26** (referenced but not fully detailed in what I read):
  built a real `--entry-z-max` comparison arm, verified it actually filters trades before trusting
  results, and found the entry-overflow gap (56%+ of entries already exceed the stop z-... [cut
  off in the captured text]) is real but **NOT the dominant blocker** — the tiny risk-per-share vs.
  oversized-position mismatch is the actual dominant cause. Full detail in `docs/FINDINGS.md` #26.
- **Confirmed directly from code, at this point in the session**: WRDS had at that point ONLY been
  wired as a **data-source swap** for the existing ~1,660-1,730-symbol universe (`data_wrds.py`'s
  `get_universe_us_equity_etf_symbols()` literally reuses `UniverseBuilder`'s existing S&P
  1500+ETF constituent list and just filters it to what CRSP covers — it does not discover or add
  any new tickers; CRSP itself is US-only by design). *"So: WRDS changed where the OHLC data comes
  from for the same ~1,660-1,730-symbol universe (cleaner, longer, total-return-adjusted history)
  — it never touched how many tickers are tracked."* The international/ADR/FX-spot symbols already
  in the universe at that point were the full extent of non-US coverage; **the entire WRDS-driven
  universe EXPANSION arc (Thread I, Thread K, the 44,840-symbol full-universe cascade, Thread J
  Test 1, k-BAHC rewiring) all happens chronologically AFTER this point** in the session.

---

## What's genuinely new vs. `docs/HANDOFF.md` — summary

See the fork's final report message for the condensed, prioritized version of this list.
