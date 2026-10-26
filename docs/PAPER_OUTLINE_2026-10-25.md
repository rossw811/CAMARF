# Paper outline (one paper, one claim; DECISIONS_2026-10-25 #3)

Status: structure only. No number below is final; each section names the result that fills it and the gate it must pass
(independent review, claims registry REPLICATED). Drafting starts after E1 and N14 v2 pass review.

**Working title.** What survives a sealed holdout: a pre-registered, point-in-time test of cointegration pairs trading
on a 44,700-symbol universe.

**Claim (one sentence).** With point-in-time pair selection, executable dollar P&L and a sealed holdout, cointegration
pairs trading shows no robust edge, and the screen that selects the pairs finds barely more of them than a
correlation-matched null does.

**Abstract (150-250 words, one claim, one number).** Number: to be chosen from C-006 (0 of 8 pre-registered cells) or
the N14 null size; written last.

## 1. Introduction
The practice (full-history screening, a confirmed pair as a timeless fact), why it matters, the four contributions,
the result. Positioned against Gatev, Goetzmann & Rouwenhorst (2006: formation/trading split, already causal),
Do & Faff (2010, 2012: declining profits), Rad, Low & Faff (2016), Farago & Hjalmarsson (2019: little pairwise
cointegration), Krauss (2017 survey); multiple testing: Harvey, Liu & Zhu (2016), Bailey & López de Prado (2014).
Engage the papers that report positive recent results (from the second-pass search).

## 2. Data
Universe (WRDS CRSP + Compustat Global in USD + yfinance + Binance; IBKR off), sealed holdout (daily from 2026-01-01,
intraday forward-recorded from 2026-10-21, sealed at the loader), the data defects found and fixed (one changelog
table, no internal IDs). Survivorship: disclosed, year-stratified OR 1.60 [1.27, 2.01].

## 3. The screen and its calibration
3.1 Pipeline: correlation prefilter, rolling Engle-Granger, BH-FDR, liquidity and same-company rules.
3.2 Correlation-matched null (N14 v2): size at nominal 5% by block-length quartile, power on a spread-s.d. grid; raw
    rejection rate on real candidates beside it. Gate: N14 v2 review.
3.3 End-to-end placebo (E1): false discoveries on a universe with no cointegration; recovery of 48 planted pairs by
    half-life. Gate: E1 score review. If recovery is low, this section leads and the claim is "no power".

## 4. The pre-registered test
4.1 Design (pre-registration and Amendments 1-6, committed before results), point-in-time pool, 432 trials, splits,
    deflated Sharpe, PBO.
4.2 Result: C-006 (Amendment 5): 0 of 8 cells; holdout Sharpes with intervals; DSR <= 0.33.
4.3 Sensitivity: Amendment 6 (monthly re-decided membership), combined family N = 864. Gate: A6 review.

## 5. Edge accounting
The 2 x 2 x 2 factorial (selection, P&L basis, executability), Shapley attribution with joint bootstrap intervals;
the split-break fix not measurable (disclosed). Gate: independent review of the run.

## 6. Claims that did not survive
Discovery regime: crisis concentration p = 0.124 window-weighted, crisis vs calm no difference, persistence
withdrawn; weak-exogeneity "70% one leg leads" order-dependent. Short, factual.

## 7. Limitations
Survivorship scope, multiple looks (counted), universe gates (S&P 500 membership gate on CRSP legs), free-data limits,
AI-tool use (section kept from the current draft, shortened).

## Appendix
A. Supporting findings kept: SPAC NAV clustering as a source of spurious cointegration. B. Johansen specification
(restricted constant; trace/max-eig tables). C. Parameter registry summary. D. Reproducibility (commands, seeds, data
ranges). Archived, not in the paper: legacy per-pair diagnostics from PAPER.md section 7.
