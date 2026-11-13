# Decisions for Ross, 2026-11-13 -- real-data stage of the 2026-11-11 model tests

Context: nine model arms passed their synthetic tests and an independent review (Development.md 2026-11-11). None has
touched real data. Each needs a go on its comparison design before it runs (CLAUDE.md: new methodology -> buy-in; a
concept goes in as a comparison arm first). All designs are point-in-time; none feeds production code.
Recommended order: **A, then B**; C-E deferred until P2 and E1 are read.

## A. Stochastic-volatility nulls for the EG / ADF calibration (Heston; SABR as a second shape) -- RECOMMENDED FIRST
- Why now: today's P2 work showed volatility clustering with fat tails drives most of the unit-root tests' over-rejection
  (GARCH t4: AIC-ADF 8.2% at 5%), and E1's placebo keeps less clustering than real data (ACF |r| 0.165 vs 0.190). A
  null generator whose clustering is MATCHED to real data measures how anti-conservative the placebo is -- the open
  question behind E1 decision 3 (calibrated cutoff) and the P2 caveat.
- Design: pairs of independent Heston log-price paths (no relation by construction), vol-of-vol and mean reversion
  fitted per decile of real US series to match each decile's ACF of |r| (lags 1-20) and kurtosis -- moments only, no
  test statistic of real pairs is read. Run the discovery test (EG, 10-year windows) and P2's yearly fixed ADF on them;
  report the far-tail rate (p < 1e-4, 2e-5) and 5% size against nominal and against the v2c placebo's rates.
- Decision rule (declared): if matched-clustering tail rates exceed the placebo's by > 2x at the discovery cutoff, the
  placebo-calibrated cutoff (decision 3) must use the stochastic-vol null as its bound, not the placebo alone.
- Cost: CPU only, light per path; ~2-4 h CachyOS, can run beside E1 at low priority (no 46k-file loads).

## B. ARMA vs AR(1) half-lives on the A8 pool spreads
- Why: time stops and the half-life filter use the AR(1) half-life; spreads with an MA / measurement-noise component make
  AR(1) read persistence too SHORT (synthetic: latent hl 13.5 -> AR(1) 1.7, ARMA 12.1).
- Design: k2 (69) and k1 (797) pools, each pair's rolling formation windows exactly as production (hedge from before the
  window); per window AR(1) vs ARMA (BIC order) dominant-root half-life. Out-of-sample check: which predicts the NEXT
  window's realised decay (time for the spread's autocorrelation to fall below 0.5) with lower median absolute log error.
- Decision rule: descriptive unless ARMA's error is lower in >= 60% of pair-windows AND the median ratio is outside
  [0.8, 1.25]; then a time-stop arm on ARMA half-lives is proposed as a new pre-registered amendment (trials counted).
- Cost: light (spreads already on CachyOS).

## C. Nelson-Siegel curve factors (FRED Treasury, via macro.py) -- deferred
Level / slope / curvature from a FIXED maturity set available over the whole span (3m, 1y, 2y, 5y, 10y; 30y has a gap
2002-2006), fixed lambda 0.0609, row by row. Use: explanatory variable for regime labels and for co-movement breaks
(endogeneity rules: matched placebo pairs, stated conditioning). Wait until a study needs it.

## D. PCA vs AE vs VAE residual s-scores on the PIT universe -- deferred
A trading-signal comparison (Avellaneda-Lee style) = new trials; needs its own pre-registration, GPU-vs-CPU measured at
real size first (CLAUDE.md), and the synthetic gap (AE 0.655 vs PCA 0.692 s-score corr) says the nonlinear models must
earn their place. Not before P2.

## E. GAE: predict next year's pool pairs from this year's graph -- deferred
Synthetic stage showed no gain over common neighbours (0.947 vs 0.943). Only worth running if a richer graph (ownership,
board links) exists; otherwise expected to restate the baseline.
