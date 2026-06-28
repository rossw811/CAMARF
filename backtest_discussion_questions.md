# backtest.py Discussion — Questions for Ross (2026-06-27)

Read before our session. My answers / recommendations are included so we
can agree or redirect quickly rather than starting cold.

---

## 1. What is Layer 1 actually testing?

The obvious Layer 1 is a simple rule-based baseline: enter when |z_rolling| >=
OU_ZSCORE_ENTRY (2.0), exit when z_rolling crosses 0, max hold = 2× half_life.
This is the pure mean-reversion signal with no ML, no regime conditioning.

**My recommendation:** yes, this should be Layer 1 exactly. Its purpose is to
establish a baseline P&L curve before adding ML on top. Without it, you can't
tell whether ml.py's predictions are adding value or just replicating the
rule's behavior in ML clothing.

**Question for you:** do you want Layer 1 to be purely event-driven (one trade
per entry signal, hold until exit or max-hold), or do you want it to model
position sizing? A flat $1 per trade (or 1 unit of spread) is the simplest;
Kelly sizing from the spread model is possible but more complex and arguably
belongs in Layer 2 where the ML output gives a confidence estimate.

---

## 2. Capital model: single pair vs. portfolio

Are we running Layer 1 per pair in isolation, or across the portfolio of all
confirmed pairs simultaneously?

**My recommendation:** run per pair first, aggregate afterward. Per-pair
gives you a clean P&L curve per pair (which pairs are actually profitable?),
then aggregating them shows diversification benefit and whether the portfolio
has correlation problems (50 pairs all entering during the same vol event).

**Question:** do you want a portfolio-level position cap? E.g. max N
concurrent open positions, or max capital concentration in one pair?

---

## 3. Transaction costs

The spread model's z-score signal is clean in-sample. Real transaction costs
on intraday pairs (bid-ask spread + market impact + commission) can easily
erase an edge that looks good on mid-prices.

**My recommendation:** include a cost model from the start. Simplest version:
flat cost per trade (e.g. $0.005/share × 2 legs × 2 trades (entry + exit)).
This should be configurable in Config.BACKTEST.

**Question:** do you have a sense of what realistic per-trade cost is for the
pairs we're tracking? Most of the confirmed 1m pairs are mid-cap liquid, which
suggests ~$0.003-0.007/share is reasonable for a retail/semi-institutional
fill.

---

## 4. Bias accounting

The session summary (DEVELOPMENT.md) already documents known biases. For the
backtest specifically:

- **In-sample stop comparison**: if entry/exit thresholds are chosen by looking
  at the backtest output, that's optimization bias. Agreed fix: lock thresholds
  to Config.ANALYSIS constants, never tune them post-hoc on backtest results.

- **Survivorship**: the confirmed pairs manifest only contains symbols that
  still exist today. Pairs involving stocks that delisted during the backtest
  period will be missing. How do you want to document/handle this?

- **Lookahead in hedge ratios**: OLS hedge ratio is estimated on the full
  sample. The backtest's spread is computed using THIS ratio, which the
  strategy wouldn't have known at entry. Kalman (which is forward-calibrated
  on the first 252 bars then frozen) is the right hedge ratio for backtesting.
  Do you want the backtest to use the Kalman hedge ratio exclusively, or
  expose both for comparison?

---

## 5. Validation approach

Given the walk-forward discussion (shuffle is wrong, CPCV is complex for our
sample size), the honest approach is:

- Reserve the last 20% of each pair's history as a holdout (chronologically,
  never touched during analysis.py's training).
- Layer 1 backtest runs on the full series for comparison purposes (we know it
  has in-sample bias since the threshold was calibrated on the same data).
- Layer 2 (ML-conditioned) backtest runs on the holdout only.

**Question:** is this the right split? 20% holdout means the last ~5 trading
days of 1m data (~1 week), which is thin. Should it be time-based (e.g. last
3 months) instead of percentage-based?

---

## 6. Output format

What does a backtest.py run produce?

**My recommendation:**
- `latest_run_backtest.log` (same pattern as other modules)
- `output/backtest/{pair_key}/trades.parquet` — one row per trade with
  entry/exit time, z-entry, z-exit, P&L, hold bars
- `output/backtest/summary.parquet` — one row per pair with Sharpe, win rate,
  avg P&L, max drawdown, n_trades
- Console: key per-pair stats during the run

**Question:** do you want an HTML/PDF report at this stage, or is parquet
output sufficient for now?

---

## 7. Layer 2 architecture (not for now, but note the dependency)

Layer 2 is ML-conditioned: only enter when ml.py says P(converge) >= some
threshold. This requires:
- ml.py to have enough labeled events to train (currently below threshold)
- The backtest to consume ml.py's predictions in time-correct order (no
  lookahead into the ML model's training window)

This is why Layer 1 first: we need the baseline to exist before we can
attribute ML alpha to the conditioned strategy.

---

## 8. Regime conditioning as a Layer 2 entry filter (new — based on Session 13 results)

`regime_conditional_analysis.py` found that VIX crisis regime → pairs converge
11× faster than their full-series average (hl_ratio=0.09); VIX backwardation →
2.3× faster (hl_ratio=0.65); VIX contango → 2.4× slower. Yield curve flat/
inverted → 2.3× faster; normal → 4.4× slower.

This means macro regime at entry time is potentially a strong predictor of
whether a given entry will converge. The `comomentum_index.parquet` adds a
crowding signal: entries during elevated comomentum (>P75, ~25% of bars) may
have lower convergence rates (not yet tested against labeled events).

**Questions:**

a. Do you want Layer 2 to include macro regime as a feature in the ML model
   (requiring ml.py feature enrichment first), OR as a hard filter on entry
   (e.g. "only enter when VIX term structure is NOT contango"), OR both?

b. For the crisis/backwardation sizing question: the data supports entering more
   aggressively when VIX is in backwardation. Do you want a continuous sizing
   multiplier (e.g. size = base × (2 - hl_ratio)) or a binary gate (enter
   normally vs. enter at 2× size)?

**My recommendation:** start with a hard filter for the first backtest pass
(reject entries when vix_term_structure = contango), measure lift vs. Layer 1
baseline, THEN consider continuous sizing. Keeps the evaluation interpretable.

---

## 9. Unified binary signal + SHAP factor table (new — from Session 13 discussion)

Ross proposed a "singular signal" that compresses all factors into one YES/NO
entry decision, with an interpretable table showing which factors drove that
decision for each entry. This maps to:

- **ml.py Stage 2**: enrich the feature vector with the macro/characteristics
  features we just computed (SampEn per pair, comomentum at entry time, VIX
  term structure, yield curve, HMM state). XGBoost outputs one probability.
- **SHAP attribution**: for each entry event, SHAP values show "SampEn=0.024
  contributed +0.12 (favorable), contango contributed -0.07 (unfavorable), etc."

The constraint: 125 labeled events → 75 training examples. Adding ~6 new features
is an overfitting risk. The right evaluation is:
- Permutation importance (not impurity-based) — unbiased at small N
- Hold-out accuracy must improve over the base model (68% → higher) before declaring win

**Questions:**

a. Build ml.py Stage 2 now (before backtest.py), or defer until backtest.py
   establishes the evaluation framework first?

b. If we build now: should the SHAP table be per-entry (real-time, shows "why
   this specific signal fired"), or aggregate (shows "across all 125 labeled
   events, which features mattered most")?

**My recommendation:** defer ml.py Stage 2 until after the backtest.py session.
Reason: the backtest will generate additional labeled events (every simulated
trade generates an outcome), giving us more training data before we add feature
complexity. Building Stage 2 now on 125 examples risks overfitting that backtest
data will immediately expose.

---

## Standing instruction

Per CLAUDE.md: **no concrete backtest.py code without an interactive session.**
This document is the pre-read for that session. Once you've reviewed these
questions, we can work through them together and then build.
