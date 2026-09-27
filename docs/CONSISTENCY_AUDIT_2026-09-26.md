# Consistency / Honesty / Rules-Compliance Audit — 2026-09-26 (audit step 4)

Read-only on every existing file; this is the only file written. Builds on, and does not redo:
`docs/CODE_REVIEW_2026-09-26.md` (finding IDs B*, A*, D*, S*, U*, M*, C*, R*, P1),
`docs/DEV_OPEN_ITEMS_LEDGER_2026-09-26.md` (DEV-* IDs, "Contradictions" 1-12),
`docs/CITATION_AUDIT_2026-09-26.md` (citation rows #1-#74).

Line references are `file:line` at the working-tree state of 2026-09-26 (HEAD 43eff410 plus the
uncommitted edits to backtest.py/ml.py/portfolio_sim.py). "P" = PAPER.md, "M" = PAPER_MAGNITUDE.md,
"R" = README.md, "F" = docs/FINDINGS.md, "H" = docs/HANDOFF.md, "BL" = docs/BUG_LOG.md,
"CL" = CLAUDE.md, "CT" = CONTRIBUTING.md, "Dev" = Development.md.

Where I re-checked code myself (beyond the three input audits) it is marked **[re-verified]**.

---

## Summary counts

| Item | Count |
|---|---|
| Section 2 claims tabled | 69 (README 15, PAPER 34, PAPER_MAGNITUDE 20) |
| — MUST-WITHDRAW | 34 (README 6, PAPER 19, PAPER_MAGNITUDE 9) |
| — MUST-QUALIFY | 30 (README 8, PAPER 13, PAPER_MAGNITUDE 9) |
| — UNAFFECTED | 5 |
| Section 3 honesty/integrity findings | 17 |
| Section 4 rule violations (current) | 16 of 18 rules checked (1 not violated, 1 cannot verify), plus 9 stale/false CLAUDE.md statements |
| Section 1 numeric items | 18 (15 cross-document disagreements or stale values; 3 consistent across documents but invalidated by code findings) |
| Section 5 cross-doc structure findings | 9 (BUG_LOG: every line pointer checked, 2 wrong; 49 rows have no line pointer; 1 entry has no Development.md write-up) |

The single most important structural fact: **no document other than the three 09-26 audit
ledgers reflects today's code review.** HANDOFF's newest entry is 2026-09-22 (H:1); Development.md's
newest session is 09-21/22 (Dev:28400); README/PAPER were last touched by commit 43eff410
("9/26 documentation currency pass"), which *added* the DSR-0.9676 / quality-admission / AUC claims
that the code review now invalidates (R:201-218, P:2057-2108).

---

## Section 2 — Claim status after today's code review (main deliverable)

Verdict key: **MUST-WITHDRAW** = the claim as written cannot stand (number or conclusion is
produced by a confirmed bug); **MUST-QUALIFY** = the claim may survive but needs an explicit caveat
or a re-derivation note; **UNAFFECTED** = checked, no confirmed finding bears on it.

### README.md

| # | Claim (short) | Location | Depends on | Verdict |
|---|---|---|---|---|
| R-1 | "182 PIT-safe confirmed pairs" / "genuinely PIT-safe 182-pair set" | R:135-137, R:145 | S3 | MUST-QUALIFY — each window is PIT-safe; the pair set is the union up to build date, then backtested over full history incl. "OOS" (S3). Also superseded by 1,375 (R:192). |
| R-2 | Purity IS −0.679 / OOS −0.834; Hybrid −0.442/−1.125; Tiered/Baseline +1.417/+0.630 | R:145-150 | B2, B3, B4, P1, S3, R1.1, U4 | MUST-WITHDRAW (numbers). Already marked superseded at R:197-198, but still printed as "the honest, uncontaminated result" (R:146). |
| R-3 | 1,375 pairs, "causally point-in-time-safe"; unconstrained −0.218, capsim −0.7584 | R:189-199 | S3, R1.6, R1.1, U4, B2-B4, P1 | MUST-WITHDRAW (Sharpes); MUST-QUALIFY the pool (pair-level FDR ≤9.1%, 498/929 GVKEY legs in local currency). |
| R-4 | All 3 gates flip unconstrained Sharpe to +0.35/+0.39/+0.43, "confirmed OOS", 100th percentile, p≈0.0000, "strongest statistical evidence to date" | R:201-206 | B2 (β-drift = all sampled positive P&L), B3, B4, P1, S3, B8 | MUST-WITHDRAW. S3 notes the upward selection bias does *not* protect the positive gate results. |
| R-5 | Family DSR 0.9676 (n=39) "confirms this is not a multiple-testing artifact" | R:207-210 | R2.1, B2-B4, B11 | MUST-WITHDRAW. |
| R-6 | Quality-ranked admission "fixed a real, substantial share"; squeeze "genuine positive outlier", momentum "neutral"; "rank candidate trades within each day" | R:211-218 | Group 1 #1-#2 (FIXED lookahead), B2-B4 | MUST-WITHDRAW. The within-day ranking described at R:213-214 is the lookahead mechanism now removed from code (backtest.py diff, `--quality-admission-batch-freq` deleted); re-run verdicts do not survive (CODE_REVIEW:26-31). |
| R-7 | WRDS = "CRSP total-return-adjusted, Compustat Global split-only as a disclosed fallback" | R:62-63, R:227-230 | U4, R1.1, R1.4 | MUST-QUALIFY — `universe_loader` reads price-only `close`; Compustat Global is local currency with no FX, which is not disclosed anywhere in R. |
| R-8 | GapFlag: DATA_GAP bars masked, "never silently forward-filled" | R:237-239 | D1, B1 (latent), D5/D8 (UNVERIFIED) | MUST-QUALIFY — gaps are forward-filled at cache time; persisted spread files contain no DATA_GAP flags (B1). |
| R-9 | EG null calibration "refuted": FP rate 7.75-12.75% | R:86-96 | R6.3 | MUST-QUALIFY — harness is one-direction `coint`, not the production call; R also omits P:666-680's "pre-WRDS, not re-derived" flag. |
| R-10 | IQV/Q@1D: 40 trades, WR=0%, Sharpe=−13986.57, "verified this is a real result, not a bug" | R:130-132 | B3 (log-units × shares vs dollar cost), B11, B2 | MUST-WITHDRAW. A Sharpe of −13,987 is the signature of the unit mix, not a strategy property. |
| R-11 | Known-biases: "genuinely PIT-safe episodic alternative … 182 vs. 3" | R:314-323 | S3, A1 | MUST-QUALIFY — the "3" standard-screen count was produced with A1 active (EG silently skipped every pair with unequal history start). Also stale (1,375). |
| R-12 | "Every rolling-window calculation is strictly causal" | R:240-243 | A2 (CONFIRMED-LATENT), R7.1, A4 (UNVERIFIED) | MUST-QUALIFY (low) — warm-up bars use full-sample β (0.02% of trades); true for `.rolling()` itself, not for every derived window parameter. |
| R-13 | Pre-WRDS provenance: "IS Sharpe ~5.8-8.5 … deflated Sharpe z~9.5 IS/2.9 OOS" | R:154-157 | B2-B4, B11 | MUST-QUALIFY — already "not current", but should also say the P&L engine itself was wrong. |
| R-14 | Universe "spanning … foreign exchange" | R:40-43 | D1 | MUST-QUALIFY — EUR.USD/GBP.USD/AUD.USD 1day closes are 100% NaN in the yfinance cache (D1). |
| R-15 | NTRS/STT **and SHW/UNP** "pass full-sample EG p<0.005 while failing" last 5y | R:79-82 | (none of the listed IDs) | UNAFFECTED by code findings, but **stale** — P:640-658 says SHW/UNP does not replicate on WRDS (0.061 / 0.054). See §1 N-12. |

### PAPER.md

| # | Claim (short) | Location | Depends on | Verdict |
|---|---|---|---|---|
| P-1 | Headline: the PIT strategy "loses money, both in-sample and out-of-sample, robustly across a parameter sweep"; −0.679 / −0.834; sweep OOS range −1.150 to −0.179 | P:15-26, P:93-95, P:177-196, P:2658-2701 | B2, B3, B4, P1, B11, S3, R1.1, U4 | MUST-WITHDRAW (numbers and "robust"). Also internally stale: P:2708-2730 says this table is superseded. |
| P-2 | Purity "Genuinely PIT-safe"; discovery "gated so that no window's confirmation can see data from after its own as-of date"; "causally point-in-time-safe methodology throughout" | P:2646-2649, P:2663, P:2720; also P:7, P:21, P:90, P:179, P:939 | S3 | MUST-WITHDRAW the pair-set-level PIT claim (per-window statement at P:2648 is true; the conclusion drawn from it is not). |
| P-3 | Parameter-sensitivity sweep table (ENTRY_ZSCORE, hedge, sizing) | P:2680-2701 | B2-B4, P1, R2.2 | MUST-WITHDRAW. |
| P-4 | §7.21: gates flip to +0.35/+0.39/+0.43 IS, +0.45/+0.24/+0.50 OOS, "real, out-of-sample-confirmed"; 100th pct p≈0.0000 | P:2748-2754 | B2-B4, P1, S3, B8 | MUST-WITHDRAW. |
| P-5 | §7.22(1): chronological admission taken −0.27 vs skipped +0.40, 0.7th percentile | P:2766-2773 | B2-B4; R2.7 (UNVERIFIED: Sharpe comparison biased by diversification) | MUST-WITHDRAW (numbers). |
| P-6 | §7.22(2): family DSR = 0.9676 (z=1.85), n=39; pooled 0.0000 (z=−37.94); "large enough to trust" | P:2774-2786 | R2.1, B2-B4, B11 | MUST-WITHDRAW. |
| P-7 | §7.22(3): Tier-2 grid "every Sharpe negative"; correlation-exit "dramatically WORSE" | P:2786-2795 | B2-B4, P1; R2.2 | MUST-WITHDRAW. |
| P-8 | α=0.01 pool: "598 pairs, down from 1,375 … 61% shrinkage"; −0.203 vs −0.218; capsim −1.4682 | P:2797-2804 | B2-B4, R1.6; arithmetic error | MUST-WITHDRAW (Sharpes); correct the shrinkage (598/1,375 = 56.5%; 61% is 360/929 from a different scan, §1 N-9). |
| P-9 | Quality-ranked admission beats FIFO 6/6, "rank candidate trades within each day" | P:2806-2815 | Group 1 #1-#2, B2-B4 | MUST-WITHDRAW. |
| P-10 | §7.10: AUC 0.6075 / 0.5897 / 0.5516 "real, non-trivial predictive signal"; Youden recalibration 53.45% vs 54.49% | P:2088-2108 | R2.3 (no purge/embargo), R4.10 (TE feature lookahead — `te_directional_diff`, `te_significance` are in `ml._FEATURE_COLS` **[re-verified]**), Group 1 #3 | MUST-WITHDRAW (AUCs as OOS evidence; recalibration figures are on the superseded raw-accuracy metric — balanced accuracy 57.72% vs 57.64%, CODE_REVIEW:23). |
| P-11 | White (2000) Reality Check: IS p=0.559, OOS p=0.546; "Correct p-value under multiple testing"; fix "correctly centers the null near the realized statistic"; "not that the strategy lacks edge" | P:431-442, P:458, P:497, P:1236-1296 (esp. P:1260-1264, P:1283-1287) | S5 | MUST-WITHDRAW. P:1262-1264 presents the bug's signature (null centred on realized, p≈0.5) as the evidence the fix worked. |
| P-12 | "positive per-pair total P&L and win rates (60-84%) … argue for real per-pair skill" | P:1287-1296 | B2, B3 | MUST-WITHDRAW — on sampled 1D trades B2 moved win rate 21.2% → 45.6% and flipped 49% of trade signs; win rate is not "unaffected". |
| P-13 | §6.7 DSR N=52, IS z=9.52, OOS z=2.90 "does not explain away the headline result" | P:1298-1346 | B2-B4, B11 (S11/S12 UNVERIFIED) | MUST-QUALIFY (already pre-WRDS provenance per P:198-213; add that the P&L itself is invalid). |
| P-14 | Pre-WRDS headline OOS Sharpe 5.2155 / IS 5.8044 | P:79-80, P:166-176, P:1272-1276, P:1422 | B2-B4, B11 | MUST-QUALIFY (provenance label + P&L invalidation). |
| P-15 | "the paper's headline 5.24 OOS Sharpe is a real, correctly [computed]…" | P:2861 | B2-B4, B11 | MUST-WITHDRAW (also contradicts P:177 which names §7.20 as the headline, and P:168's 5.2155). |
| P-16 | EG-null Monte Carlo "runs the production EG-test code itself"; FP 7.75-12.75% | P:138-151, P:700-742 (P:702) | R6.3 | MUST-WITHDRAW P:701-703 ("production code"); MUST-QUALIFY the conclusion. |
| P-17 | Raw rejection-rate table: 1D 2 of 122,082 (0.0016%, "~3,000x below chance") | P:688-693 | A1 | MUST-QUALIFY — A1 silently drops every pair with unequal history start *and* removes it from BH's m; whether these counts include or exclude failed tests could not be determined from the docs. Re-derive after A1. |
| P-18 | §4.2 NTRS/STT full-sample p≈0.00005 vs last-5y p=0.561 on CRSP TR data | P:615-638 | U4, A1 checked | UNAFFECTED — `research/durability_vs_currency_wrds.py:28` reads `close_total_return` and `:33-44` aligns both legs before `_eg_worker` **[re-verified]**. R8.12 (power of 5y test) remains UNVERIFIED. |
| P-19 | §3: CRSP "total-return-adjusted"; 3-pair WRDS static set | P:531-558 | U4, A1 | MUST-QUALIFY. |
| P-20 | §6.3 EVT: 12/29 pairs trade, 290 trades, IS Sharpe 0.2389 | P:1184-1195 | B2-B4 | MUST-QUALIFY (Sharpe); trade counts unaffected. |
| P-21 | News-impact asymmetry: "clean null … `garch_stop`'s symmetric design is validated" | P:2224-2229 | R8.1 | MUST-WITHDRAW. |
| P-22 | Grid bootstrap: "Every confirmed pair's CI sits comfortably below 1"; PNC/ZION [0.9990, 0.9990] | P:2247-2254 | R6.5 (+ D3/D4 for the 4h series) | MUST-WITHDRAW. |
| P-23 | Multiscale entropy "rising toward the white-noise level", Costa et al. | P:2309-2313 | R8.4 | MUST-WITHDRAW (or relabel as per-scale-renormalized SampEn). |
| P-24 | Network momentum "a genuine +0.046 incremental edge" | P:2340-2344 | R8.3 | MUST-QUALIFY — signal and target share r_j[t+1] by construction; drop "genuine edge". |
| P-25 | Inverse-cluster-size sizing "wins on Sharpe (0.7216)" | P:2335-2338 | R5.2, B2-B4 | MUST-QUALIFY. |
| P-26 | AFML Ch. 15 per-pair precision/frequency (CVX/OXY 42.9%, KVUE/KMB 43.8%) | P:2231-2236 | R5.3 (OLS+Kalman duplicates), B4 | MUST-QUALIFY. |
| P-27 | Beta hedging "makes every risk-adjusted metric WORSE" (Sharpe 6.0581 → 0.5019) | P:2544-2556 | R7.3 | MUST-WITHDRAW — exit-booked unhedged P&L vs daily-MTM hedge makes the hedged Sharpe lower by construction. |
| P-28 | Confidence-score filter negative result; reversion-speed category "dominant driver" | P:2556-2566 | R7.1, R7.2 (UNVERIFIED), B2-B4 | MUST-QUALIFY. |
| P-29 | Sequential bootstrap +3.1pp, 10 seeds 47.9-72.9% | P:2583-2608 | R2.3; R4.6/R4.7 UNVERIFIED | MUST-QUALIFY. |
| P-30 | TE "wired into `ml.py` as a genuine feature" | P:3207-3220 | R4.10 | MUST-QUALIFY (full-history pair-level TE attached to every event = lookahead). |
| P-31 | §7.3.1 PIT WFA 1h: −1.0121 (32 trades), +0.2547 (5 trades) | P:1599-1696 | B2-B4, P1; D1, D3/D4 (1h yfinance data); S1 (UNVERIFIED) | MUST-QUALIFY. |
| P-32 | Bias budget: "DSR says the OOS Sharpe is likely genuine" | P:2253-2258 | B2-B4, S5, B11 | MUST-WITHDRAW. |
| P-33 | §4.5 calendar-padding artifact "remains an active, citable finding" | P:207-213, P:777-824 | none confirmed (U3/R2.9 are the same family, UNVERIFIED) | UNAFFECTED. |
| P-34 | §7.12 crisis stress test: dislocation 62% vs 20% calm | P:2158-2198 | R5.5-R5.7 (UNVERIFIED) | MUST-QUALIFY — see §3 H-10 (controls added after first run; "calm" windows include 2018-02/03 stress). |

### PAPER_MAGNITUDE.md

| # | Claim (short) | Location | Depends on | Verdict |
|---|---|---|---|---|
| M-1 | Primary contribution: a PIT-confirmed set "traded and lost money, −1.0121 Sharpe on 32 trades" | M:82-89, M:462-482 | B2-B4, P1; D1, D3/D4 (1h data); S1 (UNVERIFIED) | MUST-QUALIFY (Sharpe must be re-derived; pair set built on 1h cache with the per-bar $1M liquidity filter and 1h snapping lookahead). |
| M-2 | Earlier test: "zero overlap … lost money at every fold (−0.72 to −1.04)" is "a real property of the discovery process … not a bug in the diagnostic" | M:86-89, M:492-507 | BUG-D68 (BL:85), A1, B2-B4 | MUST-WITHDRAW as evidence — BL:85 root-caused this exact result to 95.6% of PIT pairs passing only via the unreliable short-window override, and says the fix was "NOT yet re-tested against pit_wfa.py". |
| M-3 | Pooled-across-folds Sharpe +0.1845 / +0.1285; "a real, correctly-computed consequence of this weighting, not an artifact of a coding error"; fold2 −0.2589 → +0.2175 | M:606-635, M:1500-1530 (M:1526-1527) | R5.1, P1, B2-B4 | MUST-WITHDRAW — per-fold P&L spans only first→last exit, not the test window (fold1: 11 trades 1946-09→1957-09 in a ~1946-1976 window). |
| M-4 | Crisis confirmation rate 0.248% vs 0.146% (naive z=2.77) and concentration 93.1% in 2 of 12 episodes, binomial p=0.000006 | M:114-128 | R3.2, R3.3, R3.4 (all UNVERIFIED) | MUST-QUALIFY (already reported as non-significant; the concentration p is post-hoc). |
| M-5 | Persistence 91.0% vs 78.7%, cluster-robust p=0.032 — "the counter-intuitive result the paper leans on" | M:128-135, M:297, M:712-727 | R3.1 (CONFIRMED), R6.9 (UNVERIFIED) | MUST-WITHDRAW pending recode ("reappears" is coded as any regime ≠ first, docstring says non-crisis; crisis-first pairs trivially reappear). |
| M-6 | Same-sector vs cross-sector split (93.3% vs 92.1%; cross-sector 99.4% vs 94.1%, p=0.000018) | M:860-880 | R3.7 (CONFIRMED), R3.1 | MUST-WITHDRAW — see §3 H-8. |
| M-7 | Residual-SPY factor test: effect lives in 6.7% factor-surviving subset; "confound is real, not total" | M:140-145, M:~840-855 | R4.3 (UNVERIFIED); citation #70 (Forbes-Rigobon) | MUST-QUALIFY. |
| M-8 | Survivorship: 0.34% vs 0.30%, z=1.26, p=0.21, "no strong confound" | M:146-152 | R3.10, R3.11 (UNVERIFIED) | MUST-QUALIFY. |
| M-9 | Both findings "point-in-time-safe by construction" | M:166-167 | S3 | MUST-WITHDRAW wording. |
| M-10 | §4×§5 interaction: 1.72% (16/929) vs 0.0003% (2/637,166), z=98.7, p≈0 | M:994-1010 | R4.2 (CONFIRMED pooled normal z at x=2 and x=16), R4.1 | MUST-WITHDRAW the z/p; the raw counts can stay with an exact test. |
| M-11 | §7.7 "all 16 overlapping pairs are strong … z=3.98, p=0.0001 … a second, independent confirmation" | M:1459-1482; repeated M:1015-1019, M:1625, M:1746 | R4.1/R6 (CONFIRMED circular), R4.2, R6.2 | MUST-WITHDRAW (at all four locations). |
| M-12 | §7.1: BH-FDR at 5,003,637 tests "controls the expected proportion of false discoveries" for the confirmed pairs | M:1092-1110 | R1.6 (pair-level FDR ≤ 9.1%, 81% single-window) | MUST-QUALIFY. |
| M-13 | §7.1: hierarchical DSR, 990 trials, pooled DSR 0.0000 (z to −63.99), family DSR 0.9676 | M:1165-1195 | R2.1 (1,150 records / 570 unique), B2-B4, B11 | MUST-WITHDRAW. |
| M-14 | §7.2: "Only 8.18% of all detected regime spans … are ever genuinely cointegrated"; strong/moderate/weak 18,827/18,883/18,826 | M:1202-1233 | R6.2 (46% of coint spans are sub-3-window leading spans, 9,120 labelled strong) | MUST-QUALIFY. |
| M-15 | GGR "computed once over the full available history … validate only the trading rule causally" | M:95-101, M:266-270, M:1027 | citation audit #9 | MUST-WITHDRAW (misattribution; GGR formation is rolling/PIT). |
| M-16 | "~1,576-symbol WRDS-primary universe" for the §4 table | M:102-103, M:453 | factual (P:1603: 1,576 symbols *with cached 1h data*; WRDS has no intraday, M:1496) | MUST-QUALIFY (§1 N-4). |
| M-17 | Universe includes forex/commodity/futures ("~44,700 … forex, commodity, futures") | M:73-75 | D1 | MUST-QUALIFY. |
| M-18 | "the 5.24 OOS Sharpe headline" of the companion paper | M:56, M:1711 | B2-B4, B11; stale | MUST-QUALIFY. |
| M-19 | §7.3 SPAC NAV clustering, §7.4 jumps, §7.5 15.8σ artifact, §7.6 complexity | M:1244-1458 | none of the listed confirmed IDs (D1 could interact with §7.4; not checked) | UNAFFECTED (by confirmed findings). |
| M-20 | Macro-regime / publication-lag dependent claims | (none found; grep for CPI/FEDFUNDS/publication lag in P/M/R returns nothing) | M7 | UNAFFECTED (no paper claim depends on M7; but see §3 H-12 for BL:122's "FIXED"). |

---

## Section 3 — Honesty / integrity

**H-1. "All citations were verified by direct source lookup" (P:252).** False. P's reference list
marks Ref#15-#32 [TBD] (P:3451-3635), 31 in-text works have no reference entry, and the citation
audit found 9 misattributions and 10 minor bibliographic errors (CITATION_AUDIT:25-45). Must be
replaced with an accurate sourcing statement.

**H-2. "Genuinely PIT-safe" / "causally point-in-time-safe" / "PIT-safe by construction"**
(P:7, P:21, P:90, P:179, P:939, P:2646-2648, P:2663, P:2720; R:145, R:191, R:319; M:167; F:1247;
Dev ×2). S3: `episodic_pairs_adapter.py` never passes `as_of_date`; the pair set is the union of all
windows up to build date, then backtested over full history. This is the pair-level analogue of
BUG-D112 (BL:193-200), which the docs describe as fixed and cite as the reason the 182/1,375 set is
"genuinely" PIT-safe (R:137-143, P:2650). The claim was repeated with increasing emphasis
("genuinely", "by construction") without a test that would have caught it.

**H-3. White's Reality Check (P:431-442, 458, 497, 1236-1296).** The document treats the null
centring on the realized statistic as proof the fix is correct (P:1262-1264: "correctly centers
the null near the realized statistic (realized 4.59 vs. perm_mean 4.71, p=0.51)"). That is the S5
defect's signature, not a validation, and the text then uses p≈0.55 to argue the holdout is "not
yet long enough … not that the strategy lacks edge" (P:1283-1285). The §2.4 table claims "Correct
p-value under multiple testing" (P:458) for a single-series, non-demeaned test.

**H-4. "FIXED" statuses the code does not support** (builds on ledger Contradictions 3, 7):
- BL:73 BUG-D58 "FIXED" — B15: compares removal date against the shared index end, not the
  symbol's last real bar.
- BL:94 BUG-D77 "FIXED … Real-data re-check: all 10 currently-relevant pairs match the original
  convention exactly (confirmed no-op, as predicted)" — B1/D1: no DATA_GAP flag survives into the
  persisted spreads, so a no-op is guaranteed whether or not the fix works.
- BL:122 BUG-D103 "FIXED" (CPI 15d, FEDFUNDS 5d) — M7: lags added to FRED's start-of-month stamp,
  so CPI is visible ~4 weeks early. The verify script tested the lag mechanics, not the anchor date.
- BL:85 BUG-D68 "FIXED" but "NOT yet re-tested against pit_wfa.py itself", while M:492-507 still
  presents the pre-fix result as "a real property of the discovery process … not a bug".
- Dev:17776 walk-forward retrofit "done" — R5.2 (ledger Contradiction 2).

**H-5. "Not an artifact of a coding error" (M:1526-1527)** for the pooled WFA Sharpe. R5.1 is a
coding error in exactly that construction (fold P&L spans first→last exit, not the fold window).

**H-6. Outcome-informed choice: quality-admission ranking direction.** P:2813-2815 discloses "the
winning direction per gate was chosen by testing both, not derived ex-ante". R:213-216 ("using each
gate's own empirically-best ranking direction") and H:29-75 ("Fully fixed" / "Mostly fixed") do
not state it plainly, and H:66-69 presents the result as "consistent with, and strengthens" F#73.
The 09-26 re-run (CODE_REVIEW:26-31) shows the verdicts were produced by the lookahead.

**H-7. Outcome-informed choice: sweep flag `--quality-admission-ascending`** (backtest.py help text,
"Added same night as the flag itself: corr(|entry_z|, pnl_net)…") was added after observing the
correlation on the same data it was then evaluated on. Not disclosed in P/R.

**H-8. Outcome-informed, asymmetric exclusion in the same-sector test** (R3.7;
`research/crisis_regime_same_sector_test.py:128-145` **[re-verified]**). The comment says the first
run "showed a flipped, highly-significant result" and the censoring was added afterwards. The
filter keeps every non-crisis pair regardless of date and drops only crisis-first pairs after a
hardcoded 2022-06-01; `censor_cutoff` is computed and unused. M:870-874 and F:2498-2502 disclose
that the exclusion followed a flipped first run, but **not** that it is one-sided, and describe it
as "matching the main analysis's own right-censoring treatment", which was not checked in this
audit. This needs full disclosure or a symmetric re-run.

**H-9. Crisis persistence result presented as "the counter-intuitive result the paper leans on"**
(M:723-727) while its coding (R3.1) makes crisis-first reappearance nearly automatic. No disclosure
of the coding choice exists in M or F.

**H-10. Stress-test calm controls added after the first run** (`research/stress_test_replication.py:86-95`
comment **[re-verified]**). P:2172-2178 says the controls "were run through the identical test
before drawing any conclusion" — true in sequence, but it does not say the control set was chosen
after seeing the crisis results, and the "calm" 2018-02-19→04-30 window follows the Feb-2018 VIX
spike (R5.6, UNVERIFIED).

**H-11. Circular "independent confirmation"** (M:1459-1482, M:1015-1019): strength terciles are fit
on full-history windows that include the PIT cutoffs' own post-cutoff data (R4.1 via R6). Calling it
"methodologically independent" is not supported.

**H-12. Commit 43eff410's message** says Development.md "is current as of this pass", while the
same commit indexed BUG-D114 in BL:270 with no Development.md write-up (`grep -c "BUG-D114"
Development.md` = 0 **[re-verified]**). BL's own contract (BL:3-8) is "pure index … every entry
… pointer to the full write-up".

**H-13. Uncommitted code fixes not recorded in Development.md** (CLAUDE.md rule 8). `git diff`
shows the Group-1 fixes in backtest.py/ml.py/portfolio_sim.py and two verify scripts; Development.md
has no 09-26 entry (last section Dev:28400).

**H-14. "Honest, uncontaminated result" (R:146)** for a number now known to be computed on broken
P&L (B2-B4) and a lookahead pair set (S3). The rhetoric of honesty is attached to numbers that were
never independently re-derived. This recurs: "strongest statistical confirmation this project has
produced" (P:2752), "at a trial count large enough to trust" (P:2781), "Real, decisive result"
(M:1470).

**H-15. "Every numeric claim below is … cross-checked against the underlying parquet before being
written here" (M:29-33).** Contradicted by M:102/453 (1,576-symbol 1h cache called "WRDS-primary"),
M:693/M:45 (production count "29", superseded 09-13 by 17/19), and the 929-vs-1,375 conflation
(§1 N-8).

**H-16. Rule 6/7 disclosure missing for the current headline claims.** None of R:189-218,
P:2733-2815 or F#68-#73 states: the IS/OOS calendar ranges (the holdout is 80% of each pair's own
bars, B8 — not a common date), the hedge method (default `--hedge both` pools OLS and Kalman
duplicates, B4; backtest.py:2200 **[re-verified]**), ENTRY_ZSCORE (3.0) / STOP_ZSCORE (3.5)
(config.py:742, 757), the pool snapshot (the 1,375-pair `purity_pairs.parquet` exists only on
CachyOS — CODE_REVIEW:197-198), the currency treatment of the 498/929 GVKEY-leg pairs, or that
yfinance 1day files end 2026-06-17 for 227/300 sampled symbols (D2). The canonical home for data
ranges is circular and missing (§4 V-16).

**H-17. Survivorship disclosure is inconsistent.** R:312-313 and CL:48 say the universe is
"current-constituent-only"; R:46-48, CL:10-16 say the standing universe is the full WRDS market
(which includes delisted CRSP names), while DEV-001 shows the delisting registry has no consumer.
Neither statement describes what the PIT path actually uses; M:146-152 tests survivorship on 20.6%
of the universe. Rule 6 requires one accurate statement.

---

## Section 4 — Rules compliance

### Architecture rules (CL:29-53)

| # | Rule | Status | Evidence |
|---|---|---|---|
| V-1 | Rule 1: data.py fetches, analysis.py analyzes | Holds for analysis.py (analysis.py:6615 `build(connect=False, fetch=False)`). **Partial violation** in research/: `research/risk_neutral_density.py:197`, `data_contamination_scan.py:184`, `international_liquidity_filter.py:154`, `investigate_price_degeneracy_cause.py:28`, `annotate_symbol_metadata.py:32` import yfinance directly **[re-verified]**. | minor |
| V-2 | Rule 2: "CRSP total-return-adjusted" | **Violated.** `universe_loader` reads WRDS `close` (price-only); `close_total_return` never read (U4, AAPL 125.01 vs TR 158.52 vs yf 121.26). Discovery uses TR, traded spread uses price-only (R1.4). Compustat Global in local currency, no FX (R1.1). | CL:33-34 |
| V-3 | Rule 2: "IBKR's cache is the only source … for real intraday depth"; "IBKR has zero forex/commodity data" | **Contradicted by other docs.** `research/intraday_episodic_scan.py:136-142` builds its intraday universe from `DataStore.load` (yfinance cache) **[re-verified]**; R:66 "everything intraday remain[s] yfinance-sourced"; P:541-542 "forex intraday remains IBKR". | CL:37-38 |
| V-4 | Rule 3: GapFlag / DATA_GAP masked, never forward-filled | **Violated in practice.** D1 (per-bar $1M threshold NaNs then ffills at every TF; 573/1,697 1day files >20% zero-change bars), D8, B1 (no DATA_GAP flag in any persisted spread), D5 (UNVERIFIED), U3 (no gap_flag on the universe_loader path), R7.9/R2.8/R2.9 (research scripts fillna/ffill). | CL:39-42 |
| V-5 | Rule 4: "verified against a reproducing test before it's presented as done" | **Violated** for BUG-D58, D77, D103, D68 (H-4). | BL:73, 94, 122, 85 |
| V-6 | Rule 6: never silently correct away a known bias / always disclose | **Violated** for S3 (undisclosed pair-level lookahead), R3.7 (asymmetric exclusion), R1.1 (no FX — undisclosed), B8 (per-pair holdout). | §3 |
| V-7 | Rule 7: honest over impressive; data range + universe snapshot + params for every headline claim | **Violated** (H-14, H-16). | R:201-218, P:2733-2815 |
| V-8 | Rule 8: document tried-and-reverted in DEVELOPMENT.md | **Currently unmet** for the 09-26 fixes (H-13) and BUG-D114 (H-12). | Dev:28400 last |

### Known-Resolved Issues (CL:55-80)

| # | Rule | Status | Evidence |
|---|---|---|---|
| V-9 | 4h resampled from 1h with session-aligned bins | **Violated on IBKR / yfinance-fallback paths:** D3 — `snap_timestamps` keeps one 4h bar per session; the 13:30 bar overwrites 09:30 (4h lookahead). D4 feeds the 1h cache and the 4h resample. | CL:66-68 |
| V-10 | Never cache an empty constituent-fetch result | **Violated:** data.py:5735-5738 calls `_save_sp500_cache(tickers)` straight after the Wikipedia parse with no length check (the iShares branch at :5755 has `> 400`) **[re-verified]** (D14). | CL:72 |
| V-11 | Universe-size guard must stay | **Guard present only on the legacy path** (data.py:3964). The standing-direction path `universe_loader.load_full_universe()` has no guard and drops unreadable files uncounted (U1); this hid 1,647 truncated WRDS files on CachyOS (~2.8% of symbols) since mid-August (D16). The rule's purpose is defeated on the path CL:10-16 mandates. | CL:73-74 |
| V-12 | `ibkr_supplement_reader.py`, not `data_ibkr.py`, for reads | **Violated:** `research/tail_dependence_deep.py:50` `from data_ibkr import load_supplement, merge_with_yfinance` **[re-verified]**. | CL:79-80 |
| — | yfinance session, period limits, 8h removal, S&P 400/600 scraper, CFTC ID | No violation found (macro.py:411-429 uses `6dca-aqww`; no custom `requests.Session()` in data.py). Not exhaustively checked. | — |

### Working Style (CL:104-150)

| # | Rule | Status | Evidence |
|---|---|---|---|
| V-13 | Avoid hardcoding; derive worker counts from `os.cpu_count()`; grep for the same literal | **Violated:** `universe_loader.py:131 _IO_WORKERS = 32` (C16) **[re-verified]**; `research/intraday_episodic_scan.py:277 --workers default=6` **[re-verified]** (R1.10); `crisis_regime_same_sector_test.py:138` hardcoded `2022-06-01` (R3.7); `sequential_bootstrap_ml_comparison.py:246 random_state=42` (R4.7, UNVERIFIED). DEV-023 notes the drift guard was never extended past wfa.py/sensitivity.py. | CL:132-138 |
| V-14 | Standing direction: full ~44,700-symbol universe everywhere a script can | **Violated:** `intraday_episodic_scan.py` uses the Step-0 coverage file (~1,576 current constituents) **[re-verified]** (R1.10); `eg_null_calibration_montecarlo.py` samples the yfinance cache (R6.4, UNVERIFIED); DEV-011: 5 scripts never re-run at `load_full_universe()` scale. | CL:10-18 |
| V-15 | Capital-constrained PIT portfolio results are the headline, per-pair diagnostic only | **Violated in presentation:** R:201-210 and P:2748-2754 lead with UNCONSTRAINED pooled-trade Sharpe and a DSR on it; the capsim result is a subordinate clause. P:2783-2785 does say it narrowly. | CL:142-144 |
| V-16 | Never cite a number from memory / an old snapshot; re-derive | **Violated:** P abstract (P:177-186) still cites the superseded 182-pair table as the headline; F#70/H:422-426/P:2799 attribute 929 to "the 1D subset" of the 1,375 pool (it is a different scan run, §1 N-8). | CL:122-131 |
| V-17 | One agent/subagent dispatch at a time for audits | **Cannot verify.** This session lists other active agents (`code-review`, `code-review-2`); if they ran concurrently with this audit, the rule was broken. | CL:117-118 |
| V-18 | New methodology → Ross's buy-in first; research concept never straight to production | Not violated as far as the docs show (quality admission built as opt-in flag; H:192ff says Ross asked). The ranking-direction choice (H-6/H-7) was made in-session without a pre-registered rule. | CL:106-110 |

### CLAUDE.md statements that are stale or false

| # | Statement | Problem |
|---|---|---|
| S-1 | CL:33 "yfinance is primary daily fetch." | Contradicted by the next sentence and R:227 (WRDS primary for daily-and-coarser US). |
| S-2 | CL:34 "CRSP total-return-adjusted, Compustat Global fallback" | U4 (loader is price-only), R1.1 (local currency, no FX). |
| S-3 | CL:37-38 IBKR is "the only source … for real intraday depth"; "zero forex/commodity data" | V-3. |
| S-4 | CL:39-42 GapFlag rule | Describes intended, not actual, behaviour (V-4). |
| S-5 | CL:5 "Reproducibility numbers/data ranges: PAPER.md" | PAPER.md:524 and P:3164 point back to CLAUDE.md sections ("Current canonical data footprint", "Data Test Range & Reproducibility") that do not exist; so does R:284/289. The canonical data-range record is circular and missing. |
| S-6 | CL:26-27 thesis: "predictable … via multiclass ML" | Neither paper's thesis (P:3-4 durability/currency; M:1-2 discovery event); `Config.ML.LABEL_SCHEME = "binary"` (config.py:602). P:2302 also still says "ml.py's 4-class label". |
| S-7 | CL:48 survivorship "(current-constituent-only universe)" | Inconsistent with the standing full-WRDS universe (H-17). |
| S-8 | CL:4/162 `DEVELOPMENT.md` | Tracked file is `Development.md` (`git ls-files`); resolves on Windows only, not on CachyOS. |
| S-9 | CL:10 "~44,700-symbol" | Docs also use 43,883 and 44,840 for the same universe (§1 N-1); none mentions the 59,021-file WRDS cache or the 2,211 alias drop. |

---

## Section 1 — Numeric consistency

| # | Quantity | Where it appears | Problem |
|---|---|---|---|
| N-1 | Merged universe size | 44,700: CL:10, R:46, R:359, CT:177, CT:635, M:73; 43,883: R:178, M:103, M:280, M:454, M:560, M:1494, M:1775, F:3494, H:3356; 44,840: F:2569, CT:458, H:4319, H:5693 ("44,840→17,324"), H:5751-5863 | Three figures for the "same" universe, none dated in place. 43,883 − 2,211 aliases (R:176-179) is never given. WRDS cache holds 59,021 files (CODE_REVIEW:118) and 1,647 are empty on CachyOS (D16), so universe-level CachyOS runs since mid-August used ~2.8% fewer WRDS symbols than any stated count. |
| N-2 | "Current" universe in R | R:287-292 "~1,730 symbols … 1,660 passing" as canonical | Stale (2026-08-03 snapshot) and points at a non-existent CL section. |
| N-3 | pit_wfa universe | P:1603 "1,576 symbols with cached 1h data"; M:102, M:453 "1,576-symbol WRDS-primary universe" | Mislabelled: WRDS carries no intraday (M:1496). |
| N-4 | Confirmed production count | 29: M:45, M:693, P:1117-1123, P:1180-1188; 17/19: R:181-184, P:1101-1103; 27: R:173, P:2620 | M still states 29 as current. |
| N-5 | Purity pool size | 182: R:137, R:145, R:320, P:7, P:182, P:522, P:2650, P:2663, CT:447; 1,375: R:192, P:2724, P:2799, F#70, H:367; 1,382: P:2724, H:2922 | Abstract, Framing and Known-biases still use 182; CT:447 describes the parameter screen as run against the 182 set. |
| N-6 | Purity Sharpe | −0.679/−0.834 (capsim IS/OOS): R:146, P:94, P:182, P:2663; −0.218 (unconstrained IS) / −0.7584 (capsim IS): R:195-196, P:2727, H:367-377 | Not like-for-like: no OOS capsim Purity figure is given for the 1,375 pool at α=0.05 (H:377 "not directly comparable"). So "loses money both IS and OOS" (P:24) has not been re-established on the current pool. |
| N-7 | Old headline OOS Sharpe | 5.2155: P:79, P:168, P:1272, P:1422; "5.24 headline": P:2861, M:56, M:1711, R:427; 5.22: R:116 | Three values for one "headline". |
| N-8 | Tier-3 episodic run | 929 of 7,834,906 (F:2278-2287, run 2026-09-02, Tier-1 base 894,733, 5,003,637 EG tests per M:1097-1099); 1,382 of 7,834,906 (H:2922, run 2026-09-14, Tier-1 base 918,617, 5,753,735 EG tests) | Two different runs report the identical candidate count with different Tier-1 bases and confirmed counts. H:422-426 and F:4239 explain 929 vs 1,375 as "1D-only vs 1D+1h+4h"; that is false — H:2827 shows 1,363 of the 1,375 rows are `wrds_1D`. The 5,003,637-row windows file (09-02) is what F#70, R1.6 and M §5 use. |
| N-9 | FDR-threshold shrinkage | P:2799-2800 "598 pairs, down from 1,375 … 61% shrinkage"; F:4239 / H:422 "0.01 → 360 (61%)" | 61% is 360/929 (09-02 windows file); 598/1,375 is 56.5%. The 598-pair pool (H:369) was built from the current checkpoint, so the two numbers come from different runs. |
| N-10 | Trial registry size | 990: M:1170-1174, F:4046, F:4092, H:615, H:1025-1071 | CODE_REVIEW R2.1: 1,150 records, 570 unique; "matches deflated_sharpe.py exactly" false. |
| N-11 | DSR 0.9676 (z=1.85, n=39) | R:208, P:2780, M:1189, F:4130, H:618 | Consistent across docs; invalid per R2.1/B2-B4. |
| N-12 | NTRS/STT & SHW/UNP | R:79-82 (both pass p<0.005, both fail 5y); P:640-658 (SHW/UNP 0.061 / 0.054 on WRDS) | R stale vs P. |
| N-13 | EG-null FP rate | R:90, P:141, P:716-719 (7.75-12.75%) | Consistent; R omits the P:666-680 pre-WRDS flag. |
| N-14 | Luck-check percentiles | P:2770 (0.7th, chronological); H:29-50 (100.0 / 49.1 / 99.7, quality-ranked); CODE_REVIEW:29-30 re-run (squeeze 99.9/93.1, momentum 15.5/28.6, combined 77.9/44.5; taken_better False in all 6) | R and H not updated. |
| N-15 | ML recalibration | P:2102, H:92-93 (53.45% vs 54.49% raw accuracy) | Superseded by balanced accuracy 57.72% vs 57.64% (CODE_REVIEW:23). |
| N-16 | MIN_COINT_FRAC | P:749 and config.py:509 = 0.70; BL:85 (D68) "0.40 primary threshold" | BL wrong (or describes a past value without saying so). |
| N-17 | Paper title | R:19, R:426 "Unwarranted Confidence"; M:1-2 "The Discovery Event: Causal Validity and Regime Information…" | R stale. |
| N-18 | Pre-WRDS DSR | R:156 "z~9.5 IS/2.9 OOS"; P:1327-1330 z=9.52/2.90 | Consistent (both provenance). |

---

## Section 5 — Cross-document structure

**X-1. README "Current Results" vs PAPER headline vs latest HANDOFF.** Three different "current"
stories:
- PAPER (P:15-26, P:177-196): the PIT strategy loses money; headline = 182-pair table.
- README (R:189-218): 1,375-pair pool negative, but gated strategy positive, DSR confirms it,
  quality admission fixes capsim.
- HANDOFF top (H:1-156, 09-22): luck check "fully/mostly fixed", AUC 0.6075 "real ranking power",
  and an arXiv-readiness audit requested (H:8-12). No 09-26 entry.
- CODE_REVIEW (09-26): all P&L numbers invalid (B2-B4, P1), quality-admission verdicts do not
  survive, DSR registry double-counted.
None of the three narrative documents matches the code-review state.

**X-2. PAPER.md contradicts itself on its headline.** P:177 says §7.20 is the headline; P:2861
calls "5.24 OOS" "the paper's headline"; P:2708-2730 says §7.20's table is superseded; the abstract
was not updated after the supersession.

**X-3. PAPER_MAGNITUDE documents the A1 mechanism without propagating it.** M:1126-1133 records that
`DataAligner.align_universe` "silently produces per-symbol-length arrays … which the EG worker's
own try/except swallowed as 'not ok'" and fixed it only in `bh_vs_by_full_universe_1d.py`. The same
mechanism in analysis.py's main path (A1) was never checked, while M:500-504 asserts "the screening
function itself is trustworthy" and Dev:16846 says the small standard-screen result "is not a BH
artifact" (ledger Contradiction 6).

**X-4. FINDINGS vs PAPER summaries.** F#66 (F:3848-3854) calls the strength result "striking,
clean … statistically decisive"; M:1470 calls it "Real, decisive"; both inherit R4.1/R4.2. F#70
(F:4235-4241) states 929 is the 1D subset of the 1,375 pool (N-8); P:2799 then mixes the two runs.
F#73 (F:4424) headline "6/6" is stated without F noting the within-day lookahead now removed.

**X-5. README "Documentation Map" is stale** (R:425: CLAUDE.md carries "a condensed 'Current
State' pointer" — it does not; R:426-427 title and "5.24" headline).

**X-6. CONTRIBUTING.md** repeats "CRSP total-return-adjusted" (CT:104) and describes
`parameter_sensitivity_screen.py` as run against the 182-pair set (CT:447).

**X-7. BUG_LOG pointer check (every row with a `Development.md:LINE` pointer, not a sample).**
A script compared each pointer (±5 lines) against a `BUG-<id>` match in Development.md. The BUG-A
rows (A01-A14) were not checked because they use a different ID scheme.
- Every pointer in the D01-D62 rows (including the 13 pointers in the multi-pointer rows D49, D56,
  D57, D58, D62) resolves within ±5 lines (normal header offset), except the two below.
- **Wrong:** BL:71 D56 "fixed :10958" — actual `### BUG-D56 fixed` at Dev:11006; BL:72 D57
  "found :11076" — actual `### BUG-D57 found` at Dev:11119. Dev:10958 and Dev:11076 are unrelated
  paragraphs (Lo 2002 correction; a design note).
- **No line pointer at all:** BL:79-128 (49 rows, D63-D109 + Tier5/Tier6) cite a date and a
  quoted heading instead of a line, contrary to BL:3-8's stated format.
- **No write-up:** BUG-D114 (BL:270) has zero occurrences in Development.md (H-12).
- **Structure:** D110-D114 are bullets appended below the "How to add a new bug" instructions
  (BL:143ff), outside the tables.
- **Status accuracy:** D58, D68, D77, D103 marked FIXED against CODE_REVIEW B15 / BL's own
  "not re-tested" / B1 / M7 (H-4).

**X-8. HANDOFF parity claim.** H:444-454 "558/558 tracked files now in sync — the whole tracked
codebase genuinely synchronized" is literally about tracked files; it was read as full parity, but
`output/cache/wrds` (untracked) held 1,647 truncated files on CachyOS (D16).

**X-9. Development.md carries the same stale claims** (ledger Contradictions 1-12 already list
them): "total-return-adjusted" (2 hits), "genuinely PIT-safe" (2 hits), BUG-D49 "real market
data" vs D1, walk-forward retrofit "done" vs R5.2.

---

## Required document changes (prioritized)

Priority 1 — withdraw before any external circulation (every item blocks arXiv readiness, H:8-12):

1. **PAPER.md abstract + Framing + §7.20 (P:15-26, P:93-95, P:177-196, P:2658-2701):** withdraw
   all Purity/Hybrid/Tiered/Baseline Sharpes and the sweep table; replace with "pending P&L rebuild
   (B2, B3, B4, P1)". Remove "genuinely/causally PIT-safe" for the pair set (S3). Finding IDs: B2,
   B3, B4, P1, S3, R1.1, U4.
2. **README.md R:189-218 and PAPER.md §7.21-§7.22 (P:2733-2815):** withdraw the gate Sharpes,
   "OOS-confirmed", 100th-percentile, family DSR 0.9676, the Tier-2 grid, the α=0.01 comparison and
   the quality-admission 6/6 and luck-check verdicts. IDs: B2-B4, P1, S3, B8, R2.1, Group 1 #1-#2.
3. **PAPER.md §6.6 / §2.4 / §2.5 (P:431-442, P:458, P:497, P:1236-1296) and P:2253-2258:** withdraw
   the Reality Check p-values and the "fix centres the null" argument; retitle as a
   non-demeaned block bootstrap. ID: S5; citation #55.
4. **PAPER_MAGNITUDE §7.7 and its echoes (M:1459-1482, M:1015-1019, M:1625, M:1746) and M:994-1010:**
   withdraw z=3.98 and z=98.7 as independent evidence. IDs: R4.1, R4.2, R6.
5. **PAPER_MAGNITUDE §5 persistence and same-sector (M:128-135, M:297, M:712-727, M:860-880):**
   withdraw pending a recode of "reappears" and a symmetric-censoring re-run; disclose the
   post-first-run, one-sided exclusion. IDs: R3.1, R3.7.
6. **PAPER_MAGNITUDE §4 (M:86-89, M:492-507):** withdraw the pre-WRDS zero-overlap / −0.72…−1.04
   result as evidence (BUG-D68 root cause, never re-tested); qualify −1.0121 (B2-B4, P1, D1, D3/D4).
7. **PAPER_MAGNITUDE pooled WFA Sharpe (M:606-635, M:1500-1530):** withdraw, including "not an
   artifact of a coding error". IDs: R5.1, P1.
8. **PAPER.md §7.10 (P:2088-2108):** withdraw AUC as out-of-sample evidence and the raw-accuracy
   recalibration numbers. IDs: R2.3, R4.10, Group 1 #3.
9. **PAPER.md research-diagnostic claims:** withdraw P:2224-2229 (R8.1), P:2247-2254 (R6.5),
   P:2309-2313 (R8.4), P:2544-2556 (R7.3), P:1287-1296 (B2), P:2861 (B2-B4); qualify P:2340-2344
   (R8.3), P:2335-2338 (R5.2), P:2231-2236 (R5.3), P:2556-2566 (R7.1), P:3207-3220 (R4.10).
10. **README.md R:130-132:** withdraw IQV/Q Sharpe −13986.57 "real result, not a bug" (B3, B11).
11. **PAPER.md P:252:** replace "All citations were verified by direct source lookup" (citation
    audit). **PAPER_MAGNITUDE M:95-101, M:266-270, M:1027:** fix the GGR misattribution.

Priority 2 — qualify / correct:

12. **Data-source statements** — CL:33-38, R:62-63, R:227-230, P:531-536, CT:104: state that the
    loader uses price-only WRDS `close`, Compustat Global is local-currency with no FX, and resolve
    the IBKR-vs-yfinance intraday contradiction. IDs: U4, R1.1, R1.4.
13. **GapFlag descriptions** — CL:39-42, R:237-239: state the rule is not currently enforced (D1,
    B1, D8; D5 pending).
14. **FDR claims** — M:1092-1110 and any "5% FDR" pair-level wording: pair-level FDR ≤ 9.1%
    (R1.6).
15. **MC calibration** — P:700-742, R:86-96: remove "production EG-test code itself"; add the
    pre-WRDS flag to README (R6.3).
16. **§7.2 episodic spans** (M:1202-1233): qualify for the hysteresis bypass (R6.2).
17. **Numeric reconciliation** — fix N-8/N-9 (929 is the 09-02 run, not a 1D subset; 598/1,375 =
    56.5%); pick one universe figure with a date (N-1); replace M:693/M:45 "29"; unify the old
    headline (N-7); fix R:79-82 (SHW/UNP), R:19/R:426 (title), BL:85 (0.40 vs 0.70).
18. **Rule 7 disclosure block** for every surviving headline claim: IS/OOS calendar ranges, hedge
    method (never pooled — B4), entry/stop z, pool snapshot and location, currency treatment,
    daily-cache end date (D2).

Priority 3 — process records:

19. **Development.md:** add a 09-26 entry for the Group-1 fixes and the audit outcomes (rule 8);
    add the BUG-D114 write-up; annotate BUG-D58/D68/D77/D103 as partially fixed with the code-review
    IDs.
20. **HANDOFF.md:** add a 09-26 top entry superseding the 09-22 luck-check/AUC claims and pointing
    to the four audit files.
21. **BUG_LOG.md:** fix D56/D57 pointers (Dev:11006, Dev:11119); convert D63-D109 to line pointers;
    move D110-D114 into the table.
22. **CLAUDE.md:** fix S-1 to S-9 (especially the circular data-range pointer, S-5, and the thesis
    line, S-6).
23. **Code-side rule violations to schedule (not document edits):** D14 empty-cache guard, a
    universe-size guard and an unreadable-file count in `load_full_universe` (U1/D16),
    `tail_dependence_deep.py` → `ibkr_supplement_reader`, `_IO_WORKERS` / intraday `--workers`
    derived from `os.cpu_count()`, `intraday_episodic_scan.py` onto `load_full_universe`.

### Could not verify

- Whether the P:688-693 rejection-rate counts include A1's silently failed tests.
- Whether the "main analysis's own right-censoring treatment" (M:873, F:2503) is itself symmetric.
- Whether the 1,382-pair 09-14 run saved its own Tier-3 windows file on CachyOS (only the 09-02
  5,003,637-row file is referenced locally).
- Whether other agents ran concurrently with this audit (V-17).
- All UNVERIFIED code-review leads cited above remain leads; verdicts that depend only on them are
  MUST-QUALIFY, never MUST-WITHDRAW.
