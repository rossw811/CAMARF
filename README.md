# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/version-1.0.0-green.svg)](https://github.com/rossw811/CAMARF/releases/tag/v1.0.0)
[![Status](https://img.shields.io/badge/status-active--research-orange.svg)]()

---

## Overview

CAMARF is an institutional-grade quantitative research framework that systematically discovers, characterizes, and models statistical co-movement relationships across a broad multi-asset universe — spanning the full S&P 500, cryptocurrency, foreign exchange, commodities, and futures markets simultaneously.

The framework moves beyond classical pairs trading by treating co-movement relationships as regime-dependent, volatility-normalized phenomena that are predictable at statistically significant rates using a multiclass machine learning classification model. Every relationship discovered is stress-tested for overfitting, validated out-of-sample, and reported with the same rigor applied in institutional quantitative research.

This is not a trading script with a backtest. It is a research framework designed to answer a precise question: **which asset relationships are real, under what conditions are they tradeable, and how do those conditions degrade across timeframes, regimes, and asset class boundaries?**

---

## Thesis

*Cross-asset co-movement relationships exhibit regime-dependent, volatility-normalized arbitrage structure that is predictable at statistically significant rates using a multiclass ML framework, with predictability degrading systematically and quantifiably across timeframes, regimes, and asset class boundaries.*

---

## Methodology Summary

- **Universe Scan** — Full S&P 500 plus crypto, forex, commodities, and futures screened for duo and trio co-movement relationships using Engle-Granger (pairs) and Johansen (trios) cointegration, with Ornstein-Uhlenbeck spread modeling for half-life, mean reversion speed, and long-run equilibrium estimation
- **Volatility Framework** — Per-asset relative volatility normalized to own historical baseline, cross-asset volatility differential analysis, and three signal conditioning variants (regime-adjusted, volume-adjusted, baseline) tested head-to-head across all 11 timeframes
- **ML Signal Discovery** — Random Forest / Gradient Boosting multiclass classifier identifying which factor combinations most reliably predict spread resolution, with inter-indicator correlation analysis and cross-asset indicator divergence as first-class features
- **Combinatoric Backtesting** — Two-phase coarse-to-fine grid search across entry conditions, exit conditions, and risk management rules; long and short tested independently and combined; three account sizes ($10k, $100k, $1M) and three position sizing methods (2% flat, half Kelly, full Kelly)
- **Institutional Validation** — PSR (Deflated Sharpe), PBO, WFA decay ratio, three-method Monte Carlo (IID, block bootstrap, parametric Student-t), Benjamini-Hochberg FDR correction for multiple comparisons, and a dedicated failure analysis section

---

## Asset Universe Coverage

| Asset Class | Source | Depth |
|---|---|---|
| S&P 500 Equities | IBKR Gateway | Max available |
| Cryptocurrency | IBKR Gateway | Max available |
| Foreign Exchange | IBKR Gateway | Max available |
| Commodities | IBKR Gateway | Max available |
| Futures | IBKR Gateway | Max available |
| Options IV Surface | CBOE | Max available |

---

## Key Findings

> *Populated upon completion of v1.0.0 analysis run.*

---

## Research Report

> *PDF report published upon v1.0.0 release.*

The report follows institutional backtesting standards and is structured as a thesis document covering: executive summary, universe construction, pairs analysis, trio analysis, volatility and regime framework, multi-timeframe analysis, ML signal discovery, entry/exit combinatorics, position sizing feasibility, options integration, linear algebra and matrix methods, walk-forward validation, Monte Carlo simulation, overfitting diagnostics, performance attribution, statistical significance, failure analysis, and key findings with actionable recommendations.

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.10+ |
| Broker / Data | Interactive Brokers Gateway via `ib_insync` |
| Options Data | CBOE Surface Data |
| ML Models | `scikit-learn` (RF/GBM) |
| Statistical Tests | `statsmodels`, `scipy` |
| Matrix Methods | `numpy`, `pandas` |
| Regime Classification | `scikit-learn` (K-Means), `hmmlearn` (HMM) |
| Report Generation | `matplotlib`, `reportlab` |
| Data Storage | Local HDF5 / Parquet cache |

---

## How to Run

### Prerequisites

```bash
# Clone the repository
git clone https://github.com/rossw811/CAMARF.git
cd CAMARF

# Install dependencies
pip install -r requirements.txt

# Ensure IBKR Gateway or TWS is running and accessible on localhost:4001
```

### Configuration

Edit `config.py` to set:
- IBKR connection parameters
- Universe selection flags
- Timeframe selection
- Account size and risk parameters
- Output directory for report

### Full Pipeline

```bash
# Step 1 — Build universe and download historical data
python data.py

# Step 2 — Run co-movement scan (pairs + trios)
python analysis.py

# Step 3 — Train and evaluate ML classifier
python ml.py

# Step 4 — Run combinatoric backtest
python backtest.py

# Step 5 — Run options integration
python options.py

# Step 6 — Run full statistical validation suite
python stats.py

# Step 7 — Generate PDF research report
python report.py
```

> **Estimated full pipeline runtime:** TBD after v1.0.0 profiling run.

---

## Project Structure

```
CAMARF/
├── README.md               # This file
├── config.py               # All parameters, universe lists, flags
├── data.py                 # Universe building, IBKR feed, CBOE feed, caching
├── analysis.py             # Comovement scan, trio builder, spread model, vol framework, regimes
├── ml.py                   # Feature engineering, classifier, feature selection
├── backtest.py             # Engine, entry/exit combinator, position sizer, long/short
├── options.py              # IV surface loader, IV signal layer
├── stats.py                # Significance tests, Monte Carlo, WFA, PBO, PSR, PCA
├── report.py               # PDF assembly and all section builders
├── requirements.txt        # Python dependencies
└── output/                 # Generated reports and cached data (gitignored)
```

---

## Academic Context

This project was developed independently as a quantitative research portfolio piece while enrolled as an undergraduate Finance student at Washington State University. It represents original research into multi-asset statistical co-movement structure, conducted without formal coursework in stochastic processes, cointegration theory, or machine learning.

The methodology builds on and extends an earlier completed pairs trading system for NQ/ES futures (MNQ/MES micro contracts), which produced a Sharpe ratio of 3.31, WFA decay ratio of 1.06, and PBO of 22% across a full three-method Monte Carlo validation suite.

---

## Disclaimer

This framework is developed for academic research purposes only. Nothing in this repository constitutes financial advice or a solicitation to trade. All backtest results are hypothetical and subject to the limitations documented in the research report's bias mitigation section.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

*CAMARF v1.0.0 — rossw811 — Washington State University*
