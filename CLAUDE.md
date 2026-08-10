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

8. **Document what was tried, not just what was kept (added 2026-07-10).**
   When an approach is built, verified, and then reverted or discarded,
   write up the FULL attempt in Development.md — what was built, how it was
   verified, what the real (not hypothesized) failure mode was, and why it
   was reverted — not just a one-line "tried X, didn't work." A negative
   result with a well-understood mechanism is exactly as valuable as a
   positive one, and cheap to re-derive wrongly if a future session doesn't
   know it was already tried. See the Kalman slope+intercept promotion
   entry (Session 27 addendum, 2026-07-10) as the template: what was built,
   the verification chain (synthetic → full pipeline → 3-way comparison),
   the actual root-caused mechanism (not a guess), and why it was reverted.
   This applies to reverted code changes, abandoned research directions,
   and rejected hypotheses alike — not just production changes.

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

- **Universe snapshot (SUPERSEDED — kept for provenance; see the current snapshot immediately
  below):** 1,608 candidate symbols (S&P Composite 1500 + international equities/ADRs/FX spots),
  `data.py` run completed **2026-06-30 10:10**, runtime 5.6 minutes, config_hash
  `0c0e67a6b00ff0bb`. 1,357 symbols resumed from existing cache; 0 excluded; 0
  cache-contamination clears this run.
- **Current canonical universe snapshot (2026-08-03 09:57, post-BUG-D105 fix, WRDS-primary):**
  1,730 symbols with cached daily data, **1,660 assets passed the full screening funnel**
  (`latest_run_analysis.log`, 54.3 min runtime). **WRDS is now wired as primary** for
  daily-and-coarser (1D/7D/1M/3M/6M) CRSP-resolvable US equities/ETFs — CRSP
  total-return-adjusted where available, Compustat Global split-only-adjusted as disclosed
  fallback, via Baruch's WRDS subscription. International equities and everything intraday
  remain yfinance-sourced (fetch windows below unchanged for those). **Confirmed pairs under
  this snapshot: 3** — `KVUE/KMB`@3m, `PNC/ZION`@4h, `IQV/Q`@1D — a real, large reduction from
  the 23/26-pair pre-WRDS sets; see `PAPER.md` §3 for the full honest accounting of why (WRDS
  changes the underlying daily-and-coarser price series for a large fraction of the universe,
  not just adds coverage). An independent party reproducing the pre-WRDS snapshot above still
  can, exactly as described; reproducing the current snapshot additionally requires WRDS/CRSP
  access, which this repo's `output/cache/wrds/` reflects but does not itself distribute.
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
- **Research is decoupled from PAPER.md inclusion (added 2026-07-13,
  after the first LLM-council review).** Keep researching everything —
  new comparison arms, new diagnostics, new statistical checks are all
  worth building and verifying. But every new finding writes to
  `docs/FINDINGS.md` (or stays in Development.md if not yet at
  write-up quality) BY DEFAULT. Promotion into PAPER.md's own headline
  claims is a separate, deliberate decision, not automatic — the same
  comparison-arm-before-production discipline this project already
  applies to code now applies one level up: comparison-arm →
  FINDINGS.md → PAPER.md, not comparison-arm → PAPER.md directly. This
  exists specifically to resolve a real tension the council review
  found: the research itself is valuable and shouldn't be throttled, but
  PAPER.md's own length/legibility was independently flagged by multiple
  reviewers as undermining its purpose as an MFE portfolio piece. The
  strategy/research and the paper are explicitly allowed to diverge in
  scope — the paper does not need to contain everything the research
  produced.
- **Refined 2026-07-13, same day**: this isn't strictly "one paper, one
  dumping ground." Ross's own framing — multiple papers are fine; one
  MAIN paper should carry the most novel and important findings; all
  research is valuable and if a finding can be used in a genuinely
  significant way, it should be, not held back reflexively; and
  regardless of whether a given finding is "significant" enough for any
  paper, keep diving into the actual questions a result raises — its
  inferences, interactions, and the underlying market-structure/
  dynamics mechanism behind it, not just the statistical result in
  isolation. Concretely: don't be stingy about promoting a strong
  finding into PAPER.md just because the default is FINDINGS.md: promote
  it if it's genuinely novel/important. Don't assume a finding that
  doesn't make the main paper is done being explored — a null/negative
  or secondary result can still deserve real mechanism investigation
  (this is what Phase 12's STORM research and Phase 15's market-
  structure depth pass are for), and a strong-enough cluster of related
  findings that doesn't fit the main paper's focus is a candidate for
  its OWN paper, not a reason to suppress it.
- **Use `latest_run_data.log` / `latest_run_analysis.log`** — these are
  structured, LLM-readable run summaries written automatically after every
  `data.py` / `analysis.py` run. Ask for these directly instead of raw
  console scrollback.
- **Honesty over agreeableness — no fear in pushing back (added
  2026-07-13).** Ross explicitly wants to be told when he's wrong, not
  agreed with by default. If a direction he's proposing has a real problem
  — a methodological flaw, a result that doesn't hold up, a plan that's
  going to waste effort — say so plainly and explain why, the same way
  this project's own §9 AI-disclosure standard already demands for
  results ("AI output is not privileged relative to any other unverified
  claim"). This applies to Ross's own proposals and decisions too, not
  just to code or numbers. Silence or reflexive agreement when something
  is actually wrong is a failure mode to avoid, not politeness.

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
- **`verify-new-module` / `diagnose-run-log`** (built 2026-07-13) —
  CAMARF-specific skills under `.claude/skills/`, packaging the
  verify-before-trusting workflow and structured-log-diagnosis pattern
  respectively. See each `SKILL.md` for the exact sequence.
- **`council-*` subagents** (`.claude/agents/council-quant-pm.md`,
  `council-academic-reviewer.md`, `council-code-quality.md`,
  `council-process-meta.md`, `council-mfe-portfolio.md`, built
  2026-07-13) — a 5-lens blind review panel. Run all 5 together at real
  project milestones (not every session) — each is a fresh, non-fork
  agent with zero visibility into the others' findings or into this
  session's own running narration, by design. The first run
  (2026-07-13) found 2 real bugs (a recurred manifest-contamination
  incident, a README/PAPER.md p-value swap) and a converged, independent
  finding across all 5 reviewers about the project's own scope/
  convergence pattern — see Development.md for the full synthesis.
- **`adversarial-reviewer` subagent** (`.claude/agents/
  adversarial-reviewer.md`, built 2026-07-13) — general-purpose, for a
  single targeted claim/change needing a skeptical second look, distinct
  from the full `council-*` milestone review.
- **`premortem` skill** (`.claude/skills/premortem/SKILL.md`, built
  2026-07-21, adapted from
  https://github.com/b1rdmania/claude-premortem-skill) — runs BEFORE a new
  methodology/comparison arm/production change/PAPER.md claim is built or
  finalized, not after (the council and adversarial-reviewer are both
  post-hoc). Seeds its failure-reason generation from this project's own
  BUG-D taxonomy first, then ranges freely; dispatches one sub-agent per
  failure reason SEQUENTIALLY (not parallel — see the skill file's own
  note on why, tied to the still-open §11.9 orchestration-model
  question); outputs a markdown file under `docs/premortems/`. Trigger:
  "premortem this" / "find the blind spots" / "where will this break".
- **`guard_manifest.py` hook** (`.claude/hooks/`, built 2026-07-13) —
  PreToolUse hook blocking direct Write/Edit to
  `confirmed_pairs_manifest.json`, motivated by BUG-D63 (this exact file
  contaminated with test data twice). A backstop under the real
  structural fix (an injectable manifest path for test code), not a
  replacement for it.
- **Explicitly NOT recommended: `ponytail`.** Its "write minimum code,
  avoid over-engineering" philosophy conflicts with this project's
  verify-everything, no-bandaid-fixes discipline. Don't install.
- **draw.io** — noted for later, near v1 shipment, for architecture/
  pipeline diagrams. Not a current priority.

**Full inventory of installed plugins/skills/MCP servers, with exact
trigger prompts, lives in `docs/TOOLING_GUIDE.md` (added 2026-07-13) —
read that file for the complete list.** Highest-value ones for this
project's actual day-to-day work, so they don't get lost in the full
inventory:
- **`/code-review`** (installed 2026-07-13) — run after any nontrivial
  code change to `data.py`/`analysis.py`/`backtest.py`/`ml.py` before
  calling it done. Prompt: `/code-review` for the current diff, or
  `/code-review ultra` for a deep multi-agent cloud review before a big
  PAPER.md-facing milestone.
- **`/storm` and `/storm:storm-brief`** (installed 2026-07-13) — already
  in active use this session for market-structure/literature-convergence
  research (Phase 12 of the current plan). Prompt:
  `/storm <specific research question>` for a fully-sourced, cited
  report; `/storm:storm-brief <question>` for a faster, uncited
  multi-perspective think when speed matters more than citations.
- **`claude-code-setup`'s automation-recommender** — run periodically
  (e.g. once per major project phase) to check whether CAMARF is missing
  a useful hook/skill/MCP server. Prompt: invoke the
  `claude-automation-recommender` skill directly, or ask "what Claude
  Code automations are we missing for this project."
- **`obsidian`** — not yet used on CAMARF; Ross wants to use it at some
  point. Relevant if/when session notes, the research backlog, or
  literature findings move into an Obsidian vault rather than staying as
  flat `.md` files in this repo — not a current need, noted for later.
- **`superpowers`** (installed 2026-07-13, many sub-skills) — general
  engineering-discipline skills (TDD, systematic debugging, brainstorming
  before creative work, etc.). Overlaps with rules already established in
  this file (verify-before-trusting, full comprehension before code) —
  use where it adds a concrete checklist Claude wouldn't otherwise follow,
  not reflexively on every task.

---

## Current State (update this section each session)

### START HERE — Ross's explicit directive for the start of the NEXT session (added 2026-07-14)

Before picking up any other backlog item, run a full-codebase sweep for bugs, inconsistencies,
flaws, errors, edge cases, and oversights — "everything and anything possible" — logically
reasoning through every script and how it connects to the rest of the pipeline, not just checking
files in isolation. Ross's own framing: deploy code-reviewer, feature-dev, the improve plugin,
context7, "or all of them," across the entire codebase, every script total. Do a full bias sweep
alongside it (tasks #18/#19 already existed for this — this directive expands their scope, doesn't
replace them). Specific things this sweep must cover, not just generically imply:

1. **Point-in-time/causal correctness for every statistical test, done/doing/future** — not just a
   `center=True` grep (that only catches one failure shape). Session 28 found a real instance
   (BUG-D69) where a scalar field was computed correctly-causally in one code path, then silently
   overwritten by a non-causal recomputation in a different code path reusing the same object —
   this class of bug needs its own explicit check, not just a rolling-window-parameter grep.
2. **Cross-script bug-fix propagation** — Session 28 found the SAME bug class recurring independently
   at least twice (BUG-D62→D64, a Sharpe-pooling-convention bug; BUG-D65→D66, an append-seam
   contamination bug across 7 symbols instead of 1). Every bug fixed this session or logged in
   `docs/BUG_LOG.md` needs an explicit check: does this same bug CLASS exist anywhere else in the
   codebase, not just at the one instance that got fixed.
3. Survivorship bias (task, scoped Session 28 — see the relevant Development.md entry): symbols
   `data.py` finds newly unfetchable need to be flagged as a distinct category (not conflated with
   format/config fetch failures) and their pre-delisting cached history retained and usable in
   testing, not silently aged out.
4. `pit_wfa.py`'s lookahead-bias fix (BUG-D68/D69, task #67) needs its actual re-run once resources
   allow — deferred, not forgotten.

### The full execution sequence Ross wants next session (added 2026-07-14, explicitly deferred from Session 28 — "it's a lot of things to do so i want all that noted for next session")

In order, not to be compressed into one sitting — this is genuinely multi-session work, said plainly
rather than implied to fit in one session and coming up short:

1. **Files updated, dedicated_pass.md's scoped ideas turned into real files** — build the actual
   `research/*.py` modules `dedicated_pass.md` currently only scopes (k-BAHC, copula-correlation
   extension of `copula_pairs.py`, wavelet-scale cointegration, beta-neutral lag structure, the
   relational-adaptation ideas #59-62, etc.) — "dedicated pass files created" means instantiated,
   not just documented.
2. **Code reviewers run** — code-reviewer/feature-dev/improve/context7 (Ross's own list, "or all of
   them") across the codebase, INCLUDING each newly-built module as it lands, not only once at the
   end — catching a bug in one module before three others build on it is cheaper than catching it
   after a full run already used it.
3. **Full run of the scripts including the full production pipeline** — task #46 (already scoped as
   the CAPSTONE task): `data.py`→`analysis.py`→`backtest.py`(all variants)→`stats.py`→`wfa.py`→
   `distance.py`→`sensitivity.py`→`deflated_sharpe.py`→`report.py`, plus every one of the 79
   research scripts. Realistically several hours on its own. Given this session's demonstrated
   process-stability issues (`run_in_background`-launched jobs dying repeatedly, `Start-Process`
   being the working fix — see Development.md's process notes), this needs active monitoring and
   relaunching as things die, not a fire-and-forget single command.
4. **A round of connections** — once real, current results exist from step 3, repeat the
   cross-script connections pass (`dedicated_pass.md` §10 is the first one, done Session 28 against
   pre-full-run state) informed by fresh output, not stale assumptions.
5. **Buildings** — build whatever step 4's fresh connections round surfaces.
6. **A run of those, a review of those, another run of those** — build → run once (unreviewed,
   research code, "does it run and produce sane output" is often the fastest first bug-detector) →
   code-review → run again incorporating fixes.
7. **Updates made to all documentation** — treat this as the final CONSISTENCY/POLISH pass (make
   sure everything agrees, nothing's stale), not the first time anything gets written. Development.md/
   `docs/FINDINGS.md`/`docs/BUG_LOG.md` should already be current throughout steps 1-6 (continuous,
   same discipline as every prior session) — deferring documentation entirely to one giant end step
   is a real risk given how many times a process died mid-task this session; current docs mean
   nothing real gets lost if something crashes partway through.

### Session 30 (2026-08-02 through 2026-08-04, still in progress) — see Development.md for full detail

**Section header claims below this point (Sessions 27/28's "v1 functionally complete", 23-pair
headline Sharpe) are now SUPERSEDED — stated plainly, not left for the reader to notice.** WRDS
was wired as primary for daily-and-coarser US equity/ETF data (Session 29), which changed the
underlying confirmed-pair universe materially, not just refreshed it. **Current confirmed set: 3
pairs** (`KVUE/KMB`@3m, `PNC/ZION`@4h, `IQV/Q`@1D — see `docs/FINDINGS.md`'s PIT-safety disclosure
section and `PAPER.md` §3/§5 for the full, honest accounting of why this is a real reduction from
23/26 pairs, not a data-quality regression). Seven new research/comparison-arm modules built
(cycle detection, Lévy jump-diffusion, rough volatility, options-Greeks features, SVM classifier,
inverse polarity, trig-identity convergence — `docs/FINDINGS.md` §13-19); a real PIT-safety gap
found across all seven (they source pairs from the same non-PIT full-history screen already
disclosed in `PAPER.md` §7.3.1, just not previously stated for these new modules — `docs/
FINDINGS.md`'s dedicated disclosure section); parameter sensitivity extended to the research/
layer for the first time, 12 arms across 2 batches (`docs/FINDINGS.md` §20-21, `research/
sensitivity_research.py`, new). `data_crypto.py` (Binance.US) built and completed its full
15-symbol backfill overnight — first time in 4 attempts. An unattended overnight pipeline
(`run_overnight_research.ps1`, new) covering the full non-data-fetch pipeline plus all 121
research scripts, and a dedicated episodic-scan re-run (`run_episodic_scan_overnight.ps1`, new,
the prerequisite for closing the PIT-safety gap) were both launched and actively monitored —
5 real infrastructure bugs found and fixed live during the overnight run (a misreported exit
code, a genuine PowerShell async deadlock, a silently-dropped-arguments bug, every stage-timeout
orphaning its process tree for hours before being caught via a sustained near-zero-RAM
investigation, and a same-script collision between the general pipeline and the dedicated
episodic job) — see `Development.md`'s "Late-night close-out" and "Overnight monitoring" entries
for the full, hard-won detail; this class of bug is worth reading before trusting any future
long-running unattended PowerShell orchestration in this project. **Top priority next session**:
build a PIT-aware pair-discovery adapter (`episodic_bhfdr_confirm_asof`, Session 30's own
BUG-D106 fix) once the overnight episodic scan completes, audit every research script for its
pair source, rewire, and re-run the affected `docs/FINDINGS.md` entries.

### Session 29 (2026-08-01) — see Development.md for full detail

5 causality-audit bugs found and fixed (BUG-D99-103 — GARCH-stop causal baseline, position-sizing
circularity, coint_fraction_rolling fold-leakage, macro publication-lag), each verified against a
real-data check that the synthetic test correctly fails against git-stashed pre-fix code. **WRDS
wired as primary** for daily-and-coarser (1D/7D/1M/3M/6M) CRSP-resolvable US equities/ETFs in
`data.py` (BUG-D104 found and fixed along the way — CRSP's native monthly file has no OHLC).
International equities and everything intraday remain yfinance-sourced. B1 (CRSP volume
share-count adjustment) remains open, deferred pending WRDS VPN access. A full
`data.py`→`analysis.py` production run comparing WRDS-primary against the yfinance-only baseline
was launched at the end of this session but not completed until Session 30 (BUG-D105, a real
regression in the WRDS wiring, silently collapsed the analysis universe to 148 assets and blocked
this comparison for most of Session 30 until found and fixed).

### Session 28 (2026-07-13 through 2026-07-14) — see Development.md for full detail

Very large overnight/autonomous session. Headline items: BUG-D65 through D69 found and fixed
(split-adjustment cache contamination across 7 symbols, a Windows filesystem case-collision in
near-miss scan output paths, the root cause of `pit_wfa.py`'s catastrophic point-in-time lookahead
result, and a related latent lookahead in its test-window backtest); PDR + Calmar Ratio built with a
real finding that the sizing-method ranking isn't metric-invariant; lead-lag search methodology
validated clean (no implementation bug, prior null results trustworthy); `analysis.py` completed a
full rerun against the expanded 1,661-asset universe; `dedicated_pass.md` holds a large scoped
research program (k-BAHC, copula-based correlation, wavelet-scale cointegration, beta-neutral lag
structure, and more) not yet executed. See `docs/BUG_LOG.md` for the full D65-D69 index and
Development.md for complete write-ups of each.

See `DEVELOPMENT.md` Session 27 (2026-07-05 through 2026-07-10) for full detail — the most recent,
much larger session (SPY/VOO exclusion committed, permutation-test bug fixed, Kalman slope+intercept
promoted to production then reverted after a rigorous 3-way comparison, IBKR breaker re-investigated
(still unresolved), portfolio-wide effective-bets/position-sizing work, and a full v1.x backlog
clear-out — 13 new comparison-arm modules, `options.py` finally built without paid data). **v1 is
considered functionally complete** as of this session; remaining backlog items are all either
optional extensions, environment-limited (IBKR, ML training data volume), or explicitly deferred
pending Ross's direction — none are gaps in v1's own claims. See `DEVELOPMENT.md` Sessions 10–22 for
earlier detail. Headline items from Session 22 (still the last FULL numeric pipeline snapshot with
inline Sharpe figures below; Session 27's numbers are in Development.md, not yet copied into this
condensed summary):

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
- **Next priorities** (stale as of Session 27 — SPY/VOO exclusion done, STORM survey done; see
  Development.md Session 27 for the actual current backlog, which is now mostly optional extensions):
  - ~~SPY/VOO exclusion~~ — done, Session 27 (`CrossAssetTagger._is_index_tracking_pair`)
  - ~~STORM literature survey~~ — done, Session 23
  - **ML gate**: ~2 weeks from 2026-06-30 for training data accumulation (23-pair set clock reset)
  - ~~`corporate_actions.py`~~ — done, Session 27 (`research/corporate_actions_audit.py`,
    confirmed built and run; this line was stale as of Session 28's doc-alignment sweep)
  - **New modules** (still planned): `coint_frac_window_grid.py`, `cross_session_leadlag.py`,
    universe expansion (NASDAQ, Russell, crypto)
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
- `earnings.py` — earnings-date fetch/cache (`EarningsCalendar`), used by `backtest.py
  --storm-earnings-blackout`
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
- `docs/BUG_LOG.md` — one-line-per-entry index into DEVELOPMENT.md's bug registry (added 2026-07-11),
  for finding a specific BUG-D/BUG-A number without reading the full narrative. Pure index — every
  entry's actual write-up still lives only in DEVELOPMENT.md.
- `PAPER.md` — living draft of the actual paper/thesis, started Session 10
  (2026-06-23). Sections marked [DRAFTED]/[OUTLINED]/[TBD] — update
  alongside DEVELOPMENT.md whenever a session produces a citable finding,
  not just at project completion. Kept deliberately tight around the
  paper's headline pillars — not every verified finding lives here.
- `docs/FINDINGS.md` — full-depth writeups of verified comparison arms and
  robustness checks that PAPER.md's §7.15 summarizes and points to, but
  doesn't reproduce in full (added 2026-07-11, to keep PAPER.md focused).
  Same verification standard as PAPER.md; organized by relevance to the
  paper's central claims, not by confidence or quality.
- `latest_run_data.log` / `latest_run_analysis.log` — auto-generated run
  summaries, written after every run, read these first when diagnosing

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
