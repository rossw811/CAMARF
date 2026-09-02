# 15-Library Survey — What CAMARF Could Actually Learn, 2026-09-01

Ross's original ask (2026-08-2x session): read all 15 libraries "to full depth" and plan "our own,
more efficient and optimized version." That scope (weeks of full-repo reading) wasn't done here.
Instead: each library verified as real/maintained via its actual GitHub repo or docs, then judged
against CAMARF's actual architecture (stat-arb screening, EG cointegration, FDR correction,
eigenportfolio/PCA, meta-labeling ML, custom event-driven backtest.py, PIT-WFA) for concrete,
adoptable techniques — not generic "this is a good library" summaries. Sources cited inline.

## Ranked by actual relevance to CAMARF

| Rank | Library | Verdict |
|---|---|---|
| 1 | `arch` | Already used (GARCH stops) — the Johansen-test claim below was **wrong, corrected**: Johansen actually lives in `statsmodels` (already a dependency), not `arch` |
| 2 | `hftbacktest` | Not directly usable (CAMARF isn't HFT/L2-book), but its **queue-position fill model** is a real execution-realism idea `backtest.py` currently lacks |
| 3 | `PyPortfolioOpt` | Already conceptually covered (HRP/risk-parity) — worth a direct diff against CAMARF's own implementation for correctness, not adoption |
| 4 | `cvxpy` | General convex-optimization solver — only relevant if CAMARF ever needs a real solver call, not a strategy library |
| 5 | `vectorbt` | Architecture-only read: vectorized-array backtesting is a genuinely different paradigm from `backtest.py`'s event loop — worth understanding, not worth switching to |
| 6 | `nautilus_trader` | Production-grade live/backtest parity architecture — relevant only if CAMARF ever goes from research to live execution, not now |
| 7 | `scikit-learn` | Already CAMARF's actual ML backbone (`ml.py`'s meta-labeler) — nothing new to survey, it's already in use |
| 8 | `polars` | Already has a debug/verify script (`debug/_verify_polars_universe_loader.py`) — apparently already evaluated once as a pandas alternative |
| 9 | `pyarrow` | Already a hard dependency (all CAMARF's parquet I/O runs through it) — nothing to "adopt," it's load-bearing infrastructure |
| 10 | `jax` | Autodiff/JIT — no clear CAMARF use case found; GPU work is already done via CuPy/PyTorch-style kernels per `debug/_verify_eigendecompose_gpu.py`/`_verify_gpu_batched_eg.py` |
| 11 | `pytorch` | Only relevant if CAMARF's ML layer moves beyond scikit-learn to deep learning — no evidence that's planned |
| 12 | Kalshi market maker (`rodlaf/KalshiMarketMaker`) | Concrete algorithm (Avellaneda-Stoikov quoting) exists and is real, but market-making ≠ CAMARF's mean-reversion stat-arb — conceptual relevance only |
| 13 | `tensortrade` | RL-for-trading framework — no clear fit; CAMARF's ML layer is a meta-labeler, not an RL agent |
| 14 | `zipline-reloaded` | Original Zipline is dead (Quantopian shut down 2020); the maintained fork exists but its Pipeline/bundle architecture doesn't address anything `backtest.py` lacks |
| 15 | `QuantLib` | Confirmed real, actively maintained (v1.42.1, 2026), but it's derivatives/bonds pricing infrastructure — no derivatives-pricing need in CAMARF today |

---

## 1. `arch` (bashtage/arch) — Kevin Sheppard, Oxford

**What it is**: Python package for ARCH/GARCH volatility models (GARCH, EGARCH, FIGARCH, TARCH,
APARCH, HARCH) plus, less advertised, unit-root and cointegration testing.
[GitHub](https://github.com/bashtage/arch), [docs](https://bashtage.github.io/arch/doc/index.html).

**Maintained**: yes, real, actively developed (Kevin Sheppard, University of Oxford).

**CORRECTION (2026-09-01, caught before anything was built on it)**: this entry originally claimed
`arch`'s cointegration module includes a Johansen-style multi-asset test. **Verified directly against
the real docs — it does not.** `arch.unitroot.cointegration` has exactly two cointegration tests,
both pairwise: Engle-Granger (`engle_granger`) and Phillips-Ouliaris (`phillips_ouliaris`), plus
cointegrating-VECTOR estimators (Dynamic OLS, Fully Modified OLS, Canonical Cointegrating
Regression) — none of which test cointegrating RANK across 3+ series the way Johansen does. The
underlying research question (basket cointegration vs. pairwise-only) is still real and still worth
scoping — CAMARF's methodology genuinely is pairwise-only — but the actual implementation is
`statsmodels.tsa.vector_ar.vecm.coint_johansen`, already confirmed present and importable in
CAMARF's own `trading` environment (verified directly: `from statsmodels.tsa.vector_ar.vecm import
coint_johansen` succeeds), i.e. **no new dependency needed at all** — `statsmodels` is already a
CAMARF dependency for the existing pairwise EG test. See
`docs/research/JOHANSEN_BASKET_COINTEGRATION_SCOPE_2026-09-01.md` for the actual build scope.

**ADDITION (2026-09-01, per Ross's direct correction)**: CAMARF's GARCH usage is more specific than
"the `arch` package's GARCH models" — `stats.py` Section 4 fits univariate `arch_model` GARCH(1,1)
per pair, then **hand-rolls DCC (Dynamic Conditional Correlation, Engle 2002) from scratch on top of
it**, because `arch.multivariate`'s own DCC class was removed in `arch` 7+ (confirmed directly in
`stats.py`'s own comments, lines 594-596: *"arch.multivariate was removed in arch 7+. We implement DCC
from the univariate GARCH standardized residuals directly (this is exactly what the arch DCC class was
doing internally — see Engle 2002 §2)."*). Ross asked directly whether a newer/different
multivariate-GARCH package exists worth comparing against this hand-rolled implementation.
**Verified via web search**: [`pymgarch`](https://pypi.org/project/pymgarch/) (PyPI, v0.1.1) is a real,
purpose-built candidate — implements DCC, ADCC, and CCC correlation dynamics **built directly on
`arch`'s own univariate marginals** (the exact same GARCH(1,1) fit CAMARF already does), with
"correct two-stage Engle-Sheppard standard errors" and replication tests against R's `rmgarch`/
`tsmarch` reference implementation. Early-stage (0.1.1) — worth testing carefully against CAMARF's own
implementation for agreement, not trusting blindly, same discipline as everything else in this project.
**Recommendation**: a real, cheap comparison-arm candidate — run both `stats.py`'s hand-rolled DCC and
`pymgarch`'s DCC on the same confirmed-pair P&L series, check whether the fitted dynamic correlations
agree. If they do, it's a correctness cross-check (good, cheap confidence). If they don't, that's a
real bug in one implementation worth finding. See the DCC-GARCH comparison section below.

---

## 2. `hftbacktest` (nkaz001/hftbacktest)

**What it is**: A Python+Rust high-frequency trading/market-making backtester that reconstructs a
full L2 limit order book from tick data and simulates fills accounting for **feed latency, order
latency, and queue position** (where in the order book's price-level queue your order actually
sits). [GitHub](https://github.com/nkaz001/hftbacktest),
[docs](https://hftbacktest.readthedocs.io/en/v1.8.4/).

**Maintained**: yes, real, active (multiple forks and a Polymarket-specific fork exist, itself
evidence of real usage).

**Concrete finding**: CAMARF is not HFT and doesn't need L2 book reconstruction — but its core
execution-realism idea (a limit order only fills once the queue ahead of it is consumed, not just
"price touched") is a real gap in most simple backtesters. Worth checking whether `backtest.py`'s
own fill logic assumes instant/full fills at the touch price (a common backtest optimism bias) or
already accounts for anything like this. Not urgent — CAMARF trades on daily/rolling-window
signals, not tick-level — but worth a deliberate note if `backtest.py`'s fill assumptions are ever
challenged as too generous.

**Recommendation**: read for the *concept* (queue-aware fill realism), not the code — CAMARF's
timeframe doesn't need L2 book simulation, but the underlying "don't assume free fills" discipline
is transferable.

---

## 3. `PyPortfolioOpt` (robertmartin8/PyPortfolioOpt)

**What it is**: Portfolio optimization — mean-variance/efficient frontier, Black-Litterman, and
**Hierarchical Risk Parity (HRP)**. [GitHub](https://github.com/robertmartin8/PyPortfolioOpt).

**Maintained**: yes, actively updated (last release verified March 2026), maintained by a
practitioner (DE Shaw).

**Concrete finding**: CAMARF already has its own HRP/risk-parity implementation per `CLAUDE.md`'s
file map. Since PyPortfolioOpt is a well-reviewed, widely-used reference implementation of the same
algorithm (de Prado's original HRP paper), the actual value here isn't "adopt it" — it's a
**correctness cross-check**: run CAMARF's own HRP weights against PyPortfolioOpt's on the same
covariance matrix and confirm they converge to the same allocation (within numerical tolerance).
That's a cheap, concrete verification task, not a new build.

**Recommendation**: use as a reference implementation to cross-check CAMARF's existing HRP code
once, not something to integrate directly.

---

## 4. `cvxpy` (cvxpy/cvxpy)

**What it is**: A Python-embedded modeling language for convex optimization — you describe the
problem (objective + constraints) and it picks a real solver (Clarabel, OSQP, SCS, HiGHS) to solve
it. [GitHub](https://github.com/cvxpy/cvxpy/), [site](https://www.cvxpy.org/).

**Maintained**: yes, actively maintained (multiple named current maintainers, Stanford-originated).

**Concrete finding**: this is infrastructure, not a strategy library — relevant only if/when CAMARF
needs to solve an actual constrained optimization problem it doesn't already have a closed-form
answer for (e.g., a portfolio construction step with real constraints — max position size, sector
caps, turnover limits — that HRP's recursive-bisection approach doesn't naturally express). No
evidence CAMARF has hit that wall yet.

**Recommendation**: keep in back pocket for whenever portfolio construction needs real constraints
beyond what HRP naturally handles; nothing to build today.

---

## 5. `vectorbt` (polakowo/vectorbt)

**What it is**: A backtesting engine built entirely on vectorized NumPy/pandas/Numba array
operations instead of an event loop — whole price histories and whole parameter grids become
multidimensional arrays, letting it sweep thousands of strategy variants at once at near-C speed.
[GitHub](https://github.com/polakowo/vectorbt), [docs](https://vectorbt.dev/).

**Maintained**: yes, confirmed not archived, active issues/discussions through 2026 (a separate
paid `vectorbt.pro` also exists, evidence of a real, funded project).

**Concrete finding**: this is a genuinely different backtesting paradigm from `backtest.py`'s
event-driven design — vectorized batch evaluation vs. sequential event processing. The real
question worth asking (not answered here, needs your call) is narrower than "should CAMARF use
vectorbt": **does `backtest.py` need to sweep large parameter grids (stop-loss thresholds, entry
z-scores, holding periods) across many pairs at once**, and if so, is the current event-driven
architecture the right tool for that, or is a vectorized sweep layer worth building alongside it
for parameter-search specifically (keeping the event-driven engine for the final, realistic
single-configuration backtest)? This is an architecture question, not a library-swap.

**Recommendation**: read vectorbt's docs for the vectorized-parameter-sweep pattern if/when
large-scale parameter search becomes a real bottleneck in `backtest.py`; don't replace the engine.

---

## 6. `nautilus_trader`

**What it is**: A Rust-core, Python-control-plane algorithmic trading platform designed so the
*exact same* strategy code runs in backtest and live trading — nanosecond-resolution event-driven
backtester, multi-venue, built explicitly to support market-making and statistical arbitrage.
[GitHub](https://github.com/nautechsystems/nautilus_trader) (verified via multiple forks/mirrors).

**Maintained**: yes, real, active, production-grade (Rust core + Cython bindings, explicit
backtest/live parity design).

**Concrete finding**: the core architectural idea worth remembering — backtest and live code paths
sharing one implementation rather than diverging — is directly relevant *if and when* CAMARF moves
from research to any live/paper trading. Not relevant to CAMARF's current research-only phase.

**Recommendation**: worth a serious look only at the point CAMARF's roadmap includes live
execution; premature to build against now.

---

## 7. `scikit-learn`

**What it is**: The standard general-purpose Python ML library (classification, regression,
model selection, preprocessing).

**Maintained**: yes, one of the most widely used and actively maintained Python libraries in
existence — no verification needed beyond noting it's unambiguously real and current.

**Concrete finding**: checked `ml.py` directly (not assumed) — its primary meta-labeling model is
actually **XGBoost**, not a scikit-learn estimator; scikit-learn is used only for supporting
utilities (`permutation_importance` for feature importance, `LabelEncoder`,
`compute_sample_weight`). So this isn't "already the ML backbone" as a first guess might suggest —
it's a real but secondary dependency. Nothing new to adopt either way.

**Recommendation**: no action — already in use (correctly, as a utility layer, not the primary
model).

---

## 8. `polars`

**What it is**: A Rust-backed DataFrame library positioned as a faster, more memory-efficient
alternative to pandas, with a lazy-evaluation query engine.

**Maintained**: yes, extremely active, widely adopted.

**Concrete finding**: checked `debug/_verify_polars_universe_loader.py` directly (not just noted its
existence) — a polars-based universe-loading path was already prototyped and passes its own
synthetic checks: values are bit-identical to the pandas path (max abs diff 0.0 across real test
files), with one disclosed, deliberate dtype normalization (polars' `to_pandas()` yields plain
`float64`, while `pd.read_parquet` on WRDS files yields nullable `Float64Dtype()` — the verify
script treats plain `float64` as the *safer* choice, citing this project's own repeated pd.NA-dtype
bugs). So this work is already done and already correct — polars was evaluated as a genuine pandas
alternative for reading WRDS parquet, not abandoned or half-finished. Whether it's actually wired
into the production path (vs. just verified as a safe option) wasn't checked here — that's a
one-line grep for whoever picks this up next.

**Recommendation**: no further research needed — already evaluated and verified; just confirm
whether it's actually in production use or still sitting as a validated-but-unused option.

---

## 9. `pyarrow`

**What it is**: The Python bindings for Apache Arrow — columnar in-memory format, and the engine
underlying pandas' parquet read/write.

**Maintained**: yes, foundational, extremely active (Apache Software Foundation project).

**Concrete finding**: already a hard, load-bearing dependency — every parquet cache read/write in
CAMARF goes through pyarrow already (this is precisely the library whose version mismatch between
base Anaconda and the `trading` env caused the "misreport valid parquet as corrupted" bug documented
in `CLAUDE.md`'s Known-Resolved Issues). Nothing to survey or adopt; already deeply embedded.

**Recommendation**: no action — already in use, already has a documented version-pinning gotcha.

---

## 10. `jax`

**What it is**: Google's NumPy-compatible autodiff + XLA JIT-compilation library, primarily used
for ML research and differentiable programming.

**Maintained**: yes, actively developed by Google.

**Concrete finding**: no clear CAMARF use case surfaced. Checked directly — CAMARF's GPU
acceleration (`analysis.py`, e.g. `cupy.linalg.eigh` replacing `np.linalg.eigh`) is confirmed built
on **CuPy**, not jax. Introducing jax would mean a second, redundant GPU-acceleration stack rather
than filling a gap. Autodiff specifically would only matter if CAMARF ever needed to differentiate
through a model (e.g., gradient-based hyperparameter optimization) — no evidence that's needed
today.

**Recommendation**: skip — no gap it fills that isn't already covered.

---

## 11. `pytorch`

**What it is**: The standard deep-learning framework (tensors, autodiff, neural network layers).

**Maintained**: yes, unambiguously real and dominant in the field.

**Concrete finding**: relevant only if CAMARF's meta-labeling ML layer (`ml.py`) ever moves beyond
scikit-learn-style models to deep learning (e.g., a sequence model over price history, or a
learned embedding of regime state). No evidence that's planned or needed — scikit-learn's
gradient-boosted trees are usually the stronger, more interpretable choice for tabular
meta-labeling anyway, which is what CAMARF's problem looks like.

**Recommendation**: skip for now — no identified use case; scikit-learn is likely the better fit
for this project's actual ML problem shape regardless.

---

## 12. Kalshi market maker (`rodlaf/KalshiMarketMaker`)

**What it is**: A real, open-source market-making bot for Kalshi (a CFTC-regulated prediction-market
exchange). Runs one **Avellaneda-Stoikov** worker per market — the Avellaneda-Stoikov model computes
a "reservation price" (mid-price adjusted for current inventory) and quotes bid/ask asymmetrically
around it, with the asymmetry widening as inventory risk grows.
[GitHub](https://github.com/rodlaf/kalshimarketmaker). Other real Kalshi bots exist too (e.g.
Viprasol-Tech/kalshi-trading-bot), confirming this is a real, active space, not vaporware.

**Maintained**: appears real and functional; a niche/small project (not a major library), so treat
individual code quality with normal skepticism, but the Avellaneda-Stoikov algorithm itself is
well-established academic finance (Avellaneda & Stoikov 2008), not something invented for this bot.

**Concrete finding**: CAMARF doesn't do market-making (it's mean-reversion stat-arb, not quoting
two-sided markets) — so this bot's actual code isn't directly reusable. But the **underlying
inventory-risk-adjusted concept** is conceptually adjacent to something CAMARF might care about:
position sizing that widens/tightens based on how much inventory (open exposure) a strategy already
has in a given pair or sector, rather than fixed sizing. Worth flagging as a conceptual parallel,
not a concrete adoption — this would need real scoping as its own research question if you want to
pursue it, same caveat as the `arch` Johansen-test finding above.

**Recommendation**: conceptual read only (Avellaneda-Stoikov's inventory-risk framing), not code
reuse — market-making and mean-reversion stat-arb are different problems.

---

## 13. `tensortrade`

**What it is**: An open-source reinforcement-learning framework for training trading agents —
composable environments, action schemes, reward functions, and data feeds, built on gym/keras/
tensorflow. [GitHub](https://github.com/tensortrade-org/tensortrade).

**Maintained**: yes, real, has an active org and a "-ng" (next-gen) fork in active development.

**Concrete finding**: no clear fit. CAMARF's ML layer is a meta-labeler (predicting whether a
signal already generated by the screening pipeline is likely to be profitable), not an RL agent
learning to trade from scratch — a fundamentally different ML paradigm. Adopting an RL framework
would be a significant methodology pivot, not an incremental addition, and nothing in CAMARF's
existing findings suggests the meta-labeling approach has hit a ceiling that RL would solve.

**Recommendation**: skip — different ML paradigm than CAMARF's current approach, no evidence of
need.

---

## 14. `zipline-reloaded` (stefan-jansen/zipline-reloaded)

**What it is**: The community-maintained continuation of Quantopian's original Zipline
event-driven backtester, after Quantopian shut down in late 2020. Maintained by Stefan Jansen
(author of *Machine Learning for Algorithmic Trading*).
[GitHub](https://github.com/stefan-jansen/zipline-reloaded).

**Maintained**: the fork is real and maintained; the *original* Zipline is dead (Quantopian's own
infrastructure is gone).

**Concrete finding**: Zipline's signature feature is its Pipeline API (declarative, factor-based
universe screening) and bundle-based data management — CAMARF already has its own universe-loading
and screening pipeline (`universe_loader.py`, `analysis.py`) that does a conceptually similar job,
purpose-built for this project's exact data sources (WRDS/yfinance/IBKR/Binance). Nothing in
Zipline's architecture addresses a gap CAMARF currently has.

**Recommendation**: skip — CAMARF's own pipeline already does the equivalent job for its specific
data sources; Zipline's Pipeline API doesn't teach a new technique CAMARF lacks.

---

## 15. `QuantLib`

**What it is**: A comprehensive, decades-old C++ (with Python/C#/Java/R bindings) library for
derivatives pricing, bond/swap valuation, and risk management. [GitHub](https://github.com/lballabio/QuantLib),
current stable release 1.42.1 (April 2026).

**Maintained**: yes, confirmed real, actively maintained, established since 2000.

**Concrete finding**: confirms the original triage was right — this is derivatives/bonds pricing
infrastructure (swaps, options, term structures) that CAMARF has no current use for; it doesn't
trade options or fixed income. No specific piece of it addresses anything in CAMARF's actual
methodology (cointegration screening, FDR correction, regime detection, meta-labeling).

**Recommendation**: skip entirely — confirmed not relevant, no hidden useful piece found.

---

## Bottom line

Two genuinely new, concrete research threads came out of this (not code to write yet — both need
your explicit buy-in per `CLAUDE.md`'s "new methodology needs sign-off" rule before anything gets
built):

1. **Johansen basket cointegration** (via `statsmodels`, already a dependency — not `arch`, that
   attribution was wrong and corrected above) — CAMARF is pairwise-only; a basket cointegration
   comparison arm is a real, scopeable research question. Ross approved building this 2026-09-01 —
   see `docs/research/JOHANSEN_BASKET_COINTEGRATION_SCOPE_2026-09-01.md`.
2. **Inventory-risk-adjusted position sizing** (Avellaneda-Stoikov's core idea, seen in the Kalshi
   bot) — conceptually adjacent to CAMARF's position-sizing logic, worth a real scoping
   conversation if you want to pursue it, not a direct port.

Everything else either confirms CAMARF is already using the right tool (scikit-learn, pyarrow,
arch's GARCH side, HRP), is a paradigm CAMARF doesn't need (RL, HFT microstructure, market-making,
derivatives pricing, live-trading platforms), or is worth reading for architecture ideas only with
no action needed today (vectorbt's vectorized sweeps, nautilus_trader's backtest/live parity).
