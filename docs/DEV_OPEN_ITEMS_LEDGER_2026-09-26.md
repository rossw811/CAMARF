# Development.md Open-Item Ledger — 2026-09-26 (audit step 2)

Input: `docs/_dev_open_candidates_2026-09-26.json` (712 regex hits over `DEVELOPMENT.md`, 28,488
lines; markers "not yet", "next step", "deferred", "backlog", "pending", "open question", "not done",
"follow-up", "UNVERIFIED", "still open", "unresolved", ...). Read-only pass; no other file changed.

## Summary

| Class | Items |
|---|---|
| OPEN | 56 |
| NEEDS-ROSS | 13 |
| SUPERSEDED-BY-AUDIT | 28 |
| DONE | 86 (+ compressed notes) |
| OBSOLETE | 9 |
| **Distinct items (tabled)** | **192** |

**Hits dropped as narrative noise: 100 of 712** (see Method). The other 612 hits map onto the
192 tabled items below (plus a compressed DONE paragraph); one item often has several hits.

**Method.**
1. Grouped the 712 hits by Development.md section (332 sections) and read every hit in order.
2. Collapsed hits into distinct items: something someone said should be done, checked, decided, or
   fixed. Noise that was dropped: hits describing something done in the same paragraph ("not yet
   known at the time… then found"), headers of sections whose body is the item, "backlog" used as a
   noun for work that was being done in that same entry, historical "was not yet X" framing, and
   pure progress notes ("still running as of this write-up") that the next entry closes.
3. Checked each item for closure evidence in: later Development.md lines (a scripted regex search
   limited to lines after the item), `docs/HANDOFF.md` (newest first), `docs/BUG_LOG.md`,
   `docs/FINDINGS.md`, `git log --oneline --all` (102 commits), and the current code (grep/glob).
4. An item is marked DONE only when a concrete file:line, commit, or later Development.md line shows
   it was closed. Where Development.md says "fixed" and the code or `docs/CODE_REVIEW_2026-09-26.md`
   disagrees, the item is listed under Contradictions at the end.
5. Anything whose value depends on P&L, Sharpe, DSR, or capital-sim output is SUPERSEDED-BY-AUDIT
   (CODE_REVIEW B2–B4, P1, B11). Until P&L is rebuilt, every one of those numbers is wrong.

Line references are Development.md line numbers unless prefixed (e.g. `HANDOFF:3405`).

---

## OPEN (56) — sorted: result correctness > infrastructure > nice-to-have

### OPEN — correctness of results

| ID | Dev.md line(s) | Item | Evidence / notes |
|---|---|---|---|
| DEV-001 | 14962, 14964 | Wire the delisting/retained-history registry into a real consumer (PIT universe that includes delisted symbols' pre-delisting history). | `UniverseBuilder.load_delisted_registry()` exists (data.py:3888); the only caller is `debug/_verify_delisting_registry.py`. No backtest or screen reads it. Survivorship stays unaddressed on the PIT path. |
| DEV-002 | 26557, 26847; HANDOFF:3775, 3869 | Item #16: rebuild the PIT screen's universe off CRSP's point-in-time security master instead of today's cache glob (present-day-cache survivorship). | HANDOFF:3869 lists it as open: "genuinely large rebuild, not scoped in detail." Nothing later. |
| DEV-003 | 20131, 20136 | CRSP `dlyvol` is stored raw, not adjusted for share-count changes; the `dlycumfacshr` direction was never checked against a real split. ADV gates use this volume. | data_wrds.py:490 still only describes the issue. No later fix in Development.md or git. Related to R1.2 (ADV in local currency). **RESOLVED (direction) 2026-10-03:** adjusted volume = raw dlyvol x prod(1+disfacpr) over later events (CRSP stkdistributions, 65,141 events fetched); matches yfinance split-adjusted volume on AAPL 2014/2020 within 0.2% (2010: 3.5%). `research/crsp_volume_split_adjustment.py` + `debug/_verify_crsp_volume_split_adjustment.py`. Consumers (rolling-ADV gate, liquidity mask, sqrt impact) NOT yet switched -- impact measured first; the running discovery scan uses the raw (biased) volume. |
| DEV-004 | 25347, 25348 | Run the newly visible WRDS `1Y` contamination-scan events for the 10 confirmed-pair symbols through the peer-corroboration check. | Marked "Genuine open item" at 25348. HANDOFF:4585–4595 covers only the earlier (pre-WRDS-scan) events. |
| DEV-005 | 28168; HANDOFF:3405 | Regenerate the 2 stale spread series `KVUE/KMB@3m` and `PNC/ZION@4h` (`deep_history_used=True`; `promote_full_universe_pairs.py` can't regenerate them). | HANDOFF:3405: "real, small, bounded follow-up, not urgent, not built." Nothing later. |
| DEV-006 | 20908 | Train `ml.py` on the full correlation-screened candidate universe, with episodic significance as a feature and no confirmed-pairs gate ("Decided, not yet built"). | ml.py:520–545 still takes pairs from the confirmed set or the PIT-confirmed episodic set. Blocked in practice by R2.3: there is no purge/embargo yet. |
| DEV-007 | 9826, 10182, 10897, 11093, 11095 | Run `research/ml_lookahead_selftest.py` on real training data. | Built at 11066. At 21077 it was deferred to "task #8 step 4". No later real run is recorded in Development.md, HANDOFF, or git. |
| DEV-008 | 27838 (analysis.py:6375–6379) | Fix the read-modify-write race in `confirmed_pairs_manifest.json` writes. The writes are atomic now; two concurrent `analysis.py` runs can still overwrite each other's TF update. | The code comment says it is not fixed and needs file locking. HANDOFF:3371 says the same. |
| DEV-009 | 21184, 21193 | `cross_tf_break_divergence.py`: separate the bar-count/window-count confound from the short-vs-long asymmetry, and explain why `intact_side_ever_broke=True` for every event. Neither is resolved. | Task #9 closed the re-runs (21296), not these two caveats. The finding was never promoted. |
| DEV-010 | 23144, 23145 | Thread J window sweep: re-derive the headline after the artifact correction (the confound-adjusted rate rises monotonically with window length). | "Flagged as the right next step, not done." No later re-derivation. |
| DEV-011 | 22162, 20772, 24470 | Re-run the 5 scripts whose "full universe" was the yfinance glob (`inverse_polarity.py`, `cross_timeframe_cointegration.py` full_universe_scan, and 3 others) at the real `load_full_universe()` scale. | 24470: "Not yet re-run against the real universe." 22162: the cross-TF run was "never confirmed completed". Later sessions fixed the loader but show no re-run of these 5. |
| DEV-012 | 10909 | Bounded-lookback primary screen rests on only n=1 real comparison (7267.T/8058.T@1M). It was gated on universe expansion, which has since happened. | No re-run at the WRDS-expanded scale found. |
| DEV-013 | 3408 | `analysis.py`'s end-of-run per-TF `pairs=N` summary was reported as the pre-coint_frac-filter count. | Not verified either way. analysis.py:6639 still prints `len(pairs_by_tf[tf])`, and no later fix is recorded. **FIXED (stale entry) — verified 2026-10-03:** `_save_tf_results` returns the persisted set (analysis.py `pair_results = AnalysisPipeline._save_tf_results(...)`, commit 3b2b1741, 2026-06-23); `_run_one_tf` returns it and `pairs_by_tf[tf_label] = pairs` uses it, so both summary lines count saved pairs. Test: `debug/_verify_save_tf_results_return.py` (returned == on disk; passes 2026-10-03). |

### OPEN — infrastructure

| ID | Dev.md line(s) | Item | Evidence / notes |
|---|---|---|---|
| DEV-014 | 4472, 4476 | Add a read-only-mode gate so `analysis.py` cannot mutate the cache (tied to a real near-incident; flagged twice). | No read-only/cache-mutation gate in analysis.py (grep). No later mention. |
| DEV-015 | 17218 | Run BUG-D73's `merge_with_yfinance()` split-seam fix against a real IBKR supplement refresh. | No later mention anywhere. |
| DEV-016 | 24504 | Re-test the `scripts/mem_guard.py` tree-kill fix against a real memory-floor breach. | No later mention. |
| DEV-017 | 23615, 23627; HANDOFF:3830 | CachyOS NTFS mounts are not persistent (no `/etc/fstab` entries). | HANDOFF:3830: "drives are still not mounted." Ross has to do this. |
| DEV-018 | 23744; HANDOFF:5251 | Run memtest86+ on CachyOS and confirm RAM speed (`dmidecode`) to close the hard-hang question. | HANDOFF:5251: "has not been run yet." |
| DEV-019 | 25249 | Windows-side fix Ross has to run himself (admin rights). | "not yet confirmed run." |
| DEV-020 | 25533 | Vectorize `research/earnings_structural_break_correlation.py`. | "scoped, needs design thought before building." Nothing later. |
| DEV-021 | 20697 | Root-cause the overnight failures of `r134_descriptive_check_concordance`, `r146_follower_direction_validation`, and `r166_lo2002_sharpe_correction`. | "logged as a known gap." No later root cause. |
| DEV-022 | 20672 | Exclude `wrds_deep_history_episodic_scan.py` from the overnight runner's discovery. | Done in run_overnight_research.py:266. `run_overnight_research.ps1` still exists without the exclusion. Either delete it or port the fix. |
| DEV-023 | 17162, 17464, 17490 | Extend the config-drift guard and constant centralization beyond `wfa.py`/`sensitivity.py` to the other ~90 research scripts. | Only done for the files found at the time (17451). CODE_REVIEW C16 (`_IO_WORKERS=32` hardcoded) is a live example. |
| DEV-024 | 23269, 23574 | Rest of the CachyOS optimization plan (Ruff, Pandera, Python 3.14 compatibility); time the raw-file reader on the 9.2 GB cache. | The Polars swap is done (23756). Nothing else is evidenced. |
| DEV-025 | 18164 | Annotate the two config fields found to have doc drift in the gate-vs-descriptive enumeration. | "not done here." |
| DEV-026 | 20506 | Identify a headline metric for the remaining 39 parameterized research scripts (continues batch 1). | "explicit backlog, multi-session." No later batch. |

### OPEN — nice-to-have / research extensions

| ID | Dev.md line(s) | Item | Evidence / notes |
|---|---|---|---|
| DEV-027 | 303, 289 | ml.py Stage 2 `garch_zscore` feature using asymmetric GARCH (EGARCH/GJR). | No `garch_zscore`/EGARCH/GJR anywhere in the code (grep). The Stage 2 ablation (10565) did not include it. |
| DEV-028 | 3720, 7306, 7307 | SHAP explanations for ml.py (blocked on numba/numpy). | No `import shap` anywhere. |
| DEV-029 | 3971 | Surface vol-regime (short/long vol ratio) as its own diagnostic or ml.py feature. | "Deferred, not built." Nothing later. |
| DEV-030 | 4078, 4079, 4471 | Line-by-line audit of the cumsum-based `cvd_proxy` before Stage 2 uses it. | `cvd_proxy` exists only in analysis.py. No audit recorded. |
| DEV-031 | 5407 | Copula Mispricing-Index trading signal/backtest (only if the copula result holds up). | Not built. `copula_pairs.py` is diagnostic only. |
| DEV-032 | 6127, 26836, 26839; HANDOFF:3871 | Crowding: cross-spread correlation as a Layer-4 sizing signal, and wire the FINRA short-interest fetcher into an analysis. | `data_finra.py` is imported only by its verify script. SEC EDGAR is used (SPAC exclusion). FINRA is not. |
| DEV-033 | 6220, 6221, 6222, 6224 | Free data sources never added: CBOE SKEW, CBOE put/call, Google Trends. | No fetchers exist (glob/grep). FINRA and VIX term structure are done. |
| DEV-034 | 8018 | Wire the absorption ratio into position sizing or regime gating. | absorption_ratio.py only appears in an analysis.py comment (2352). It gates nothing. |
| DEV-035 | 6581 | Test whether entries during high comomentum (>0.113) have lower convergence rates. | comomentum.py was fixed for lookahead (BUG-D78, 17540). This specific test is not recorded. |
| DEV-036 | 12995, 12997, 12999 | Run the Merton jump-diffusion MLE across the full confirmed-pair set (so far one pair, AMD/DD). | `jump_diffusion_parameter_fit.py` exists. No full-set run recorded. |
| DEV-037 | 13882 | KO/PEP: test with a regularized/Kalman hedge ratio. | "candidate follow-up, not claimed." |
| DEV-038 | 15103 | GPC/ZION smoothing hit needs its own multiple-testing-corrected follow-up. | Not done. |
| DEV-039 | 15689, 15715 | Characterize the unexplained structural-break date clustering from the task #70 cross-check. | "reported as an open question." |
| DEV-040 | 15964 | Explain why the task #67 test window fails in every train-window variant. | "not yet investigated." |
| DEV-041 | 18462 | Wavelet-scale cointegration comparison arm. | DCC-GARCH is done (`research/dcc_garch_pymgarch_comparison.py`, 25148). No wavelet-cointegration script exists. |
| DEV-042 | 19259, 22526 | Remaining WRDS tiers (TRACE, Execcomp, Dealscan, insiders, event study) and a usability check of `contrib_global_factor`, CDS, and bond tables. | Fama-French/Compustat fundamentals (21776) and IBES (26658) are done. The rest is untouched. |
| DEV-043 | 20885, 21025, 21032, 21047, 21048, 21173 | Cross-TF break research: onset-age comparison arm; Tier 2/3 (true cross-asset, cross-TF); backtest of trading the intact side. | Only Tier 1 detection exists (`cross_tf_break_divergence.py`). No onset-age arm script. |
| DEV-044 | 21514 | "Actually usable, not just significant" duration/degree-of-cointegration test. | "not yet started, genuinely multi-session." |
| DEV-045 | 21561 | Ridge-regularized hedge ratio for short intraday windows. | "not-yet-attempted follow-up." |
| DEV-046 | 22476, 22477 | Mechanism behind the ~13% entry-signal divergence between EWMA z and rolling z. | "flagged for follow-up, not closed." |
| DEV-047 | 22735, 22737 | Thread M Option B: run the JKP raw-characteristic regression on real WRDS pair-leg data. | Built and verified, never run. (Option A regresses on backtest returns and falls under B2; see DEV-S04.) |
| DEV-048 | 22895 | Run `frame_pair_around_macro_transition` on real data. | "not yet run." |
| DEV-049 | 10731 | Pin down the session in which the cross-timezone universe layer was added (reproducibility section). | "needs a dedicated follow-up grep." |
| DEV-050 | 5750 | Worked CVSA/MPT correlated-but-not-cointegrated example for PAPER §4.1. | Not found in PAPER.md drafts. Belongs to the step-4 paper rewrite. |
| DEV-051 | 10297 | README/CLAUDE.md "Known Biases": survivorship is partly addressed, not "unaddressed". | Queued for Phase 4 doc alignment. Not verified as applied. |
| DEV-052 | 26167; HANDOFF:1–27 | HANDOFF 09-22 backlog: "arxivisual" graphical abstract, a new author-concept backlog pass, an arXiv comparison pass, and the arXiv literature-search script. | HANDOFF:25: "None of these four are started." (Item 2, arXiv-readiness audit, is DEV-S27.) |
| DEV-053 | 14126, 14149 | Task #63: systematic relational sweep across every concept the project has touched. | "queued, not done." No later task #63 entry. |
| DEV-054 | 12090 | Broader universe-expansion decision (NASDAQ, more international). | Mostly overtaken by the ~44,700-symbol WRDS universe (CLAUDE.md standing direction). Still open for intraday (IBKR/yfinance) coverage. |
| DEV-068 | 15500 | Use the checkers in `debug/synthetic_diagnostics.py` in new research scripts' own verification, and grow the generator set as new bug classes appear. | Only one other file imports it (grep: 2 files including itself). |
| DEV-069 | 16245, 16256 | Shared-leg hub concentration (one name as a leg in many pairs) is not modelled by HRP or risk parity. Literature gap found, no CAMARF-side treatment. | "Open question, not settled by this research." Related to B4 duplicate exposure and R7.12 breadth. |

---

## NEEDS-ROSS (13) — blocked on a methodology/concept decision

| ID | Dev.md line(s) | Item | Evidence / notes |
|---|---|---|---|
| DEV-055 | 10900, 12044, 12627 | Holdout convention: 29+ evaluations have used the same OOS slice. Adopt `fresh_holdout_compare.combined_split()` (time- and pair-reserved)? | 12627: "Presented to Ross as a proposal, not adopted — his explicit call was to wait for more data." Once P&L is rebuilt (B2–B4) this becomes the key decision, since the reserved-fresh slice has not been touched yet. |
| DEV-056 | 27285, 27330, 27390, 27740, 27771, 27774 | `MIN_OVERLAP_BY_TF`: every value is "provisional pending item 2". The pilot suggests overlap length may be the wrong lever. | 27740/27774 queue this for Ross. CODE_REVIEW C13 (missing 3M/6M/1Y in `MIN_BARS_REQUIRED`) belongs to the same config family. |
| DEV-057 | 736, 747, 749, 4746, 5444, 8137 | Policy for flagged pairs (EG-permutation flag, decoupling flag): exclude, downweight, or flag-and-include? Plus the minimum-viable-portfolio gate. | 4746: "Not yet decided with Ross." No decision recorded later. |
| DEV-058 | 19465, 19477, 21769 | S&P 400/600 point-in-time membership is not in this WRDS subscription. Options: partial fix, wait for a different subscription (Baruch), or keep the Wikipedia-current approach. | 19477: "Decision pending Ross's input." Still unavailable (26591). |
| DEV-059 | 15784, 15786, 16132, 16134, 16140 | IBKR deep history (the 3–4Y ceiling after the timeout fix): confirm on the other 16 symbols, then decide whether to re-run `data_ibkr.py` at scale. | 16140: decision reserved for Ross. Nothing later. |
| DEV-060 | 5760, 6231, 6232 | Factor-level cointegration and lead-lag (Ross's own idea), deferred to an interactive session. | No script. `jkp_factor_*` is a different question. |
| DEV-061 | 981, 1011 | Implied-correlation divergence: dispersion-style scope and whether to prototype a standalone diagnostic ("ask before building"). | Not built. options.py has Greeks and RND, not implied correlation. |
| DEV-062 | 6144, 6210 | Locate the "Singha" hidden-order paper (Ross to track down). | No later mention. |
| DEV-063 | 23533, 23641 | GPU re-implementation of the EG/Johansen/ADF AIC-selection loop (a new numerical procedure). | "Recommendation, explicitly NOT started", gated on Ross. |
| DEV-064 | 23965 | Momentum/reversal overlay: trade the same two legs or a universe-wide basket? | "design choice not yet made, would need Ross's input." |
| DEV-065 | 25659, 25661 | Join the 44,840-symbol growth into §5's crisis scan and §7.2's episodic segmentation (substantial re-run). | "flagged for Ross's scoping decision." |
| DEV-066 | 17818 | Paper framing: the project's meta-contribution (bug registry, "publish the collapse honestly") as the main contribution. | "deferred at Ross's request." Relevant to the step-4 rewrite. |
| DEV-067 | 15144 | Replace or supplement the `hurst_rs < 0.50` production criterion with DFA/wavelet Hurst, which may admit genuinely mean-reverting pairs R/S rejects. | Comparison arm exists (`research/wavelet_hurst_comparison.py`). Production has not changed. This is a gate change, so it needs Ross. |

---

## SUPERSEDED-BY-AUDIT (28) — moot or subsumed by `docs/CODE_REVIEW_2026-09-26.md`

| ID | Dev.md line(s) | Item | Superseding finding |
|---|---|---|---|
| DEV-S01 | 4612, 4619, 4621, 4628, 4639, 4660, 4666, 4697, 4880, 4889, 4895, 4897, 4920, 5104, 5189, 10369, 10370, 10376, 10378, 10404, 10780 | BUG-D49 "degenerate 1m bars": universe audit, root cause (market cap), flagged-pair policy, `predicted_degeneracy_risk` gate, "is EG well-specified on sparse prices", and a candidate third paper pillar. | **D1 (escalated, R8):** `_liquidity_filter` NaNs every bar under $1M *per-bar* dollar volume and forward-fills it, so most sub-hourly bars of mid-caps are filter copies. The "genuine market data" attribution is wrong (see Contradictions). |
| DEV-S02 | 9110, 9114, 10883, 10961, 10998 | Lo (2002) autocorrelation correction on the headline Sharpe, and whether to promote the corrected 5.81/7.00. | B2–B4, P1: the underlying Sharpe is built on broken P&L. |
| DEV-S03 | 11317, 11319, 12031, 12036, 12054, 12643, 12644, 12933, 13405, 10852, 28094, 28101, 28103 | PAPER.md/README numbers-and-tone reconciliation passes, DD-hub caveat, international-pair wording, gold/silver tier counts. | Step-4 rewrite. Every P&L number falls under B2–B4. Tier counts fall under S6 (PO/KPSS proxy inflates gold/silver). |
| DEV-S04 | 16168, 16170, 16205, 16252, 16298, 16299, 16335, 16336, 16341, 16568, 16846, 17041 | Apply the `docs/PAPER_PENDING_CHANGES.md` drafts (§4.2 MC reframing, §7.5, §7.2 RP-vs-HRP, §7.3.1, tensions). All are still "drafted, not applied". | Step 4. Several rest on superseded numbers: §7.3.1 (B2, S3), §4.2 MC (R6.3/R6.4), §7.2 (B4/P1). |
| DEV-S05 | 13649, 13688, 13302, 12050, 10798, 10910 | Promote STOP_ZSCORE 3.0; re-run §7.8 sensitivity grids; regime-conditional OOS re-run; coint_frac as a sizing signal; tail-risk-vs-Sharpe section. | B2–B4, B11 (every one is a Sharpe/P&L comparison). |
| DEV-S06 | 11557, 11879, 11880, 11882, 12219 | Line-by-line inspection of `distance.py`/`sensitivity.py`; permutation null for the 16-trade distance Sharpe; BUG-D62 holdout-window check. | B2–B4, B11. |
| DEV-S07 | 17023, 17041, 17043, 16999 | Re-run stats.py/cvar.py/deflated_sharpe.py/fresh_holdout against the settled pair set; settle `_build_daily_pnl`'s zero-fill convention. | S9 (`_build_daily_pnl` not zero-filled), P1 (`portfolio_math` calendar-day √252), S11/R2.1 (DSR registry). |
| DEV-S08 | 17336, 21609, 22914, 25869, 25875, 25886, 26142, 26166, 22735 | BUG-D76 before/after Sharpe; sweep of the PIT-confidence multipliers; VaR-sizing green light; pooled WFA-daily Sharpe; robustness CI for the concentration cap; repeated-sampling CI for the diversification basket; Thread M Option A. | B2–B4 (and R5.1 for pooled fold Sharpe, B8 for the D76 holdout cut). |
| DEV-S09 | 23860, 23883, 23933, 23934, 18235, 18239 | Thread Q diagnostics re-run on PIT-safe/episodic trades; descriptive-signal vs backtest-performance concordance. | B2–B4 (all compare against realized P&L). |
| DEV-S10 | 28464; HANDOFF:239 | Quality-ranked capital admission: turn it into a deployable rule. | Group 1 #1–#2: the `batch_freq` lookahead was removed, and the 09-22 luck-check verdicts do not survive the re-run. Also B2–B4. |
| DEV-S11 | 23909 | Regime-age sizing (`--regime-age-*`) is not part of BUG-D76's IS-only fit, so it has a lookahead risk with `--holdout`. | B7 (same shape as `--decay-rate-sizing`; precomputed file, no IS-only fit). |
| DEV-S12 | 17440, 17446 | Retrofit `convex_portfolio_construction.py`, `eigenvalue_weighted_position_sizing.py`, and the ERC file onto the walk-forward scaffold. | R5.2: walk-forward still uses clusters from `panel.corr()` over layer1 + holdout. Development.md 17776 says "All 3 … now retrofitted" (see Contradictions). |
| DEV-S13 | 19313, 19902, 22227, 22303, 22322 | Verify Compustat Global `trfd` total-return reconstruction; run Thread I's global-universe pipeline. | R1.1 (no FX conversion, local-currency prices), U4 (WRDS `close` is price-only), R1.4. |
| DEV-S14 | 19353 | Wire WRDS 3M/6M/1Y into the production TF loop. | C13: they were wired (`WRDS_PRIMARY_TFS`), but `MIN_BARS_REQUIRED` lacks 3M/6M/1Y, so almost every symbol is rejected. |
| DEV-S15 | 19824 | Episodic-scan resume across separate invocations (crash between tiers). | R1.7, R1.8 (checkpoint cleared before BH; resume not keyed on params). |
| DEV-S16 | 24420, 24421 | Re-fetch the 1,032 missing or corrupted WRDS cache files (skip-and-log added). | D16 (1,647 zero-byte files on CachyOS only), U1 (loader drops them uncounted). |
| DEV-S17 | 24607 | BH-vs-BY at the real ~44,700 scale (only an N=300 sample was used). | R1.11 (one-direction EG, price-only closes). `bh_vs_by_full_universe_1d.py` has to be fixed before the re-run is meaningful. |
| DEV-S18 | 24667, 26688 | Pre-registered "does regime strength predict PIT survival" test, and controlling for raw correlation strength. | R4.1 (circular strength terciles, confirmed via R6), R4.2 (invalid z-test at x=0), R6.2. |
| DEV-S19 | 26919, 12839, 10787 | Re-derive the §4.2.1 Monte Carlo EG-null calibration post-WRDS; lead §4.2 with Claim B; generalize the Strictness-Paradox robustness check. | R6.3 (the MC uses one-direction `coint`, not the production call), R6.4. |
| DEV-S20 | 26564 (survconf), 26737 | §5 survivorship confound test. | R3.10 (never filters to crisis-first), R3.11 (design can't detect exclusion survivorship). |
| DEV-S21 | 26356, 26443, 26444 | Confidence score: drop or invert the reversion-speed category. | R7.1 (vol-profile lookahead, ~25% of the score), R7.2 (percentiles against the full trade set). |
| DEV-S22 | 26488 | Interpret the realized-vs-implied skew divergence. | R7.8 (detector name overstates; VRP expected). |
| DEV-S23 | 20957, 20963 | Systematic ML validation system (overfitting/survivorship/lookahead). | R2.3 (no purging or embargo in ml.py/LSTM), R2.11, R4.10 (TE feature lookahead). |
| DEV-S24 | 14555, 16085, 16086 | Point-in-time/causal correctness sweep of every statistical test; close the bias-sweep coverage gaps. | The 09-26 review (groups 1–7, ~190 findings) is that sweep. |
| DEV-S25 | 17103, 17115, 17117, 17380, 17381 | BUG-D77 gap handling: measure DATA_GAP incidence across the full universe, not 19 symbols. | B1, D1, D5, D8: gaps are forward-filled at cache time, so no DATA_GAP flag survives into spread_series. Measuring "real outage incidence" from flags is moot until that is fixed. |
| DEV-S26 | 10919, 4149 | Corporate-actions reconciliation beyond a 4-symbol spot check; `_roll_adjust` 5% false-roll threshold. | D12 (split reconciliation compares different dates; dividend seams never reconciled), R8 note on `corporate_actions_audit.py`; D9 (`_roll_adjust`). |
| DEV-S27 | 139, 14463, 14472, 13219, 13233, 21246; HANDOFF:9 | Deep-history `coint_fraction_rolling_deep` has no gap_flag; permutation-correct the 3m near-miss outlier (667 flagged); re-run lag-aware discovery on a fresh intraday near-miss scan; write up the stress-test result; arXiv-readiness audit (HANDOFF 09-22 #2). | A10/A3 (deep-history enrichment); D1 escalation + D3/D4 (yfinance intraday 1m–30m suspect); R5.5–R5.7 (stress test); this review is the arXiv-readiness audit. |
| DEV-S28 | 16849 (part 2) | Pre-registered, economically motivated universe restriction to recover the 8 excluded 1h pairs. | Standard screen: A1 (EG never runs on pairs with different start dates; they are dropped from BH m). The "8 excluded pairs" premise has to be re-derived after A1. |

---

## DONE (86)

| ID | Dev.md line(s) | Item | Closure evidence |
|---|---|---|---|
| DEV-D01 | 605 | Maximum holding period | config.py:758 `MAX_HOLD_MULTIPLIER=2.0`; backtest.py:994–1016 `max_hold` exit |
| DEV-D02 | 2688, 2690, 2752 | Rich regime classification; ML ensemble / multi-system discovery | `research/regime_conditional_entry_gate.py` + `_regime_features.py` (10463); ensemble shown not orphaned (10404 correction) |
| DEV-D03 | 2862, 2877, 10272, 10912 | PairCharacteristicsAnalyzer and archetype clustering | `research/pair_characteristics_analyzer.py`, `research/archetype_conditional_sizing.py` (2862 notes built) |
| DEV-D04 | 2949, 2952, 2956, 2962 | Fundamentals data source | WRDS Compustat fundamentals + `comp.company` fetched (21776–21802) |
| DEV-D05 | 3623, 3720 (macro part) | Macro context into ml.py Stage 2 | `research/ml_stage2_ablation.py` (10565) |
| DEV-D06 | 3650 | Per-bar regime labels in spread series (deferred for runtime) | Overtaken by per-trade regime context in backtest.py:268–276; not needed as a per-bar column |
| DEV-D07 | 3696, 3698 | yfinance intraday 96–100% failure | Resolved the same session; later intraday caches fetched normally (3704ff "4h derivation … both succeeded fully") |
| DEV-D08 | 3897 | BUG-D44 labeling pipeline needs data volume | ml.py trained for real (HANDOFF:2081, 1784) |
| DEV-D09 | 4502, 4503, 4492, 4508 | [TBD] citations and [PLACEHOLDER] sections in PAPER.md | 4511 ("previously-[TBD] citations" filled); later PAPER drafting |
| DEV-D10 | 4549, 4569, 4570, 4571 | Re-verify vectorized `_pairwise_corr` / `_fix_ambiguous_variance_cells` | `debug/_verify_pairwise_stats_low_memory.py`; 23214 |
| DEV-D11 | 4751, 4773 | MIDAS "does it help" comparison | `research/midas_feature.py`, `research/midas_cross_asset_lead_lag.py` (20722–20735) |
| DEV-D12 | 5311, 5321, 5368, 5371, 5444 (item 1) | Permutation-corrected best-p across K lags | `research/lead_lag_permutation_check.py`, `research/lag_aware_cointegration_discovery.py` (13169) |
| DEV-D13 | 5582, 5583 | data_ibkr stale deep supplements | BUG-D70 `bypass_cache` (data_ibkr.py; 14827→15721) |
| DEV-D14 | 5710, 6234 (overlap) | Overlap length as a confidence signal | Studied: `research/overlap_threshold_pit_test.py`, `multivariate_pit_predictors.py`, GEE refit (HANDOFF:330). Threshold decision → DEV-056 |
| DEV-D15 | 5961, 5968 | `_gap_aware_returns` elapsed-time check | data.py:967–991 (elapsed-time > 4× median masked); `valid_lag1_mask` (17623) |
| DEV-D16 | 6006, 6036 | Stale confirmed-pair set; `hedge_direction_conflict` etc. | Re-analysed in later sessions; 6036 notes field live |
| DEV-D17 | 6226 | near_miss_lag_scan on other TFs | Task #53 all TFs (14418) |
| DEV-D18 | 6234 (report), 6692, 7308, 7329, 7662 | report.py build | 7697 "report.py ✅ Complete"; `report.py` exists |
| DEV-D19 | 7031, 10256 | S7 half-life stationarity | stats.py Section 7 (10256) |
| DEV-D20 | 7164, 7302 | Session 17/19 pending items (hedge conflict, Kalman drift) | Marked DONE in place (7164, 7302) |
| DEV-D21 | 7307 | options.py (no historical IV source) | options.py built with Greeks and RND (26171ff) |
| DEV-D22 | 7338, 7340, 7341, 10528, 10530, 10532, 10903, 11163 | Exchange-aware .L/.T/.HK session handling on a real fetch; BUG-D57 | 12059; BUG_LOG D57 (VOD.L 44.5→88.9%) |
| DEV-D23 | 7597, 7602 | 1h pair loss, FDR α decision | BUG_LOG D52 (FDR_ALPHA fix) |
| DEV-D24 | 7727 | STORM brief, full pipeline review, bug sweep | 8594 (STORM); Grand Sweep 2026-07-20 (16967ff) |
| DEV-D25 | 7966 | DSR units mismatch | Fixed in place (7966); now under R2.1/S11 for registry issues |
| DEV-D26 | 8081, 8094, 8558, 8643 | PAPER cross-references (Session 23), FilterFunnel into PAPER | 8643 "closed above" |
| DEV-D27 | 8097, 8103, 8113 | Decoupling-as-signal research + backtest | `research/decoupling_analysis.py`, `research/decoupling_backtest.py` (R7.11 caveats apply) |
| DEV-D28 | 8305, 8827 | IBKR client-id / Gateway log checks | `--client-id` override added (8305); breaker root-caused (see D34) |
| DEV-D29 | 8347 | Re-run optional research diagnostics | Overnight research runner (24357: 172/195 stages) |
| DEV-D30 | 8839 | BiasAuditLog pair-selection lookahead in `bias_audit.json` | BiasAuditLog 45 entries/run (20959); atomic save (27843) |
| DEV-D31 | 8925, 8928, 8987, 8997, 9013, 9064, 9162, 9184 | Author concept backlog rounds 2/2.5/3; McLean–Pontiff | 9184 "Nothing left open"; McLean–Pontiff cited 16311 |
| DEV-D32 | 9025, 10876 | Split Development.md / BUG_LOG.md | `docs/BUG_LOG.md` exists (288 lines) |
| DEV-D33 | 9201, 9537 | Chan Kalman slope+intercept, full backtest | `research/kalman_slope_intercept.py`; real backtest loses to origin-only (10063) |
| DEV-D34 | 9558, 9578, 9584, 9662, 10905 | IBKR circuit breaker | Root-caused as client timeout / request size (16092ff); BUG-D70 bypass fix |
| DEV-D35 | 9321 | SPY/VOO exclusion | Commit `e5b76808` |
| DEV-D36 | 9544, 9546, 9901, 9903 | Remaining triage items (weak-exog, FTI, CAViaR, QRF, glasso, MSE, convex) | Built 9901ff (`research/weak_exogeneity_test.py` etc.; R4/R7 caveats apply) |
| DEV-D37 | 9714, 10613, 10615 | Correlation-aware position sizing follow-up | `research/eigenvalue_weighted_position_sizing.py` (10613); see DEV-S12 |
| DEV-D38 | 10262 | Bounded-recent-lookback primary screen | `research/bounded_lookback_primary_screen.py` (n=1 caveat → DEV-012) |
| DEV-D39 | 10247 | `coint_frac_window_grid.py`, `cross_session_leadlag.py` | Both exist in research/ |
| DEV-D40 | 10495, 10883 (#3) | `vix_ts_regime` never populated | backtest.py:268–276, 978; empty is by design in Layer 1 (11053). B13/M9 caveats |
| DEV-D41 | 10821, 10912 (#11), 11229, 11231, 11249 | requirements.txt pandas drift timeline | Resolved 11227–11249 |
| DEV-D42 | 11021, 11030 | Carver vs carver+coint_frac comparison | 11285–11286 (numbers under B2) |
| DEV-D43 | 11371 | BUG-D58 survivorship truncation | backtest.py:2146–2169 `resolve_survivorship_oos_end`; BUG_LOG D58 (see Contradictions re B15) |
| DEV-D44 | 11604, 11652, 11661, 11694, 11699 | BUG-D60 capital constraint; causal vol sizing; flat_2pct/Kelly | `portfolio_sim.py`, `--capital-sim` (12031) |
| DEV-D45 | 12036, 12095, 12230 | "Capital constraints raise Sharpe" not understood; zero-fill | BUG-D62 root-caused and fixed (12234) |
| DEV-D46 | 12308, 12321, 12388 | BUG-D61 per-pair vs global cutoff gap | Closure confirmed (12308) |
| DEV-D47 | 12735 | DSR trial-count re-tally | Re-run 12728ff (now under R2.1) |
| DEV-D48 | 13006, 13008, 13024 | Analyst price-target convergence idea | `research/price_target_pairs_overlay.py` (26658; R8.9/R8.10 caveats) |
| DEV-D49 | 13073, 13083, 13084, 13103, 14087, 14090, 14096 | DD/MIDD hub mechanism; trend-dominance wiring; confirm 6 non-DD symbols | Root cause was cache contamination (BUG-D65/D66, 13694; task #64 refetch 14646–14752). Wiring a trend remedy is moot |
| DEV-D50 | 13111, 13155, 16816, 16840, 16846 | BH vs BY: adopt dependence-robust correction? | `research/fdr_method_comparison.py` settled it (16846) |
| DEV-D51 | 13357, 13360, 13396 | BUG-D63 placeholder contamination; injectable manifest path (#44) | analysis.py:6211/6229/6352 `manifest_path_override` |
| DEV-D52 | 13559, 13603, 15552 | HMM trade-timing cluster robustness | Task #47 (15550–15575) |
| DEV-D53 | 13780, 13841, 13844, 14332, 14334 | DD cache remediation; Phase 8 rerun; task #64 clean rerun | 14303 (analysis complete); 14646 (task #64 rerun) |
| DEV-D54 | 13888, 13955, 13983 | Cross-TF divergence program; k-BAHC comparison arm | `research/cross_timeframe_divergence.py`; `research/k_bahc_covariance_cleaning.py` (18290) |
| DEV-D55 | 14416, 14418 | 6M near-miss not reached; BUG-D67 | Task #53 complete (14418) |
| DEV-D56 | 14506, 14508, 16265 | pit_wfa re-test after BUG-D68 | Checkpoint sweep (16263); BUG-D69 fix |
| DEV-D57 | 14578, 14607, 15921 | Train-window/split-ratio sweep | Task #67 (15921) |
| DEV-D58 | 14678, 14685, 14752, 16674, 16751, 16794 | 24→0 1h collapse characterization | 14689; root cause proven (16674) |
| DEV-D59 | 14827, 15723 | BUG-D70 `get_bars` bypass | `bypass_cache` in data.py/data_ibkr.py |
| DEV-D60 | 14887, 14924, 15816, 15844, 15851, 16094, 16096, 16102 | IBKR pagination (#72); isolated re-test | 15721; 16092 |
| DEV-D61 | 14994, 14999, 15001, 15002, 15048, 15049, 15165 | Task #69 pieces; earnings-break vs decoupling classification | 15147; 15646 (task #70 cross-check); `research/earnings_structural_break_correlation.py` |
| DEV-D62 | 16408, 16380 | §7.3.1 comparison arms (persistence, min-history) | 16461 (persistence_sweep result); pit_wfa.py:482/552 |
| DEV-D63 | 16849 (part 1), 18164 | Independent confirmatory test on the 8 candidates | `research/confirmatory_cointegration_check.py` (Johansen/KPSS/PO). See Contradictions re S6 |
| DEV-D64 | 17164, 17167, 17189 | wfa.py / run_storm_grid stale outputs after D71/D72 | Rerun 18036 |
| DEV-D65 | 17280, 17260 | BUG-D75 imputation fit on train only | ml.py:839–845 `train_median` |
| DEV-D66 | 18178 | BUG-D95 persistence design | `debug/_verify_bug_d95_persistence_fix.py`; 18619/18754 |
| DEV-D67 | 12917 | Persist raw per-pair p-values before correlation/BH filtering | BUG-D95 fix persists `all_candidates` per TF (18619) |
| DEV-D68 | 18348, 18354, 18356, 18365–18378 | k-BAHC forced-k and sector-restricted follow-ups | 18365 |
| DEV-D69 | 18466, 18502, 18532–18543, 18652, 18655 | Pearson threshold sensitivity; FELE/MAS discrepancy | 18650 (EG direction asymmetry → both-direction fix 18971) |
| DEV-D70 | 18837, 18886, 18888 | Deep-history derived-TF fallback; price-degeneracy scan on 12 TFs | 18835; 18886 |
| DEV-D71 | 19010, 19038, 19112, 19115, 19118, 19169 | Pending full pipeline + backtest rerun (BUG-D96, EG both directions, ADV proxy) | Capstone reruns 19131ff; later WRDS-era reruns |
| DEV-D72 | 19358, 19365, 19388, 19391, 19392, 19395, 19443, 19714 | WRDS ambiguous tickers (8 symbols); Tier 2/3 run | 19678 cleanup; Tier 3 finished (25361) |
| DEV-D73 | 19575, 22229, 22234 | Which global indices to populate | Ross: "all of them, then liquidity filter" (22234); Thread I built |
| DEV-D74 | 19721, 19733, 19743, 19755, 19790, 19791 | BrokenProcessPool redesign; relaunch episodic scan | 19758 fix; full runs completed (25361, 25432) |
| DEV-D75 | 20140, 20298, 20305, 20394, 20411 | WRDS-primary end-to-end verification; pit_wfa real-universe rerun | 20376 close-out |
| DEV-D76 | 20203, 20360 | Deferred research-topics list; Binance wiring | 20201 sweep; `universe_loader` loads Binance (U2/U3 caveats) |
| DEV-D77 | 20584, 20806, 20821, 21077, 21099 | Rewire confirmed-pairs scripts to PIT adapter (`--pit-safe`) | levy/rough_vol/options_greeks have `--pit-safe` (e.g. research/levy_jump_diffusion.py:137); svm has none → minor residual |
| DEV-D78 | 21001, 21004 | Onset detection calendar-time segment floor | research/structural_break_onset_detection.py:67–84 `min_segment_bars_for_dates` |
| DEV-D79 | 21069, 21071, 21296 | Deferred PIT-safe broad-scale scans (task #9) | 21296 "Task #9 COMPLETE" |
| DEV-D80 | 21120, 21123, 21640 | New paper structure discussion | Reframes 25538, 26893 |
| DEV-D81 | 21388, 21390, 21435, 21438, 21454, 21458, 21474, 21475, 21480, 21503, 23033 | Window sizing choice; intraday scan; adapter real run; 1D `_TF_DIRS` gap; ml PIT training | Steps 2–5 completed (21567); 10y lookback in production (28023) |
| DEV-D82 | 21802, 21803 | IBES analyst estimates | Used by `price_target_pairs_overlay.py` (26658) |
| DEV-D84 | 27068 | `_enrich_with_deep_history` read yfinance-only `DataStore.load()` for its main series | Fixed in the same entry: `_load_main_close()` WRDS-then-yfinance fallback (27070ff) |
| DEV-D85 | 22520 | Thread L event-study function-signature design | Built: local event-study framework (22886) |
| DEV-D86 | 25594 | Dispatch the 4 remaining council lenses on the reframe | Council review results used at 26874 |
| DEV-D83 | 21979, 21982, 22007, 22015, 22060, 22352, 22383, 22384, 22665, 23154, 23157, 28225, 28359, 28380, 28401, 28403 | Thread G Tier-2 params; Kelly untestable; ENTRY_ZSCORE 2→3; zero-effect params; FDR threshold; tensorflow | config.py:742 `ENTRY_ZSCORE=3.0`; HANDOFF:525 (Kelly), 653 (Tier2), 367 (FDR), 313 (tensorflow); 22922 (flat_risk_pct verified) |

Also DONE, compressed (process/infra notes closed by the next entry): 23298/23305 (btrfs add, Ross ran it);
23385/23460 (memo cache and orchestrator → overnight runs 24357); 23511/23513 (GPU benchmark 2–2.8×,
HANDOFF:941); 23756 (uncommitted work → later commits); 23793–23814, 24039, 24114, 24120, 24121, 24198,
24199 (Thread Q paths scoped then built 23894/24117; decay-rate deployed, output file referenced by B7);
24241, 24247 (BLAS speedup measured 24244); 24424 (6 skip-and-log fixes re-exercised by the completed resweep, 24357); 24575, 24702, 24704, 24733, 24782, 24811, 24813, 24901,
24928, 24945, 24961, 25372, 25432, 25443, 25496 (Tier 1/3 scale runs completed 25361/25432); 25239
(ZION/PNC/7267.T: HANDOFF:4585–4595 "not evidence of real data contamination"); 25715 (Phase 2/2b
built 25953); 26040 (Sharpe-citation grep audit done); 26378, 26416 (vol-cache gap → `load_price_series`
fix 26375); 27014, 27022, 27452, 27456, 27461, 27540, 27639, 27669, 27726, 27734 (`clean_mask`
analysis.py:3061, sparse-pair exclusion, regeneration 28066, multivariate study 27817); 26984, 27150
(KPSS/PO NaN traced as a third mechanism); 27121, 27347 (OOM relaunch and pilot completed); 27790–28029,
28159, 28171 (backlog #4–#8, HANDOFF:3345–3420); 27075 (yfinance-era threshold audit, 5 items).

---

## OBSOLETE (9)

| ID | Dev.md line(s) | Item | Why obsolete |
|---|---|---|---|
| DEV-O1 | 3978, 3985 | Re-save persisted half_life fields for the 17 confirmed pairs (padding-contaminated) | That pair set and its spread files have been fully regenerated many times since (latest 28066) |
| DEV-O2 | 4184, 4208, 4461, 5227, 4016, 4029, 4175 | Act on the "~60-idea" Session 10 backlog | 5227: the full list "was never persisted to a file". Top picks were later merged into the author-concept backlog (8854) |
| DEV-O3 | 14322 | Reconcile manifest 42 pairs vs 27 in log | That manifest lineage has been replaced (17-pair 1D manifest, HANDOFF:3360) |
| DEV-O4 | 12555, 12631 | Russell 2000 constituent source | Standing direction is the ~44,700-symbol WRDS universe (CLAUDE.md). Index-constituent scoping is moot |
| DEV-O5 | 21640 | 454-pair PIT-safe set "provisional pending redo" | Replaced by the 182, then 1,375-pair Purity pool (28186) |
| DEV-O6 | 16579, 16592, 16595 | Phases 14/16/17/18 of the July phase plan | Plan replaced by the thread/session structure and the paper reframes. Phase 16 (`report.py` figures) is not tracked anywhere now |
| DEV-O7 | 22424, 22427 | Stray `--dry-run` PID 2116 still running | Process-specific; long gone |
| DEV-O8 | 18113 | Headline result requires pair-set collapse resolution | Superseded by the WRDS-era pair lineage; and now by B2–B4 |
| DEV-O9 | 20453, 20704, 20969, 21761, 22495, 25292 | Misc. one-off notes (inverse-polarity scan, pair-count write-up, untested new modules, unresolved-symbol gating, BXMT/ECL, n=1 claim) | Each answered in place or overtaken by later runs. Nothing actionable remains |

---

## Items that contradict the current code or CODE_REVIEW findings

1. **BUG-D49 "degenerate 1m bars are real, corroborated market data" (4920, 5142–5189, 10647).**
   Development.md concludes the few-distinct-price 1m bars are genuine (market-cap driven) and not a
   fetch defect. CODE_REVIEW D1 (escalated in R8, data.py:1874–1882) shows `_liquidity_filter`
   compares *per-bar* dollar volume to the $1M *daily* threshold at every TF, then forward-fills. That
   produces exactly this signature in liquid mid-caps. `audit_price_degeneracy.py` cannot tell filter
   copies from genuine flat bars. The market-cap "root cause" is very likely the filter's own
   selection rule (smaller caps trade less per bar). → DEV-S01.
2. **Walk-forward retrofit "done" (17776: "All 3 Tier 3.3 files now retrofitted onto genuine
   walk-forward").** CODE_REVIEW R5.2 (confirmed by code): `portfolio_position_sizing_correction.py:129`,
   `eigenvalue_weighted_position_sizing.py:176`, and `graphical_lasso_clusters.py:63–113` still build
   cluster labels from `panel.corr()` over layer1 + layer1_holdout combined. → DEV-S12.
3. **BUG-D58 survivorship fix (BUG_LOG D58, backtest.py:2146–2169).** The fix is present, but it
   compares the removal date against `spread_df.index.max()`, the shared index end, not the symbol's
   own last real bar (CODE_REVIEW B15). A delisted leg whose NaN tail is padded to the shared end
   looks like it "has data" past removal. Development.md's "FIXED" is only partly accurate. → DEV-D43.
4. **"WRDS/CRSP is total-return-adjusted" (CLAUDE.md, repeated across Development.md 20081ff).**
   CODE_REVIEW U4 (confirmed on AAPL): `universe_loader` reads WRDS `close`, which is split-adjusted
   price only. `close_total_return` is never read there. Episodic discovery uses total return while the
   traded spread uses price-only (R1.4). → DEV-S13.
5. **Purity pool "Genuinely PIT-safe" (PAPER.md §7.20; Development.md 21438–21503, 28186ff).** CODE_REVIEW
   S3: `episodic_pairs_adapter.py` never passes `as_of_date`, so the pair set is the union of all windows
   up to build date and is then backtested over its full history. Each window is PIT-safe; the pair
   set is not.
6. **"Tiny 2–3 pair standard-screen result is not a BH artifact" (16846, 16614ff).** It may be an
   artifact of something else. CODE_REVIEW A1 shows `_eg_worker` raises on unequal-length arrays and
   silently drops every pair whose legs have different history start dates, and drops them from BH's
   m too. The "collapse" findings (14646ff, 16612ff) and the FDR-method comparison were computed with
   that bug active. → DEV-S28.
7. **GapFlag/DATA_GAP handling described as working (BUG-D77 17344ff; CLAUDE.md rule 3).** CODE_REVIEW
   B1/D1/D5/D8: persisted spread files contain no DATA_GAP flags. Gaps are forward-filled at cache time,
   and 4h weeknight gaps fall under the FILL limit. The BUG-D77 "real outage incidence" measurement
   (17103) measured flags that cannot appear. → DEV-S25.
8. **DSR/hierarchical DSR "matches deflated_sharpe.py exactly" (09-21 entries, HANDOFF:609/791/1025).**
   CODE_REVIEW R2.1: the merged registry double-counts (1,150 records, 570 unique), so the family DSR
   0.9676 and pooled DSR are computed on duplicated trials.
9. **Confirmatory PO/KPSS test (`confirmatory_cointegration_check.py`, 16849/18164) treated as
   independent confirmation.** CODE_REVIEW S6 (UNVERIFIED, reviewer simulation: 25.7% rejection at
   nominal 10%): the stats.py Phillips-Ouliaris proxy uses univariate DF critical values on estimated
   residuals, and KPSS has the same problem. Check which implementation the confirmatory script calls
   before citing it. → DEV-D63.
10. **Strength predicts PIT survival, "z=3.98, independent" (FINDINGS ~3850, 24667ff).** CODE_REVIEW
    R4.1 (confirmed circular via R6) and R4.2 (normal z-test at x_b=0). → DEV-S18.
11. **Quality admission "fully/mostly fixed" luck-check verdicts (28464; HANDOFF:29–77).** CODE_REVIEW
    group 1: the `batch_freq` calendar-bucket lookahead inflated these. On the re-run the verdicts do
    not survive. → DEV-S10.
12. **ML AUC correction (HANDOFF:113, FINDINGS #72: XGBoost 0.6075 etc.).** CODE_REVIEW R2.3: no
    purging or embargo in ml.py or the LSTM split while labels look forward, so these are not clean
    OOS AUCs. → DEV-S23.
