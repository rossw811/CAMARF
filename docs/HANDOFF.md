# CAMARF Handoff — Reconstructed from an Interrupted Session, 2026-07-27/28

---

**2026-08-02 update — reconstructed from the live browser session, machine rebooting for Windows
Update.** This local Claude Code session has no prior work of its own to hand off — it was opened
specifically to capture the state of a **separate, still-open browser tab**
(`claude.ai/code/session_01VjNx54nhUFHzb9KncV8ZeW`, titled "Verify Phase A causality bug fixes with
real data") before this machine restarts for a pending Windows Update. That browser session is
**not itself blocked by the reboot** — it had already stalled on its own, hitting Claude's usage
limit while idling in a `Monitor`-wait loop for the background `data.py` run, several exchanges
*after* it wrote the "2026-08-01 update" block immediately below (which is the same session's own
end-of-Phase-A write-up — trust that block's content, it's this session's own accurate summary of
its own work, not a stale prior-session note). The reboot just means don't count on that tab still
being live/resumable from this machine afterward; nothing computationally is lost, since nothing was
still running locally (checked via `tasklist` — no python processes active) and the browser session
itself is server-side and tied to the Claude account, not this machine.

**What actually changed since that "2026-08-01 update" block was written, verified against the repo
just now, not the transcript:**

- **The full `data.py` production run it launched (Task 16) has now actually finished** —
  `latest_run_data.log` shows `runtime_min: 125.9`, completed `2026-08-02 00:13`, 1357/1694 symbols
  resumed, all 8 intraday timeframes saved cleanly (1m/2m/3m fetch-failure rates in the normal range).
  The log's `phase1_daily` section is empty (no per-symbol WRDS-vs-yfinance counts logged there) —
  worth checking whether that's just a logging gap in the new WRDS branch or a sign the daily/coarser
  phase didn't do what was expected; don't assume either way without reading `data.py`'s WRDS-read
  branch logging calls directly.
- **`analysis.py` has NOT been re-run since.** `latest_run_analysis.log` is still the *2m/3m-scoped*
  verification run from Phase A (`date: 2026-08-01 17:10`, same KVUE/KMB pair set as always) — it
  predates the full `data.py` run above and says nothing about WRDS-sourced daily data. **The actual
  point of Task 16 (an honest yfinance-vs-WRDS-primary comparison) has not happened yet** — the
  browser session died in its wait loop before it could run analysis.py against the fresh data. This
  is the single most concrete next step: run `analysis.py` (full universe, or at least 1D/7D/1M/3M/6M)
  against the just-completed cache and see what actually changed.
- **A separate line of discussion from Ross, raised mid-session and explicitly deferred, is still
  open and undocumented anywhere else:** whether to build comparison arms for jump-diffusion (Lévy
  processes) and rough volatility (tied to the existing GARCH vol-regime work), wavelet
  convergence/divergence (already scoped in `dedicated_pass.md`), options Greeks as correlation/
  convergence features (`options.py` already exists, Session 27), an SVM-via-gradient-descent
  alternate classifier for `ml.py`'s meta-labeler, cross-asset/cross-timeframe cycle detection in
  `ml.py` (Fourier/Hilbert/wavelet-based), and evaluating
  `github.com/paperswithbacktest/awesome-systematic-trading` for reusable pieces (verdict already
  given in-session: skip `pyfolio`/`tf-quant-finance`/`FinancePy` as unmaintained or too heavy for
  this machine's x86-emulated-ARM64 setup; skip scraper-based ticker sources like Investpy in favor of
  the already-larger WRDS/Compustat Global universe). Ross's own instruction was to finish the
  current WRDS plan first and discuss this list after — it was never brought back up before the
  session stalled. Surface this list to Ross before building any of it, per CLAUDE.md's new-
  methodology buy-in rule.
- Ross also gave a standing-instruction correction mid-session, already worth carrying forward
  explicitly: *"you don't need me to tell you to keep going. if there's a task to be done let's get
  it done. if there's questions move on to the next task until the questions are at the end of the
  task list."* Apply this going forward — don't pause on a completed step waiting for a "continue."

**Immediate next step, in order:** (1) run `analysis.py` against the completed `data.py` output to
get the real WRDS-vs-yfinance comparison Task 16 was for; (2) resume the browser session once its
usage limit resets (it was mid-way through Phase B/C — WRDS data-quality fixes B1 deferred on Ross's
VPN, Phase C wiring done) — or if it's not resumable, treat this document plus the "2026-08-01
update" block below as the reconstruction and continue in a fresh session; (3) only then raise the
deferred research-topics list above with Ross.

---

**2026-08-01 update (Session 29, see Development.md)**: all 5 causality-audit findings described below
are now **fixed and verified** (synthetic tests + real-pipeline runs, including a real-data check that
each synthetic test correctly fails against git-stashed pre-fix code) — BUG-D99 through BUG-D103, see
`docs/BUG_LOG.md`. Section "Exact current state of the 5 causality-audit findings" below is now stale
(kept for historical record of what was found, not current status). WRDS was also wired as primary for
daily-and-coarser (1D/7D/1M/3M/6M) CRSP-resolvable US equities/ETFs in `data.py` (BUG-D104 found + fixed
along the way — CRSP's native monthly file has no OHLC). International (`equity_intl`) stays on
yfinance — not solved this session. B1 (CRSP volume share-count adjustment) remains **open**, deferred
pending Ross's WRDS VPN access (no live-query capability in that session's environment). A full
production `data.py`→`analysis.py` run comparing WRDS-primary against the yfinance-only baseline was
launched at the end of that session — see `latest_run_data.log`/`latest_run_analysis.log` for the actual
result, not assumed here.

---

**Superseded document notice**: everything below replaces the previous version of this file (written
2026-07-20, "pair-set collapse" handoff). That version's core finding (yfinance-production confirmed-pair
set collapsed to near-zero after removing DD-cache contamination) is **still true and still unresolved**
— see "Carried forward, unchanged" below — but a large amount of separate WRDS-based work has landed
since, and the session that did it **never finished and was never written up**. Read this file, not
memory of the old one, and not Development.md's own "Current State"/session-log tail, which stops before
half of what's described here.

**How this document was produced**: the originating Claude Code session (`session_019rPiyBj5SDCqQdGKYiVppb`,
titled "Resume script sweep and novel research discussion") hit sustained usage-limit errors and was left
**archived mid-task** — Ross's last message ("continue as you were") got no response before the session
was archived. This document was reconstructed by reading that session's transcript directly in the browser
(the session cannot be resumed from Claude Code's own history) and then **cross-checked against actual repo
state** (file mtimes, git log, log files, grep of current code) rather than trusted at face value — several
things the transcript describes as "in progress" turned out, on inspection, to still be unstarted in the
actual files. Where the transcript and the repo disagree, this document reports the repo.

**Read `CLAUDE.md` first, in full**, before touching anything — this handoff assumes you've read it,
especially the "START HERE" directive and the point-in-time/causal-correctness sweep it already calls for.

---

## The single most important thing to know before doing anything else

Two unresolved threads are now live simultaneously, and they interact:

**1. Carried forward, unchanged: the yfinance-production confirmed-pair set is still ~2 pairs.**
As of the last full `analysis.py` capstone rerun (2026-07-22, documented in Development.md), the
production pipeline's confirmed set is **KVUE/KMB @2m and @3m only** — the historic 26-pair/Sharpe-5+
headline numbers still sitting in PAPER.md's Abstract do not reflect current reality. This was not
touched by the session described below. PAPER.md has still not been reconciled (see
`docs/PAPER_PENDING_CHANGES.md` entry #7).

**2. New: a separate WRDS/Compustat-based deep-history scan just found a much larger, more promising
pair set — but it is unintegrated, undocumented, and not yet checked for the exact causality bug the
project has been explicitly worried about.** `research/wrds_deep_history_episodic_scan.py`'s Tier 1/2/3
run against a 5,846-symbol WRDS universe (CRSP + newly-added Compustat Global international equities)
completed successfully on 2026-07-28 at 18:52, after a ~23-hour runtime:

```
Tier 1 (full-sample, static corr):        103 / 220,493 pairs confirmed
Tier 2 (rolling EG, static corr):         189 / 220,493 pairs episodic-confirmed (missed entirely by Tier 1)
Tier 3 (rolling EG, rolling corr/ADV):    620 / 1,089,763 pairs episodic-confirmed
```
Output: `output/research/wrds_deep_history_episodic_scan_tier{1,2,3}_*.parquet`.

This is a **completely different order of magnitude** from the yfinance production set, on cleaner/deeper
data. It is also **not yet trustworthy for anything beyond "interesting, investigate further"**, for
reasons that were found mid-session and never resolved:

- The scan's own design asks "was this pair EVER confirmed in any historical rolling window," computed
  in one pass over the whole dataset — not "as of date T, using only windows that had already concluded
  by T." Ross's own words when this was raised: *"if we're not being aware of episodic cointegration
  then our entire model is induced to a brutal bias that falsifies our data... for rolling windows it
  must always be rolling up to that point."* Nothing consumes this WRDS output downstream yet (confirmed
  via repo-wide grep — see below), so there's no live bug today, but **the moment anything reads these
  parquet files into a backtest or live decision without an `.asof(T)`-style causal filter, that bug goes
  live.** `episodic_bhfdr_confirm`'s aggregation (in both this script and the new lead-lag scan) currently
  discards the actual per-window calendar dates when it collapses to a summary row — a future retrofit is
  not a simple patch, the date information needed doesn't survive into the final file.
- A 4-agent causality/point-in-time audit was dispatched the same evening to check the rest of the
  pipeline for the same bug class. It found **5 real, unfixed issues in backtest.py/ml.py/pit_wfa.py/
  wfa.py/macro.py** (full list below) — one of which (a live position-sizing circularity) is severe
  enough that Ross explicitly told Claude to fix it directly rather than just building a comparison arm.
  **That fix was started and never finished** — see next section.

**Do not treat the WRDS Tier 1/2/3 pair counts as a new headline result.** They're a real, promising signal
worth pursuing, but need the causality audit's findings resolved first, plus the same PAPER.md-caliber
verification rigor as anything else in this project.

---

## What actually happened in the interrupted session (chronological, 2026-07-27 evening → 2026-07-28)

Everything in this section happened **after** Development.md's last written entry ("International
expansion: bulk fetch built, run, and completed," 2026-07-27) and is **not yet in Development.md at all**.
Writing it up there is itself one of the open tasks below.

1. **Real Tier 1/2/3 episodic scan launched** on the full expanded universe (5,846 symbols: 2,843
   CRSP total-return-adjusted + 3,003 Compustat Global split-only-adjusted, including the ~2,974
   international symbols from the just-completed bulk fetch), with the rolling $25M ADV liquidity gate
   active on Tiers 2/3. Ran ~23 hours in the background, completed cleanly, see counts above.

2. **`research/wrds_universal_lead_lag_scan.py` built** — a new pair-*discovery* methodology (not just
   confirmation), because an exact pairwise lagged-correlation scan is infeasible at the full universe's
   ~16.6M candidate pairs. 4-stage design: Stage 0 (cheap/approximate, vectorized BLAS matmul screen,
   all pairs) → Stage 1 (cheap/exact recheck of Stage 0 survivors, not yet run) → Stage 2 (expensive EG
   confirm, not yet run) → Stage 3 (joint BH-FDR, not yet run). Verified synthetically (5/5 groups,
   including an adversarial partial-overlap stress test) before running on real data.
   - Real-data results: `research/cross_listing_lead_lag.py` companion test found 34/36 same-company
     multi-exchange pairs are pure lag-0 parity (expected — arbitrage keeps them tight), 1 genuine
     candidate (gvkey=101017, lag=-1, corr lifts 0.364→0.478).
   - Stage 0 ran count-only on the real 5,762-symbol/16,597,441-pair universe: 13.9 min for all 21 lags,
     **435,549 pairs (2.6%) survive** the approximate ≥0.15 correlation floor at a non-zero lag. Stage
     1-3 were deliberately **not launched** — Stage 1 is currently a serial loop (not yet parallelized
     like Stage 2), and launching it was held pending the causality-audit triage below. Output:
     `output/research/wrds_universal_lead_lag_stage0_full.parquet` (306MB, Stage 0 survivors only —
     these are NOT EG-confirmed pairs, just correlation-screen survivors).
   - An **episodic mode** was added to the same script (rolling-window variant, same convention as
     Tier 2/3), verified synthetically (6/6 checks, including proof it recovers a regime-confined
     lead-lag relationship a whole-sample scan would dilute below detection) — **never run on real data**.

3. **Causality/point-in-time audit** (Ross's "brutal bias" message above triggered this) — 4 agents
   dispatched **in parallel** (this predates the "1 agent at a time" rule stated later the same
   conversation — see Working Style note below). Findings:
   - **Production core** (`analysis.py`/`data.py`): clean. Full-sample tests already disclosed via
     `BiasAuditLog` and quantified in PAPER.md §7.3.1.
   - **`backtest.py`/`ml.py`/`macro.py`/`pit_wfa.py`/`wfa.py`** — 5 real findings, **none fixed yet**
     (verified directly against current code, see next section for exact status of each):
     1. `pit_wfa.py`'s point-in-time override (from BUG-D69) never included `hurst_rs` — same bug class
        already fixed for 3 other fields, still missing for this one.
     2. **Live position-sizing circularity**: `coint_fraction_rolling`, `half_life_trend_slope`,
        `mean_reversion_speed`, `hurst_rs` are each a single whole-history scalar (no point-in-time
        series exists) that directly scales position size under `--storm-coint-frac`/`--storm-all` in
        `backtest.py`, and feeds `ml.py`'s training features on every entry across a pair's full
        history. A window ending in 2024 has always been allowed to justify a trade in 2015. This is a
        BUG-D76-class issue the earlier fix never covered (BUG-D76 only addressed the risk-parity/HRP/
        pnl_cap sizing paths).
     3. `garch_stop`'s "is current vol elevated" check in `wfa.py` uses a full-sample denominator, not a
        causal one — same mechanism as the already-fixed BUG-D89, not applied here.
     4. The `coint_frac_sizing` WFA variant sizes a fold's test-window trades using data from *other*
        folds — undermines the point of walk-forward validation for that variant specifically.
     5. `macro.py`'s monthly FRED series are date-stamped to reference period, not publication date
        (~5-6 week real-world lag unaccounted for). Currently dormant — nothing consumes it live — but
        will silently activate the moment macro features get wired into `RegimeConditioner`.
   - **New WRDS scripts**: clean on the "is anything downstream consuming this non-causally" question
     (confirmed via repo-wide grep: nothing does, yet). The `episodic_bhfdr_confirm` date-discarding
     design gap (described above) was the one real finding.
   - **`research/` directory** (~79 scripts): audit **never completed** — the dispatched agent hit the
     session's own API usage limit mid-task, twice.

4. **Ross's standing-rule correction, mid-session**: *"for the future, only 1 agent at a time, as per
   our standing rule."* `feedback_working_style.md` (this project's Claude memory file) was updated with
   this rule immediately. **Apply it going forward** — the 4-parallel-agent audit above predates the
   correction and should not be repeated as a pattern.

5. Ross's follow-up instruction: *"fix the circularity and finish the research/ directory audit. Also
   let's make sure the new WRDS data is integrated and actually being used in the pipeline now. after
   the fixes and changes run the rest of the pipeline and research scripts accordingly."* Claude began
   fixing the circularity (finding #2 above) **directly** rather than scoping it as a comparison arm
   first, per Ross's explicit instruction that this specific item warranted a direct fix. Work done:
   read how `coint_fraction_rolling` is consumed downstream, then built
   `CointScanner.expanding_coint_fraction()` in `analysis.py` (added 2026-07-28, per the file's own
   docstring and mtime) — a causal, point-in-time-safe per-bar expanding-fraction series, using the same
   forward-fill convention as the already-causal `rolling_half_life`.

6. **The session then hit a sustained run of "Usage limit reached" errors** (dozens, back to back), the
   background progress-monitor was stopped, and Ross's final message in the thread — *"continue as you
   were"* — received no response. The session shows as **archived** with no way to resume it from
   within Claude Code.

---

## Exact current state of the 5 causality-audit findings — verified against the repo just now, not assumed

**None of the 5 findings from step 3 above are fixed.** Specifically:

- **Finding #2 (circularity) is half-built, not fixed.** `CointScanner.expanding_coint_fraction()` exists
  in `analysis.py` and is a legitimate causal replacement (per-bar expanding fraction instead of a single
  whole-history scalar) — but it is **called from nowhere** (`grep -rn "expanding_coint_fraction"` across
  the whole repo returns only its own definition). `backtest.py` (last modified 2026-07-21, i.e.
  **before** this audit even happened) still reads the plain circular scalar at lines 544/597-599/696-698,
  unchanged. `ml.py` and `pit_wfa.py` are the same. **The orphaned function needs to actually be wired
  into `rolling_fraction()`'s output path and consumed by `backtest.py`/`ml.py`/`pit_wfa.py` in place of
  the scalar** — this is the concrete next step, not a re-investigation.
- **Findings #1, #3, #4, #5 (hurst_rs pit_wfa gap, garch_stop full-sample baseline, coint_frac_sizing
  cross-fold leakage, macro.py publication-lag)**: no code changes found anywhere related to any of
  these. All 4 are exactly as the audit described them — genuinely still open, not addressed.

**Also not done, despite being explicitly requested**: the `research/` directory audit was never
finished; the new WRDS data (Tier 1/2/3 output, the universal lead-lag Stage 0 output) is not wired into
the production pipeline anywhere (confirmed via grep — nothing outside the `research/` scripts themselves
reads `output/research/wrds_*` files); "run the rest of the pipeline and research scripts" never happened.

---

## Concrete next steps, roughly in the order Ross asked for them

1. **Fix the circularity for real.** Wire `expanding_coint_fraction()`'s per-bar series into
   `rolling_fraction()` so `PairResult` carries a point-in-time series (or a name-distinguished field)
   alongside/instead of the scalar, then update `backtest.py` (lines ~544, 597-599, 696-698) and `ml.py`
   (lines ~292-298, the `FeatureRow` construction) to look up the causal value at each trade's actual
   entry date rather than the pair-wide scalar. Follow the same pattern already used for
   `hedge_ratio_ols_t`/`hedge_ratio_kalman_t` (point-in-time series in the spread_series parquet, scalar
   fallback for pre-fix files) — this project has already solved this exact shape of problem once.
2. **Fix findings #1, #3, #4, #5** — each is narrowly scoped (see descriptions above); none looked like
   they need new architecture, just applying the causal-override pattern already established elsewhere
   in the same files.
3. **Finish the `research/` directory causality audit** — one agent at a time, per the corrected rule.
   Prioritize scripts with rolling/regime/episodic logic in their name or content first.
4. **Decide how (or whether) to integrate the WRDS Tier 1/2/3 and lead-lag output into the production
   pipeline** — this is a real methodological decision (new data source, different adjustment
   convention, needs the point-in-time retrofit discussed above before any backtest touches it), not a
   mechanical wiring task. Surface it to Ross before building, per CLAUDE.md's Working Style section on
   new-methodology buy-in.
5. **Write up everything in this document into Development.md** as a proper session entry (or two:
   2026-07-27 evening and 2026-07-28) — this handoff exists because that write-up never happened;
   don't let this doc become the permanent record instead of Development.md.
6. Only after 1-3 are actually fixed: launch Stage 1-3 of the universal lead-lag scan (Stage 1 needs
   parallelizing first — it's currently a serial loop over 435,549 survivors) and the lead-lag episodic
   mode on real data.
7. Separately, unresolved from the prior handoff: **the yfinance-production pair-set decision** (does
   PAPER.md report the near-zero KVUE/KMB-only reality, keep looking for a defensible way to use the 2-3
   pairs that survive, or something else) is still open and still blocks Phase 13 of the PAPER.md
   reconciliation plan. The WRDS work above does not resolve this — it's a separate, cleaner dataset,
   not a fix to the yfinance pipeline's own collapse.

---

## Standing conventions this project has already established — don't relitigate these

- **Only 1 agent at a time** (restated explicitly this session, now recorded in `feedback_working_style.md`
  — read it).
- Scope non-trivial improvements as a comparison arm first, discuss, then decide on production — except
  when Ross explicitly says to fix something directly (as with the circularity above), which is an
  exception to the default, not a new default.
- Before launching any new heavy computation, check for the bugs/biases already being discussed —
  point-in-time data correctness specifically got called out by name this session.
- Run everything via `C:\Users\RossW\anaconda3\envs\trading\python.exe`, never bare `python`.
- WRDS data (`output/cache/wrds/`) must stay local-only — the subscription's non-commercial license
  prohibits distributing it off-machine. No cloud sync/git for that directory specifically (it's already
  under the fully-gitignored `output/`, verified).
- If a script might crash on a long run, add checkpointing so a restart resumes instead of redoing work
  — this was requested explicitly this session (*"if the scripts crash i don't want to have to restart.
  save progress"*) and applied to `wrds_deep_history_episodic_scan.py`; apply the same discipline to any
  new long-running script (the universal lead-lag scan's Stage 1-3, when built, will need it too).
- PAPER.md/README.md changes are drafted into `docs/PAPER_PENDING_CHANGES.md` only, never applied
  directly.
- Every new research script gets a synthetic `debug/_verify_*.py` test with known ground truth before
  being trusted on real data — followed correctly for every script mentioned in this document.
- Never commit without being explicitly asked. (As of this writing, `git status` is clean — everything
  described in this document through `research/wrds_universal_lead_lag_scan.py`/`analysis.py`'s
  `expanding_coint_fraction` addition is already committed, in the "7/31" commit `25c78303`. Nothing is
  sitting uncommitted from this session.)
- New methodology (not bug fixes) goes through Ross for explicit buy-in before being built — applies
  directly to the "integrate WRDS data into the pipeline" open item above.

## Using Graphify

`graphify-out/` exists but predates this session's file changes. Run `graphify update .` (AST-only, no
LLM/API cost) before relying on it for navigation.
