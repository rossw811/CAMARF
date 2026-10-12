# Decision sheet — everything that needs Ross (2026-10-12)

One place for every open decision, with a recommendation, cost and dependency for each. Mark each row
**Y** (adopt as recommended), **M** (modify — say how) or **N** (drop). Inputs: `docs/PLAN_OF_ACTION_2026-10-07.md`
(S1–S36 decided), `docs/PLAN_WHILE_WRDS_LOCKED_2026-10-11.md` (Tracks A–E, brainstorm 1–20 approved),
`docs/DATA_SOURCES_SURVEY.md`, `docs/PARAMETER_REGISTRY.md`, `docs/bug_recheck/verdicts.csv`, `docs/ERRATA.md`.
Cost key: **S** < 1 day of my work · **M** 1–3 days · **L** a week+ · **J** = CachyOS compute time.

## State in one paragraph

Four defects found since 10-10 are fixed failing-first and committed: BUG-D115 (crashed tests left out of BH's m),
BUG-D116 (second pass reused the first pass's trades), BUG-D117 (both label→PERMNO maps named the wrong security for
some files; one content-verified map now feeds everything) and the S36 gap (ADR-vs-home-listing pairs; now linked via
CCM + Capital IQ). Measured impact on discovery is small (0 confirmed pairs touched) but not zero, so the plan is to
re-run discovery → pools → second pass. Suite 381/382 (the one failure is the known Act 3 machine difference). Bug
recheck: 311/311 with verdicts. Claims: 12 central claims re-derived (C-001, C-007), 78 to go — most wait for the
re-run. WRDS works again, behind a login guard.

---

## A. Approve now — operations (nothing runs until you say)

| # | Item | Recommendation | Cost |
|---|---|---|---|
| A1 | Re-copy `ciq_link_cusip.parquet` to CachyOS (truncated by a dropped connection) | **Y** | S |
| A2 | Launch `debug/_tmp_chain_rerun_20261012.sh` on CachyOS: volume re-restatement → full suite (stops on any unexplained failure) → primary discovery → intraday → pools → audits → second pre-registered pass with run-time guards | **Y** | J ~2 days |
| A3 | Re-run the volume re-restatement on the Surface's copy of the cache (stopped for low memory) | **Later / optional** — CachyOS holds the canonical cache for runs; do it when the Surface is idle | S |
| A4 | Remove `graphify-out/` (43 MB, tracked) from the working tree — stays in git history | **Y** (git history is the backup) | S |
| A5 | Grid-offset re-runs (63/126/189) on the corrected code | **After the second pass**, as the robustness check it already is (S3 kept grids as a check, not pools) | J ~4 days |
| A6 | Third labelled pass with the adopted A2/A4/B8/B9 fixes (S4–S8) | **Y, after A2** — arms are built (A2/A3, B8) or about to be (A4, B9) | M + J |
| A7 | Dollar-P&L re-runs of pit_wfa / pit_wfa_wrds_daily / distance / sensitivity | **Y, after R1.12 is decided (D16)** | M + J |

## B. You, at a machine or a desk

| # | Item | Recommendation |
|---|---|---|
| B1 | CachyOS memtest86+ (DEV-018) — hangs recur (twice this week) | **Do soon**; a bad DIMM would explain every hang and silently corrupt long runs |
| B2 | Windows admin fix (DEV-019) | When convenient |
| B3 | Kamiak HPC — ask a faculty sponsor | **Y** — I draft the request (placebo discovery, power curves, grid re-runs are exactly what crashes CachyOS) |
| B4 | Bloomberg: use for spot checks only (licence: no bulk export/redistribution) | **Y** — a short protocol: 20 random claim-critical prices / corporate actions / supply-chain links checked by hand, logged |

## C. Ask the WSU library (free to you; ranked by value to the thesis)

| # | Resource | Why | Recommendation |
|---|---|---|---|
| C1 | **Full TAQ** (only samples visible; CRSP–TAQ link is full) | real intraday trades/quotes 1993+ — replaces yfinance intraday, enables microstructure + execution realism | **Ask first** |
| C2 | **Full OptionMetrics** (only a 2-week 2014 sample) | implied vol / skew — option-implied stress as a break predictor; equity–option cross-asset | **Ask** |
| C3 | **Capital IQ key developments / transactions / transcripts** (permission denied on WRDS) | dated corporate events, M&A incl. private parties, earnings-call text | **Ask** |
| C4 | Capital IQ Pro (web) | same content, interactive | Ask (lower priority than C3) |
| C5 | Full FactSet / MSCI ESG on WRDS (samples only); ISS (not visible) | ownership / ESG / governance | Ask, low priority |
| C6 | PitchBook web export rights | private-market deal flow | Ask what export is allowed |

## D. Methodology decisions (existing claims; each enters as a comparison arm first)

The 16 confirmed reviewer findings behind the PAPER_MAGNITUDE regime/episode claims (M-051/052/066/067/073/075/076/077,
P-082). All are re-derived on the NEW discovery output (687 Tier-3 pairs, not the old 29) after A2.

| # | Finding | Recommended fix |
|---|---|---|
| D1 | R3.3 top-2 binomial picks its episodes post hoc | **Drop the binomial**; keep the max-2 test |
| D2 | R3.4 max-2 null assumes independent confirmations | **Episode-level permutation** (shuffle labels across whole episodes) |
| D3 | R3.5 promised episode-level crisis-vs-calm test never computed | **Add it**: per-episode confirmation rate, crisis vs calm, randomization test |
| D4 | R3.6 gap-rule sensitivity has no null | **Placebo dates** (same gap rule on randomly shifted episode dates) |
| D5 | R3.10 survivorship test not filtered to crisis-first pairs | **Filter** (mechanical) |
| D6 | R3.11 survivorship design cannot see excluded pairs | **Redesign** on the full CRSP master incl. delisted: included vs excluded universes |
| D7 | R5.5 stress-test EG dominated by baseline days | **Test the crisis window itself**: structural-break test at crisis start + in-crisis residual stationarity |
| D8 | R5.6 calm controls chosen after the first run, not calm | **Pre-registered calm rule**: windows with VIX below its 30th percentile, matched length/season |
| D9 | R5.7 arbitrary 15-point "support" threshold | **Formal two-proportion test** with cluster bootstrap |
| D10 | R5.8 bootstrap resamples days and drops all-zero draws | **Stationary block bootstrap** of daily P&L incl. zeros; correct the label |
| D11 | R6.4 null pairs unaligned, yfinance-only | **Calendar-aligned nulls from the full universe** |
| D12 | R6.9 cluster bootstrap not null-centred, 12 clusters | **Wild cluster bootstrap / randomization inference**; report as CI, not a p-value |
| D13 | R8.12 recent-window power | **Report the MC power** of the 5-year test at the observed effect |
| D14 | **Dual-listed twins** (Rio Tinto plc/Ltd, historical Unilever NV/plc, Royal Dutch/Shell): Capital IQ treats them as two companies, so they stay in pools | **Exclude from pools as same economic entity; keep as positive controls** (brainstorm #4) — they are the classic Froot–Dabora pairs |
| D15 | **85 CRSP labels with no verified identity** (75 too short to test, 10 matching no candidate) | **Exclude them from gate-dependent tiers** (unresolved ≠ eligible) and list them |
| D16 | **R1.12 / U4**: `pit_wfa_wrds_daily` loads price-only close | **Total return for signals AND P&L** (a long–short holder earns/pays dividends; matches discovery) |
| D17 | P-089 FANG/OXY worked example (predates the 756-bar rule) | Re-check (mechanical), CORRECT or WITHDRAW |
| D18 | Specification-curve ranges (E5) for each outcome-informed value | I propose ranges per value with the registry work; you approve them |

## E. New research — designs to approve (each pre-registered, counted in the trial ledger)

Brainstorm 1–20 are already approved; this is their order plus the new items. ★ = recommended first.

| # | Study | Data (all available unless marked) | Recommendation |
|---|---|---|---|
| E1 ★ | End-to-end placebo discovery (#1) + power curves (#2) + grid null (#3) | synthetic + real universe; Kamiak ideal | **First** — gives every discovery claim its reference point |
| E2 ★ | Verification-layer yield (#17) → process paper backbone | bug registry, verdicts | **First** (no compute) |
| E3 ★ | **Bond/credit cross-asset**: equity vs own-issuer bond spreads, sector equity vs sector credit, Treasuries vs rate-sensitive equities; credit as early warning of breaks | TRACE (full), `wrdsapps_link_crsp_bond`, FRED spreads | **Y** — the "cross-asset" in the title; fetch scoped to pool issuers |
| E4 ★ | Pair-break causes: earnings dates (Compustat `rdq`), M&A (SDC), restatements (Audit Analytics) | full on WRDS | **Y** — event study around breaks |
| E5 ★ | Fundamental divergence → break prediction | Compustat quarterly, Financial Ratios Suite, Calcbench (as-reported, no restatement lookahead) | **Y** |
| E6 | Economic linkage of confirmed pairs (#8): shared institutional owners (13F via CUSIP, MFLINKS), board interlocks (BoardEx), shared lenders (DealScan), supply chain (Bloomberg SPLC spot checks) | WRDS full | **Y** — "does discovery find economics?" |
| E7 | Survival analysis (#6) + transition matrix (#7) | discovery outputs | **Y**, after A2 |
| E8 | Factor-neutral spreads (#9): FF5 + Pastor–Stambaugh liquidity; Beta Suite | WRDS | Y |
| E9 | Regime robustness (#10, HMM), half-life bias (#11) | existing | Y (folds into D-series re-derivation) |
| E10 | TimesFM comparison arm | **post-training-cutoff data only** (leakage) + forward record | Y, small |
| E11 | Our own forecaster vs TimesFM vs AR/OU baselines | existing LSTM | Y, with E10 |
| E12 | Break-even cost frontier (#12), capacity (#13), SEC 605 execution realism | WRDS SEC 605 | Y, after A2 |
| E13 | Sealed holdout 2024-07→ (#14) | — | **Declare now** (costs nothing; protects the final test) |
| E14 | Forward paper-trading record (#15) | free live data | Y, from the second pass's selected config |
| E15 | Private markets: PE/VC deal flow as sector signal, IPO lockups (SDC), LBO pre-deal decoupling, private-vs-public valuation lag | SDC, CIQ private cos, DealScan; PitchBook sample | Exploratory (#16 adjacent), after C3/C6 answers |
| E16 | Option-implied stress as break predictor | **needs C2** | After C2 |
| E17 | Intraday microstructure of breaks | **needs C1** | After C1 |
| E18 | International: World Indices regimes; ADR–home pairs as controls | WRDS World Indices | Y |
| E19 | Literature pass with EconLit / Business Source (citation audit refresh) | library | Y, with paper redraft |
| E20 | Off-thesis explorations (Value Line rank archive, MSRB munis, Bank Regulatory, Penn World Tables, GFDD) | various | Park; pick any you're curious about |
| E21 | Trial ledger (#16), one-command reproduction + CI (#18), claims dashboard (#19), external red team (#20) | — | Ledger + CI now; dashboard after claims settle; red team after the papers' claims are REPLICATED |

## F. Papers

| # | Decision | Recommendation |
|---|---|---|
| F1 | Lead paper's contribution | **A calibrated discovery paper**: what a full-universe episodic cointegration screen actually finds once its false-discovery rate (E1) and power (E1) are measured — transient, regime-concentrated relationships — with the strategy null result (second pass) as an honest section. Novel and arXiv-level, per your standing rule |
| F2 | Process paper | **Y** — verification layers, the bug registry and its yield (E2); drafted now |
| F3 | Withdrawn peripheral claims | stay withdrawn (S34) |

## G. Recommended order

1. **Now:** A1 + A2 (CachyOS re-run), A4, E13 (declare the holdout), B1 when you can.
2. **While A2 runs (~2 days):** D-series proposals in full + D17; parameter justification (E3 of Track E); E2 process
   paper; E1 placebo-discovery design (and the Kamiak request, B3); E3 bond fetch plan; ask the library (C1–C3).
3. **After A2:** second pass reported beside the first (+ adversarial review) → D-series re-derivations → A6 third
   pass → E4/E5/E6/E7 studies → A5 grids → papers.
