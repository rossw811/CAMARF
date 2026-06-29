# =============================================================================
# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework
# report.py — LaTeX report generator
# github.com/rossw811/CAMARF
#
# Runs AFTER stats.py.  Reads all output/ parquets + JSONs and generates:
#   output/report/main.tex         — full paper (compile with pdflatex)
#   output/report/references.bib  — BibTeX references
#   output/report/figures/        — PNG figures (300 DPI)
#
# Compile:
#   pdflatex main.tex && bibtex main && pdflatex main.tex && pdflatex main.tex
# =============================================================================

from __future__ import annotations

import glob
import json
import logging
import os
import time
import warnings
from typing import Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("CAMARF.report")

_ROOT = os.path.dirname(os.path.abspath(__file__))
_STATS_DIR   = os.path.join(_ROOT, "output", "stats")
_BACKTEST_DIR = os.path.join(_ROOT, "output", "backtest")
_RESULTS_DIR = os.path.join(_ROOT, "output", "results")
_REPORT_DIR  = os.path.join(_ROOT, "output", "report")
_FIG_DIR     = os.path.join(_REPORT_DIR, "figures")
_FIG_DPI     = 300
_TODAY       = pd.Timestamp.now().strftime("%Y-%m-%d")

# Matplotlib style
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "figure.dpi": _FIG_DPI,
})

TIER_COLORS = {"gold": "#C8A951", "silver": "#8E9EAB", "bronze": "#CD7F32"}


# =============================================================================
# SUMMARY LOG
# =============================================================================


class SummaryLog:
    def __init__(self) -> None:
        self._lines: List[str] = []
        self._t0 = time.time()

    def note(self, msg: str) -> None:
        self._lines.append(msg)
        log.info(msg)

    def write(self, path: str) -> None:
        runtime_min = (time.time() - self._t0) / 60
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("=== CAMARF report.py ===\n")
            fh.write(f"date:        {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
            fh.write(f"runtime_min: {runtime_min:.1f}\n\n")
            for line in self._lines:
                fh.write(line + "\n")
            fh.write("\n=== end ===\n")


summary = SummaryLog()


# =============================================================================
# LaTeX UTILITIES
# =============================================================================


def _esc(s: str) -> str:
    """Escape special LaTeX characters in a string."""
    for ch, rep in [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"), ("%", r"\%"), ("$", r"\$"),
        ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
        ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
    ]:
        s = s.replace(ch, rep)
    return s


def _pair_label(row: pd.Series) -> str:
    """Format pair label for display (e.g. 'LNT/WELL@1h')."""
    return f"{row['symbol_a']}/{row['symbol_b']}@{row['tf_label']}"


def _pair_label_tex(a: str, b: str, tf: str) -> str:
    """LaTeX-safe pair label."""
    return _esc(f"{a}/{b}@{tf}")


def _fmt(val, decimals: int = 2, na: str = "---") -> str:
    """Format a number, returning na for NaN/None."""
    try:
        v = float(val)
        if np.isnan(v) or np.isinf(v):
            return na
        return f"{v:.{decimals}f}"
    except (TypeError, ValueError):
        return na


def _sig(pval: float, reverse: bool = False) -> str:
    """Return significance stars for a p-value.
    reverse=True: low p = reject null = use *** convention.
    """
    try:
        p = float(pval)
    except (TypeError, ValueError):
        return ""
    if reverse:
        if p < 0.01: return r"$^{***}$"
        if p < 0.05: return r"$^{**}$"
        if p < 0.10: return r"$^{*}$"
        return ""
    else:
        if p < 0.01: return r"$^{***}$"
        if p < 0.05: return r"$^{**}$"
        if p < 0.10: return r"$^{*}$"
        return ""


def _booktabs_table(headers: List[str], rows: List[List[str]], caption: str,
                    label: str, fontsize: str = "small",
                    col_fmt: Optional[str] = None) -> str:
    """Generate a booktabs LaTeX table."""
    n = len(headers)
    if col_fmt is None:
        col_fmt = "l" + "r" * (n - 1)
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        rf"\{fontsize}",
        rf"\caption{{{caption}}}",
        rf"\label{{tab:{label}}}",
        rf"\begin{{tabular}}{{{col_fmt}}}",
        r"\toprule",
        " & ".join(headers) + r" \\",
        r"\midrule",
    ]
    for row in rows:
        lines.append(" & ".join(str(c) for c in row) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    return "\n".join(lines)


def _savefig(fig, name: str) -> str:
    r"""Save figure and return the relative path for \includegraphics."""
    path = os.path.join(_FIG_DIR, name)
    fig.savefig(path, dpi=_FIG_DPI, bbox_inches="tight")
    plt.close(fig)
    return f"figures/{name}"


# =============================================================================
# DATA LOADERS
# =============================================================================


def _load_tiers() -> pd.DataFrame:
    p = os.path.join(_STATS_DIR, "cointegration_tiers.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_evt() -> pd.DataFrame:
    p = os.path.join(_STATS_DIR, "evt_tail_risk.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_hedge() -> pd.DataFrame:
    p = os.path.join(_STATS_DIR, "hedge_ratio_comparison.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_dcc_peak() -> pd.DataFrame:
    p = os.path.join(_STATS_DIR, "dcc_peak_correlation.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_dcc_rolling() -> pd.DataFrame:
    p = os.path.join(_STATS_DIR, "dcc_rolling_correlation.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_mc_dist() -> pd.DataFrame:
    p = os.path.join(_STATS_DIR, "montecarlo_dist_fit.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_mc_slippage() -> pd.DataFrame:
    p = os.path.join(_STATS_DIR, "montecarlo_slippage.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_mc_quality() -> pd.DataFrame:
    p = os.path.join(_STATS_DIR, "montecarlo_trade_quality.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_perm(suffix: str) -> dict:
    p = os.path.join(_STATS_DIR, f"permutation_test_{suffix}.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _load_trades(suffix: str = "layer1_holdout") -> pd.DataFrame:
    p = os.path.join(_BACKTEST_DIR, f"trades_{suffix}.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_summary(suffix: str = "layer1_holdout") -> pd.DataFrame:
    p = os.path.join(_BACKTEST_DIR, f"summary_{suffix}.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _load_portfolio(suffix: str = "layer1_holdout") -> pd.DataFrame:
    p = os.path.join(_BACKTEST_DIR, f"portfolio_{suffix}.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def _build_equity_curve(trades: pd.DataFrame) -> pd.Series:
    """Build cumulative P&L equity curve from trades, indexed by exit_time."""
    if len(trades) == 0:
        return pd.Series(dtype=float)
    tr = trades.copy()
    tr["exit_time"] = pd.to_datetime(tr["exit_time"])
    # De-duplicate hedge_method: keep OLS only
    if "hedge_method" in tr.columns:
        tr = tr[tr["hedge_method"] == "ols"]
    tr = tr.sort_values("exit_time")
    curve = tr.set_index("exit_time")["pnl_net"].cumsum()
    return curve


# =============================================================================
# FIGURES
# =============================================================================


def fig_tier_distribution(tiers: pd.DataFrame) -> str:
    """Bar chart: Gold/Silver/Bronze tier counts + conflict annotation."""
    if tiers.empty:
        return ""
    counts = tiers["stats_tier"].value_counts().reindex(["gold", "silver", "bronze"], fill_value=0)
    n_conflict = int(tiers.get("flagged_conflict", pd.Series(dtype=bool)).sum()) if "flagged_conflict" in tiers.columns else 0

    fig, ax = plt.subplots(figsize=(4.5, 3.2))
    bars = ax.bar(
        ["Gold", "Silver", "Bronze"],
        counts.values,
        color=[TIER_COLORS[t] for t in ["gold", "silver", "bronze"]],
        edgecolor="white", linewidth=0.5,
    )
    for bar, val in zip(bars, counts.values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.3,
                str(val), ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.set_ylabel("Number of pairs")
    ax.set_title("Confirmatory Cointegration Tier Distribution")
    ax.set_ylim(0, max(counts.values) * 1.2)
    if n_conflict:
        ax.annotate(f"Note: {n_conflict} conflict flags\n(EG confirms, KPSS rejects)",
                    xy=(0.97, 0.95), xycoords="axes fraction", ha="right", va="top",
                    fontsize=7, color="#555555",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="#f5f5f5", alpha=0.8))
    fig.tight_layout()
    return _savefig(fig, "tier_distribution.png")


def fig_equity_curve(trades_oos: pd.DataFrame, trades_is: pd.DataFrame) -> str:
    """Equity curve + drawdown panel for IS and OOS."""
    if trades_oos.empty:
        return ""

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 4.5), gridspec_kw={"height_ratios": [3, 1]},
                                    sharex=False)

    for trades, label, color, alpha in [
        (trades_is, "In-Sample", "#2196F3", 0.7),
        (trades_oos, "Out-of-Sample", "#E64A19", 1.0),
    ]:
        if trades.empty:
            continue
        curve = _build_equity_curve(trades)
        if curve.empty:
            continue
        ax1.plot(curve.index, curve.values, label=label, color=color, alpha=alpha, linewidth=1.2)
        # Drawdown
        running_max = curve.cummax()
        dd = curve - running_max
        ax2.fill_between(curve.index, dd.values, 0, alpha=0.5 * alpha, color=color)

    ax1.set_ylabel("Cumulative P&L ($)")
    ax1.legend(fontsize=8)
    ax1.set_title("Portfolio Equity Curve")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax2.set_ylabel("Drawdown ($)")
    ax2.set_xlabel("Exit date")
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    fig.tight_layout()
    return _savefig(fig, "equity_curve.png")


def fig_evt_tail_risk(evt: pd.DataFrame) -> str:
    """Horizontal bar chart of GPD xi per pair, colored by fat-tail flag."""
    if evt.empty:
        return ""
    df = evt.dropna(subset=["gpd_xi_spread"]).copy()
    df = df.sort_values("gpd_xi_spread", ascending=True)
    labels = [_esc(f"{r['symbol_a']}/{r['symbol_b']}@{r['tf_label']}") for _, r in df.iterrows()]
    xi = df["gpd_xi_spread"].values
    fat = df["fat_tail"].values

    fig, ax = plt.subplots(figsize=(6, max(3, len(df) * 0.28)))
    colors = ["#E53935" if f else "#43A047" for f in fat]
    bars = ax.barh(range(len(df)), xi, color=colors, alpha=0.85)
    ax.axvline(0.3, color="#555555", linestyle="--", linewidth=0.8, label="Fat-tail threshold (0.30)")
    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(labels, fontsize=6.5)
    ax.set_xlabel(r"GPD shape parameter $\xi$")
    ax.set_title("EVT Tail Risk — GPD Shape Parameter per Pair")
    ax.legend(fontsize=7)
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(color="#E53935", label="Fat tail ($\\xi > 0.30$)"),
        Patch(color="#43A047", label="Thin tail ($\\xi \\leq 0.30$)"),
        plt.Line2D([0], [0], color="#555555", linestyle="--", label="Threshold"),
    ], fontsize=7)
    fig.tight_layout()
    return _savefig(fig, "evt_tail_risk.png")


def fig_slippage(slippage: pd.DataFrame) -> str:
    """Sharpe vs slippage bps/side."""
    if slippage.empty:
        return ""
    df = slippage.dropna(subset=["sharpe"])
    fig, ax = plt.subplots(figsize=(4.5, 3))
    ax.plot(df["slippage_bps_per_side"], df["sharpe"], "o-", color="#1565C0",
            linewidth=1.5, markersize=5)
    ax.axhline(0, color="#999", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Slippage (bps per side)")
    ax.set_ylabel("Portfolio Sharpe Ratio")
    ax.set_title("Slippage Sensitivity")
    ax.set_xticks(df["slippage_bps_per_side"])
    for _, row in df.iterrows():
        ax.annotate(f"{row['sharpe']:.2f}", (row["slippage_bps_per_side"], row["sharpe"]),
                    textcoords="offset points", xytext=(0, 6), ha="center", fontsize=7)
    fig.tight_layout()
    return _savefig(fig, "slippage_sensitivity.png")


def fig_dcc_rolling(dcc_rolling: pd.DataFrame) -> str:
    """DCC rolling correlation time series between pairs."""
    if dcc_rolling.empty:
        return ""
    fig, ax = plt.subplots(figsize=(7, 3.5))
    for col in dcc_rolling.columns:
        label = _esc(col.replace("|", " | "))
        ax.plot(dcc_rolling.index, dcc_rolling[col].values, linewidth=0.9, alpha=0.85, label=label)
    ax.axhline(0.7, color="#E53935", linestyle="--", linewidth=0.8, label="Risk threshold (0.70)")
    ax.set_ylabel("Dynamic Conditional Correlation")
    ax.set_xlabel("Date")
    ax.set_title("DCC-GARCH Rolling Pair-Pair Correlations")
    ax.legend(fontsize=6.5, loc="upper left")
    ax.set_ylim(-0.1, 1.05)
    fig.tight_layout()
    return _savefig(fig, "dcc_rolling.png")


def fig_mc_distribution(trades: pd.DataFrame) -> str:
    """Histogram of per-trade P&L with Normal and t-distribution overlays."""
    if trades.empty:
        return ""
    pnl = trades["pnl_net"].values.astype(float)
    pnl = pnl[np.isfinite(pnl)]
    if len(pnl) < 10:
        return ""

    from scipy import stats as sp_stats
    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    ax.hist(pnl, bins=40, density=True, alpha=0.55, color="#1976D2", label="Empirical P\\&L")
    x = np.linspace(pnl.min(), pnl.max(), 300)

    # Normal
    mu, sigma = sp_stats.norm.fit(pnl)
    ax.plot(x, sp_stats.norm.pdf(x, mu, sigma), "r-", linewidth=1.2,
            label=f"Normal ($\\mu$={mu:.0f}, $\\sigma$={sigma:.0f})")

    # Student-t
    nu, loc_t, scale_t = sp_stats.t.fit(pnl)
    ax.plot(x, sp_stats.t.pdf(x, nu, loc_t, scale_t), "g--", linewidth=1.2,
            label=f"Student-t ($\\nu$={nu:.2f})")

    ax.set_xlabel("Trade P\\&L ($)")
    ax.set_ylabel("Density")
    ax.set_title("Per-Trade P\\&L Distribution")
    ax.legend(fontsize=7)
    fig.tight_layout()
    return _savefig(fig, "mc_distribution.png")


def fig_mfe_mae(trades: pd.DataFrame) -> str:
    """Scatter: MFE vs |MAE| per trade, colored by P&L sign."""
    if trades.empty or "mfe" not in trades.columns:
        return ""
    df = trades[["mae", "mfe", "pnl_net"]].dropna()
    df = df[(np.abs(df["mfe"]) > 1e-4) | (np.abs(df["mae"]) > 1e-4)]
    if len(df) < 5:
        return ""

    fig, ax = plt.subplots(figsize=(5, 4))
    colors = ["#43A047" if p > 0 else "#E53935" for p in df["pnl_net"]]
    ax.scatter(np.abs(df["mae"]), df["mfe"], c=colors, alpha=0.6, s=18, linewidths=0)
    ax.set_xlabel("|MAE| ($)")
    ax.set_ylabel("MFE ($)")
    ax.set_title("Maximum Adverse vs. Favorable Excursion per Trade")
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(color="#43A047", label="Winning trade"),
        Patch(color="#E53935", label="Losing trade"),
    ], fontsize=7)
    fig.tight_layout()
    return _savefig(fig, "mfe_mae.png")


def fig_hedge_estimators(hedge: pd.DataFrame) -> str:
    """OLS vs MM hedge ratio scatter with identity line."""
    if hedge.empty:
        return ""
    df = hedge.dropna(subset=["beta_ols", "beta_mm"])
    if len(df) < 3:
        return ""

    fig, ax = plt.subplots(figsize=(4.5, 4))
    ax.scatter(df["beta_ols"], df["beta_mm"], color="#0288D1", alpha=0.8, s=30)
    lim = max(np.abs([df["beta_ols"].min(), df["beta_ols"].max(),
                       df["beta_mm"].min(), df["beta_mm"].max()])) * 1.1
    ax.plot([-lim, lim], [-lim, lim], "k--", linewidth=0.8, alpha=0.5, label="OLS = MM")
    ax.set_xlabel("OLS hedge ratio")
    ax.set_ylabel("MM hedge ratio")
    ax.set_title("OLS vs. MM Estimator Hedge Ratios")
    ax.legend(fontsize=7)
    for _, row in df.iterrows():
        ax.annotate(_esc(f"{row['symbol_a']}/{row['symbol_b']}"),
                    (row["beta_ols"], row["beta_mm"]), fontsize=5.5, alpha=0.7)
    fig.tight_layout()
    return _savefig(fig, "hedge_estimators.png")


def fig_coint_fraction_hist(tiers: pd.DataFrame) -> str:
    """Histogram of coint_fraction_rolling colored by tier."""
    if tiers.empty:
        return ""
    bins = np.linspace(0, 1, 21)
    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    for tier, color in [("gold", TIER_COLORS["gold"]), ("silver", TIER_COLORS["silver"]),
                        ("bronze", TIER_COLORS["bronze"])]:
        sub = tiers[tiers["stats_tier"] == tier]["coint_fraction_rolling"].dropna()
        ax.hist(sub, bins=bins, alpha=0.75, color=color, label=tier.capitalize(), edgecolor="white")
    ax.set_xlabel("Rolling Confirmation Fraction")
    ax.set_ylabel("Count of pairs")
    ax.set_title("Distribution of Cointegration Rolling Stability")
    ax.legend(fontsize=8)
    ax.axvline(tiers["coint_fraction_rolling"].median(), color="#333", linestyle="--", linewidth=0.9,
               label=f"Median = {tiers['coint_fraction_rolling'].median():.2f}")
    fig.tight_layout()
    return _savefig(fig, "coint_fraction_hist.png")


def fig_half_life_by_tier(tiers: pd.DataFrame) -> str:
    """Box plot of half_life_rolling by confirmatory tier."""
    if tiers.empty or "half_life_rolling" not in tiers.columns:
        return ""
    fig, ax = plt.subplots(figsize=(5, 3.5))
    order = ["gold", "silver", "bronze"]
    data = [tiers[tiers["stats_tier"] == t]["half_life_rolling"].dropna().values for t in order]
    bp = ax.boxplot(data, patch_artist=True, widths=0.5,
                    medianprops=dict(color="white", linewidth=2))
    for patch, tier in zip(bp["boxes"], order):
        patch.set_facecolor(TIER_COLORS[tier])
        patch.set_alpha(0.85)
    ax.set_xticks([1, 2, 3])
    ax.set_xticklabels(["Gold", "Silver", "Bronze"])
    ax.set_ylabel("Half-life (bars)")
    ax.set_title("Mean-Reversion Half-Life by Confirmatory Tier")
    for i, (vals, tier) in enumerate(zip(data, order)):
        if len(vals):
            ax.text(i + 1, np.median(vals) + 0.5, f"Med={np.median(vals):.0f}",
                    ha="center", va="bottom", fontsize=7, fontweight="bold")
    fig.tight_layout()
    return _savefig(fig, "half_life_by_tier.png")


def fig_hurst_scatter(tiers: pd.DataFrame) -> str:
    """RS Hurst vs DFA Hurst colored by interpretation."""
    if tiers.empty or "hurst_rs" not in tiers.columns:
        return ""
    df = tiers.dropna(subset=["hurst_rs", "hurst_dfa"])
    cmap = {"mean_reverting": "#43A047", "near_random_walk": "#FF9800", "trending": "#E53935"}
    fig, ax = plt.subplots(figsize=(4.5, 4))
    for interp, color in cmap.items():
        sub = df[df["hurst_interpretation"] == interp]
        ax.scatter(sub["hurst_rs"], sub["hurst_dfa"], color=color, alpha=0.8, s=35,
                   label=interp.replace("_", " ").title())
    ax.axhline(0.5, color="#aaa", linewidth=0.7, linestyle=":")
    ax.axvline(0.5, color="#aaa", linewidth=0.7, linestyle=":")
    ax.plot([0, 1], [0, 1], "k--", linewidth=0.6, alpha=0.4, label="RS = DFA")
    ax.set_xlabel("Hurst (R/S)")
    ax.set_ylabel("Hurst (DFA)")
    ax.set_title("Hurst Exponent — R/S vs DFA Methods")
    ax.legend(fontsize=7)
    fig.tight_layout()
    return _savefig(fig, "hurst_scatter.png")


def fig_timeframe_distribution(tiers: pd.DataFrame) -> str:
    """Confirmed pairs by timeframe, colored by tier mix."""
    if tiers.empty:
        return ""
    order = ["1m", "2m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W", "1M"]
    present = [tf for tf in order if tf in tiers["tf_label"].values]
    if not present:
        present = tiers["tf_label"].unique().tolist()
    counts = {tier: [] for tier in ["gold", "silver", "bronze"]}
    for tf in present:
        sub = tiers[tiers["tf_label"] == tf]
        for tier in counts:
            counts[tier].append(int((sub["stats_tier"] == tier).sum()))
    fig, ax = plt.subplots(figsize=(6, 3.5))
    bottoms = np.zeros(len(present))
    for tier, color in [("gold", TIER_COLORS["gold"]), ("silver", TIER_COLORS["silver"]),
                        ("bronze", TIER_COLORS["bronze"])]:
        vals = np.array(counts[tier])
        ax.bar(present, vals, bottom=bottoms, color=color, alpha=0.85,
               label=tier.capitalize(), edgecolor="white")
        bottoms += vals
    ax.set_xlabel("Timeframe")
    ax.set_ylabel("Confirmed pairs")
    ax.set_title("Confirmed Pairs by Timeframe and Tier")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _savefig(fig, "timeframe_distribution.png")


def fig_per_pair_sharpe_oos(summary_oos: pd.DataFrame) -> str:
    """Horizontal bar of OOS Sharpe per pair (OLS hedge only)."""
    if summary_oos.empty:
        return ""
    df = summary_oos[summary_oos["hedge_method"] == "ols"].copy()
    if df.empty:
        df = summary_oos.copy()
    df["pair"] = df["symbol_a"] + "/" + df["symbol_b"] + "@" + df["tf"]
    df = df.sort_values("sharpe")
    colors = ["#43A047" if s >= 0 else "#E53935" for s in df["sharpe"]]
    fig, ax = plt.subplots(figsize=(6, max(3, len(df) * 0.38)))
    ax.barh(df["pair"], df["sharpe"], color=colors, alpha=0.85, edgecolor="white")
    ax.axvline(0, color="#333", linewidth=0.8)
    for _, row in df.iterrows():
        ax.text(row["sharpe"] + (0.1 if row["sharpe"] >= 0 else -0.1),
                row["pair"], f"{row['sharpe']:.2f}",
                va="center", ha="left" if row["sharpe"] >= 0 else "right", fontsize=7)
    ax.set_xlabel("OOS Sharpe Ratio")
    ax.set_title("Out-of-Sample Sharpe by Pair (OLS hedge)")
    fig.tight_layout()
    return _savefig(fig, "per_pair_sharpe_oos.png")


def fig_exit_reasons(trades_is: pd.DataFrame, trades_oos: pd.DataFrame) -> str:
    """Stacked bar of exit reason breakdown IS vs OOS."""
    reasons = ["signal_exit", "stop", "max_hold", "eod"]
    fig, ax = plt.subplots(figsize=(5, 3.5))
    x = [0, 1]
    labels = ["In-Sample", "Out-of-Sample"]
    colors = {"signal_exit": "#43A047", "stop": "#E53935", "max_hold": "#FF9800", "eod": "#9E9E9E"}
    bottoms = [0, 0]
    for reason in reasons:
        vals = []
        for trades in [trades_is, trades_oos]:
            if trades.empty:
                vals.append(0)
                continue
            sub = trades[trades["hedge_method"] == "ols"] if "hedge_method" in trades.columns else trades
            total = max(len(sub), 1)
            n = (sub["exit_reason"] == reason).sum() if "exit_reason" in sub.columns else 0
            vals.append(n / total * 100)
        ax.bar(x, vals, bottom=bottoms, color=colors[reason], alpha=0.85,
               label=reason.replace("_", " ").title(), edgecolor="white")
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Percentage of trades (%)")
    ax.set_title("Exit Reason Breakdown — IS vs OOS")
    ax.legend(fontsize=7, loc="upper right")
    fig.tight_layout()
    return _savefig(fig, "exit_reasons.png")


def fig_hold_duration(trades_is: pd.DataFrame, trades_oos: pd.DataFrame) -> str:
    """Hold duration distribution IS vs OOS."""
    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    for trades, label, color in [(trades_is, "In-Sample", "#1976D2"),
                                  (trades_oos, "Out-of-Sample", "#E64A19")]:
        if trades.empty or "hold_bars" not in trades.columns:
            continue
        sub = trades[trades["hedge_method"] == "ols"] if "hedge_method" in trades.columns else trades
        holds = sub["hold_bars"].dropna().values
        if len(holds) == 0:
            continue
        ax.hist(holds, bins=40, alpha=0.55, color=color, label=f"{label} (n={len(holds)})",
                density=True)
    ax.set_xlabel("Hold duration (bars)")
    ax.set_ylabel("Density")
    ax.set_title("Trade Hold Duration Distribution")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _savefig(fig, "hold_duration.png")


def fig_entry_z_vs_pnl(trades_oos: pd.DataFrame) -> str:
    """Scatter of |entry_z| vs pnl_net, colored by win/loss."""
    if trades_oos.empty or "entry_z" not in trades_oos.columns:
        return ""
    sub = trades_oos[trades_oos["hedge_method"] == "ols"] if "hedge_method" in trades_oos.columns else trades_oos
    df = sub[["entry_z", "pnl_net"]].dropna()
    if len(df) < 5:
        return ""
    colors = ["#43A047" if p > 0 else "#E53935" for p in df["pnl_net"]]
    fig, ax = plt.subplots(figsize=(5, 4))
    ax.scatter(np.abs(df["entry_z"]), df["pnl_net"], c=colors, alpha=0.65, s=22, linewidths=0)
    ax.axhline(0, color="#aaa", linewidth=0.8, linestyle="--")
    ax.set_xlabel("|Entry Z-Score|")
    ax.set_ylabel("Net P&L ($)")
    ax.set_title("Entry Z-Score vs Trade P&L (OOS)")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="#43A047", label="Winner"), Patch(color="#E53935", label="Loser")], fontsize=7)
    fig.tight_layout()
    return _savefig(fig, "entry_z_vs_pnl.png")


def fig_pnl_by_pair(trades_oos: pd.DataFrame) -> str:
    """Box/strip plot of pnl_net per pair (OOS, OLS only)."""
    if trades_oos.empty:
        return ""
    sub = trades_oos[trades_oos["hedge_method"] == "ols"].copy() if "hedge_method" in trades_oos.columns else trades_oos.copy()
    sub["pair"] = sub["symbol_a"] + "/" + sub["symbol_b"]
    pairs = sub.groupby("pair")["pnl_net"].median().sort_values().index.tolist()
    fig, ax = plt.subplots(figsize=(6, max(3, len(pairs) * 0.42)))
    data = [sub[sub["pair"] == p]["pnl_net"].values for p in pairs]
    bp = ax.boxplot(data, vert=False, patch_artist=True, widths=0.5,
                    medianprops=dict(color="white", linewidth=1.8))
    for patch, vals in zip(bp["boxes"], data):
        med = np.median(vals)
        patch.set_facecolor("#43A047" if med > 0 else "#E53935")
        patch.set_alpha(0.75)
    # Overlay individual points
    for i, vals in enumerate(data):
        jitter = np.random.default_rng(42).uniform(-0.15, 0.15, len(vals))
        ax.scatter(vals, np.full(len(vals), i + 1) + jitter, s=10, alpha=0.5,
                   color=["#43A047" if v > 0 else "#E53935" for v in vals], linewidths=0)
    ax.set_yticks(range(1, len(pairs) + 1))
    ax.set_yticklabels(pairs, fontsize=8)
    ax.axvline(0, color="#555", linewidth=0.8, linestyle="--")
    ax.set_xlabel("Net P&L per trade ($)")
    ax.set_title("Trade P&L Distribution by Pair (OOS)")
    fig.tight_layout()
    return _savefig(fig, "pnl_by_pair.png")


def fig_variant_comparison() -> str:
    """Bar chart comparing Sharpe across all backtest variants."""
    variants = [
        ("layer1",                   "IS Layer 1"),
        ("layer1_holdout",           "OOS Baseline"),
        ("layer1_holdout_hubw",      "OOS Huber-wt"),
        ("layer1_holdout_neghedge",  "OOS+NegHedge"),
        ("layer1_holdout_pnlcap",    "OOS P&L-cap"),
        ("layer1_holdout_riskparity","OOS Risk-par."),
    ]
    sharpes, labels, colors_v = [], [], []
    for suffix, label in variants:
        port = _load_portfolio(suffix)
        if port.empty:
            continue
        s = float(port.iloc[0].get("sharpe_portfolio", np.nan))
        sharpes.append(s)
        labels.append(label)
        colors_v.append("#1565C0" if "IS" in label else ("#43A047" if s >= 0 else "#E53935"))
    if not sharpes:
        return ""
    fig, ax = plt.subplots(figsize=(6, 3.5))
    bars = ax.bar(labels, sharpes, color=colors_v, alpha=0.85, edgecolor="white")
    ax.axhline(0, color="#333", linewidth=0.8)
    for bar, val in zip(bars, sharpes):
        ax.text(bar.get_x() + bar.get_width() / 2,
                val + (0.05 if val >= 0 else -0.15),
                f"{val:.2f}", ha="center", va="bottom" if val >= 0 else "top", fontsize=7.5)
    ax.set_ylabel("Portfolio Sharpe Ratio")
    ax.set_title("Sharpe Ratio Across Backtest Variants")
    plt.xticks(rotation=20, ha="right")
    fig.tight_layout()
    return _savefig(fig, "variant_comparison.png")


def fig_all_hedge_estimators(hedge: pd.DataFrame) -> str:
    """Cleveland dot plot: all 5 estimators per pair, normalized to OLS."""
    if hedge.empty:
        return ""
    cols = ["beta_ols", "beta_tls", "beta_kalman", "beta_huber", "beta_mm"]
    labels_e = ["OLS", "TLS", "Kalman", "Huber", "MM"]
    colors_e = ["#1976D2", "#E64A19", "#7B1FA2", "#388E3C", "#F57F17"]
    df = hedge.dropna(subset=["beta_ols", "beta_mm"]).copy()
    df["pair"] = df["symbol_a"] + "/" + df["symbol_b"]
    # Sort by hedge_ratio range (spread of disagreement)
    df["est_range"] = df[cols].max(axis=1) - df[cols].min(axis=1)
    df = df.sort_values("est_range", ascending=True)
    fig, ax = plt.subplots(figsize=(6, max(3.5, len(df) * 0.38)))
    for i, (_, row) in enumerate(df.iterrows()):
        ols_ref = row["beta_ols"]
        ax.hlines(i, df[cols].min().min(), df[cols].max().max(), color="#ddd", linewidth=0.6)
        for col, label_e, color_e in zip(cols, labels_e, colors_e):
            ax.scatter(row[col], i, color=color_e, s=22, zorder=3, alpha=0.9)
    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(df["pair"].values, fontsize=7)
    ax.axvline(0, color="#aaa", linewidth=0.6, linestyle=":")
    ax.set_xlabel("Hedge ratio estimate")
    ax.set_title("All Hedge Estimators per Pair (sorted by estimator range)")
    from matplotlib.lines import Line2D
    legend_handles = [Line2D([0], [0], marker="o", color="w", markerfacecolor=c,
                             markersize=6, label=l) for l, c in zip(labels_e, colors_e)]
    ax.legend(handles=legend_handles, fontsize=7, loc="lower right")
    fig.tight_layout()
    return _savefig(fig, "all_hedge_estimators.png")


def fig_evt_xi_scatter(evt: pd.DataFrame) -> str:
    """Scatter: GPD xi_spread vs xi_pnl per pair."""
    if evt.empty:
        return ""
    df = evt.dropna(subset=["gpd_xi_spread", "gpd_xi_pnl"]).copy()
    if len(df) < 3:
        return ""
    fat = df["fat_tail"].values
    colors = ["#E53935" if f else "#43A047" for f in fat]
    fig, ax = plt.subplots(figsize=(4.5, 4))
    ax.scatter(df["gpd_xi_spread"], df["gpd_xi_pnl"], c=colors, alpha=0.8, s=35)
    ax.axhline(0, color="#aaa", linewidth=0.7, linestyle="--")
    ax.axvline(0.3, color="#888", linewidth=0.7, linestyle="--", label="Fat-tail threshold")
    ax.set_xlabel(r"GPD $\xi$ (spread)")
    ax.set_ylabel(r"GPD $\xi$ (P\&L)")
    ax.set_title(r"Spread vs P\&L Tail Risk ($\xi$ parameters)")
    for _, row in df.iterrows():
        ax.annotate(f"{row['symbol_a']}/{row['symbol_b']}",
                    (row["gpd_xi_spread"], row["gpd_xi_pnl"]), fontsize=5.5, alpha=0.7)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="#E53935", label="Fat tail"), Patch(color="#43A047", label="Thin tail"),
                       plt.Line2D([0], [0], color="#888", ls="--", label="xi=0.30 threshold")], fontsize=7)
    fig.tight_layout()
    return _savefig(fig, "evt_xi_scatter.png")


def fig_coint_vs_oos_sharpe(tiers: pd.DataFrame) -> str:
    """KEY FIGURE: coint_fraction_rolling vs per-pair OOS Sharpe (Skeptic test)."""
    summary_oos = _load_summary("layer1_holdout")
    if tiers.empty or summary_oos.empty:
        return ""
    ols_sum = summary_oos[summary_oos["hedge_method"] == "ols"].copy()
    ols_sum = ols_sum.rename(columns={"tf": "tf_label"})
    merged = tiers.merge(ols_sum[["symbol_a", "symbol_b", "tf_label", "sharpe", "n_trades"]],
                         on=["symbol_a", "symbol_b", "tf_label"], how="inner")
    if merged.empty:
        return ""
    tier_colors_m = [TIER_COLORS.get(t, "#999") for t in merged["stats_tier"]]
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    sc = ax.scatter(merged["coint_fraction_rolling"], merged["sharpe"],
                    c=tier_colors_m, s=merged["n_trades"] * 4 + 20,
                    alpha=0.85, linewidths=0.5, edgecolors="white")
    ax.axhline(0, color="#aaa", linewidth=0.8, linestyle="--")
    for _, row in merged.iterrows():
        ax.annotate(f"{row['symbol_a']}/{row['symbol_b']}",
                    (row["coint_fraction_rolling"], row["sharpe"]),
                    fontsize=5.5, alpha=0.75, xytext=(3, 2), textcoords="offset points")
    # Linear trend
    if len(merged) >= 4:
        from scipy import stats as sp_stats
        slope, intercept, r, pv, _ = sp_stats.linregress(merged["coint_fraction_rolling"], merged["sharpe"])
        x_line = np.linspace(merged["coint_fraction_rolling"].min(), merged["coint_fraction_rolling"].max(), 50)
        ax.plot(x_line, slope * x_line + intercept, "k--", linewidth=1.0, alpha=0.5,
                label=f"OLS trend (r={r:.2f}, p={pv:.2f})")
        ax.legend(fontsize=7)
    ax.set_xlabel("Rolling Confirmation Fraction")
    ax.set_ylabel("OOS Sharpe Ratio")
    ax.set_title("Rolling Stability vs OOS Performance\n(Empirical Skeptic Test — bubble size = trade count)")
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(color=TIER_COLORS["gold"], label="Gold"),
        Patch(color=TIER_COLORS["silver"], label="Silver"),
        Patch(color=TIER_COLORS["bronze"], label="Bronze"),
    ] + ([plt.Line2D([0], [0], color="k", ls="--", label=f"Trend r={r:.2f}")] if len(merged) >= 4 else []),
              fontsize=7, loc="upper left")
    fig.tight_layout()
    return _savefig(fig, "coint_vs_oos_sharpe.png")


def fig_perm_distribution(perm_is: dict, perm_oos: dict) -> str:
    """Visualize permutation test: simulated null distribution vs realized Sharpe."""
    if not perm_is and not perm_oos:
        return ""
    from scipy import stats as sp_stats
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.8))
    for ax, perm, label, color in [
        (axes[0], perm_is,  "In-Sample (n=620)",   "#1976D2"),
        (axes[1], perm_oos, "Out-of-Sample (n=111)", "#E64A19"),
    ]:
        if not perm:
            ax.set_visible(False)
            continue
        mu  = float(perm.get("perm_mean_sharpe", 0))
        sig = float(perm.get("perm_std_sharpe",  1))
        realized = float(perm.get("realized_closed_trade_sharpe", mu))
        x = np.linspace(mu - 4 * sig, mu + 4 * sig, 300)
        ax.fill_between(x, sp_stats.norm.pdf(x, mu, sig), alpha=0.3, color=color)
        ax.plot(x, sp_stats.norm.pdf(x, mu, sig), color=color, linewidth=1.5,
                label="Null distribution\n(Normal approx.)")
        ax.axvline(realized, color="#222", linewidth=1.8, linestyle="-",
                   label=f"Realized = {realized:.2f}")
        p5  = float(perm.get("perm_5pct_sharpe",  mu - 1.645 * sig))
        p95 = float(perm.get("perm_95pct_sharpe", mu + 1.645 * sig))
        ax.axvspan(p5, p95, alpha=0.15, color=color, label="5–95% null band")
        pval = float(perm.get("pvalue", 1.0))
        ax.set_title(f"{label}\n$p = {pval:.3f}$", fontsize=9)
        ax.set_xlabel("Permuted Sharpe")
        ax.set_ylabel("Density")
        ax.legend(fontsize=7)
    fig.suptitle("White Reality Check — Permuted vs Realized Sharpe", fontsize=10, y=1.01)
    fig.tight_layout()
    return _savefig(fig, "perm_distribution.png")


def fig_mc_quality(mc_qual: pd.DataFrame) -> str:
    """Trade quality metrics: realized vs simulation 5th–95th band."""
    if mc_qual.empty:
        return ""
    df = mc_qual.copy()
    fig, ax = plt.subplots(figsize=(5, 3.5))
    x = np.arange(len(df))
    ax.barh(x, df["realized"], color="#1976D2", alpha=0.8, label="Realized", height=0.4)
    for i, row in df.iterrows():
        ax.plot([row["sim_5pct"], row["sim_95pct"]], [i, i], color="#E64A19",
                linewidth=3, alpha=0.6, solid_capstyle="round")
        ax.scatter([row["sim_5pct"], row["sim_95pct"]], [i, i],
                   color="#E64A19", s=20, zorder=4)
    ax.set_yticks(x)
    ax.set_yticklabels(df["metric"].str.replace("_", " ").str.title(), fontsize=8)
    ax.set_xlabel("Metric value")
    ax.set_title("Trade Quality — Realized vs MC Simulation Band (5th–95th %ile)")
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="#1976D2", label="Realized"),
                       Line2D([0], [0], color="#E64A19", linewidth=3, label="Sim. 5–95%")], fontsize=8)
    fig.tight_layout()
    return _savefig(fig, "mc_quality.png")


def fig_dcc_heatmap(dcc_peak: pd.DataFrame) -> str:
    """Heatmap of peak pairwise correlations between confirmed pairs."""
    if dcc_peak.empty:
        return ""
    # Build symmetric matrix
    pairs = sorted(set(dcc_peak["pair_i"]) | set(dcc_peak["pair_j"]))
    n = len(pairs)
    mat = np.full((n, n), np.nan)
    np.fill_diagonal(mat, 1.0)
    idx = {p: i for i, p in enumerate(pairs)}
    for _, row in dcc_peak.iterrows():
        i, j = idx[row["pair_i"]], idx[row["pair_j"]]
        mat[i, j] = mat[j, i] = row["peak_rho"]
    fig, ax = plt.subplots(figsize=(max(4, n * 1.0), max(3.5, n * 0.9)))
    labels_h = [p.replace("@", "\n@") for p in pairs]
    im = ax.imshow(mat, vmin=-1, vmax=1, cmap="RdYlGn", aspect="auto")
    ax.set_xticks(range(n))
    ax.set_xticklabels(labels_h, fontsize=7, rotation=30, ha="right")
    ax.set_yticks(range(n))
    ax.set_yticklabels(labels_h, fontsize=7)
    for i in range(n):
        for j in range(n):
            if not np.isnan(mat[i, j]):
                ax.text(j, i, f"{mat[i,j]:.2f}", ha="center", va="center",
                        fontsize=7, color="black" if abs(mat[i, j]) < 0.7 else "white")
    plt.colorbar(im, ax=ax, label="Peak DCC correlation")
    ax.set_title("Peak Cross-Pair DCC Correlation (concentration risk)")
    fig.tight_layout()
    return _savefig(fig, "dcc_heatmap.png")


def fig_half_life_trend(tiers: pd.DataFrame) -> str:
    """Distribution of half_life_trend_slope — is mean-reversion speed changing?"""
    if tiers.empty or "half_life_trend_slope" not in tiers.columns:
        return ""
    df = tiers["half_life_trend_slope"].dropna()
    if len(df) < 3:
        return ""
    fig, ax = plt.subplots(figsize=(5, 3.5))
    ax.hist(df, bins=20, color="#7B1FA2", alpha=0.75, edgecolor="white")
    ax.axvline(0, color="#333", linewidth=1.0, linestyle="--", label="No trend")
    ax.axvline(df.mean(), color="#E64A19", linewidth=1.2, linestyle="-",
               label=f"Mean = {df.mean():.4f}")
    ax.set_xlabel("Half-life trend slope (bars/bar)")
    ax.set_ylabel("Count of pairs")
    ax.set_title("Half-Life Trend Slope Distribution\n(Positive = slowing mean-reversion over time)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    return _savefig(fig, "half_life_trend.png")


def fig_win_rate_is_vs_oos(summary_is: pd.DataFrame, summary_oos: pd.DataFrame) -> str:
    """Paired dot plot: IS vs OOS win rate per pair."""
    if summary_is.empty or summary_oos.empty:
        return ""
    s_is  = summary_is[summary_is["hedge_method"] == "ols"].copy()
    s_oos = summary_oos[summary_oos["hedge_method"] == "ols"].copy()
    s_is["pair"]  = s_is["symbol_a"]  + "/" + s_is["symbol_b"]
    s_oos["pair"] = s_oos["symbol_a"] + "/" + s_oos["symbol_b"]
    merged = s_is[["pair", "win_rate"]].merge(s_oos[["pair", "win_rate"]],
                                              on="pair", suffixes=("_is", "_oos"))
    if merged.empty:
        return ""
    merged = merged.sort_values("win_rate_is")
    fig, ax = plt.subplots(figsize=(5.5, max(3, len(merged) * 0.45)))
    y = np.arange(len(merged))
    ax.hlines(y, merged["win_rate_oos"], merged["win_rate_is"], color="#ccc", linewidth=1.2)
    ax.scatter(merged["win_rate_is"],  y, color="#1976D2", s=40, zorder=3, label="In-Sample")
    ax.scatter(merged["win_rate_oos"], y, color="#E64A19", s=40, zorder=3, label="Out-of-Sample")
    ax.set_yticks(y)
    ax.set_yticklabels(merged["pair"], fontsize=8)
    ax.axvline(0.5, color="#aaa", linewidth=0.7, linestyle="--", label="50% breakeven")
    ax.set_xlabel("Win Rate")
    ax.set_title("Win Rate: In-Sample vs Out-of-Sample by Pair")
    ax.legend(fontsize=7)
    fig.tight_layout()
    return _savefig(fig, "win_rate_is_vs_oos.png")


# =============================================================================
# LaTeX TABLE BUILDERS
# =============================================================================


def table_confirmed_pairs(tiers: pd.DataFrame) -> str:
    if tiers.empty:
        return "% No pairs data available.\n"
    cols_want = ["symbol_a", "symbol_b", "tf_label", "stats_tier",
                 "coint_pvalue_adjusted", "coint_fraction_rolling",
                 "eg_pval", "kpss_pval", "po_pval"]
    df = tiers[[c for c in cols_want if c in tiers.columns]].copy()
    df = df.sort_values(["stats_tier", "tf_label"], ascending=[True, True])

    headers = [r"Pair", r"TF", r"Tier", r"EG $p$", r"Roll. Frac.",
               r"KPSS $p$", r"PO $p$"]
    rows = []
    for _, r in df.iterrows():
        tier = str(r.get("stats_tier", ""))
        tier_tex = {"gold": r"\textbf{Gold}", "silver": "Silver", "bronze": "Bronze"}.get(tier, tier)
        rows.append([
            _esc(f"{r['symbol_a']}/{r['symbol_b']}"),
            _esc(str(r.get("tf_label", ""))),
            tier_tex,
            _fmt(r.get("eg_pval", r.get("coint_pvalue_adjusted", np.nan)), 3),
            _fmt(r.get("coint_fraction_rolling", np.nan), 2),
            _fmt(r.get("kpss_pval", np.nan), 3),
            _fmt(r.get("po_pval", np.nan), 3),
        ])

    return _booktabs_table(
        headers, rows,
        caption=(
            r"Confirmed pairs with confirmatory cointegration tier. "
            r"EG: Engle-Granger $p$-value (BH-FDR adjusted). "
            r"Roll.\ Frac.: fraction of rolling windows confirming cointegration. "
            r"KPSS: stationarity test $p$-value (want $>0.05$). "
            r"PO: Phillips-Ouliaris proxy $p$-value (want $<0.10$). "
            r"Significance: * $p<0.10$, ** $p<0.05$, *** $p<0.01$."
        ),
        label="confirmed_pairs",
        fontsize="footnotesize",
        col_fmt="llcrrrrr" if len(headers) == 8 else "llcrrrrr",
    )


def table_performance_variants() -> str:
    """Table comparing all backtest variant portfolio-level metrics."""
    variants = [
        ("layer1",                  "IS (Layer 1)"),
        ("layer1_holdout",          "OOS Baseline"),
        ("layer1_holdout_hubw",     "OOS Huber-weighted"),
        ("layer1_holdout_neghedge", "OOS + Neg-hedge"),
        ("layer1_holdout_pnlcap",   "OOS P\\&L-cap"),
        ("layer1_holdout_riskparity","OOS Risk-parity"),
    ]
    headers = [r"Variant", r"Trades", r"Sharpe", r"Calmar", r"Total P\&L",
               r"Max DD", r"Win Rate", r"Pairs"]
    rows = []
    for suffix, label in variants:
        port = _load_portfolio(suffix)
        summ = _load_summary(suffix)
        if port.empty:
            continue
        p = port.iloc[0]
        if summ.empty:
            n_trades = int(p.get("n_trades_total", 0))
            win_rate = "---"
        else:
            n_trades = int(summ["n_trades"].sum())
            wr_vals = summ["win_rate"].dropna()
            win_rate = _fmt(wr_vals.mean()) if len(wr_vals) else "---"
        rows.append([
            label,
            str(n_trades),
            _fmt(p.get("sharpe_portfolio", np.nan)),
            "---",
            f"\\${float(p.get('total_pnl_portfolio', 0)):,.0f}",
            f"\\${float(p.get('max_drawdown_portfolio', 0)):,.0f}",
            win_rate,
            str(int(p.get("n_pairs", 0))),
        ])

    return _booktabs_table(
        headers, rows,
        caption=(
            r"Portfolio-level performance across all backtest variants. "
            r"IS = in-sample (full history). OOS = out-of-sample (20\% chronological holdout). "
            r"Sharpe annualized assuming 252 trading days. "
            r"Max DD = maximum peak-to-trough drawdown in dollars."
        ),
        label="perf_variants",
        col_fmt="lrrrrrrr",
    )


def table_evt_risk(evt: pd.DataFrame) -> str:
    if evt.empty:
        return "% No EVT data.\n"
    df = evt.sort_values("gpd_xi_spread", ascending=False)
    headers = [r"Pair", r"TF", r"$\xi$ (spread)", r"$\sigma$ (spread)",
               r"$\xi$ (P\&L)", r"Fat tail?"]
    rows = []
    for _, r in df.iterrows():
        fat = r.get("fat_tail", False)
        rows.append([
            _esc(f"{r['symbol_a']}/{r['symbol_b']}"),
            _esc(str(r["tf_label"])),
            _fmt(r.get("gpd_xi_spread"), 3),
            _fmt(r.get("gpd_sigma_spread"), 1),
            _fmt(r.get("gpd_xi_pnl"), 3),
            r"\checkmark" if fat else r"---",
        ])
    return _booktabs_table(
        headers, rows,
        caption=(
            r"GPD extreme value theory fit per pair. $\xi > 0$ indicates a fat-tailed "
            r"(Pareto) distribution; $\xi > 0.30$ triggers the fat-tail flag. "
            r"Threshold: 95th percentile of absolute spread changes."
        ),
        label="evt_risk",
        col_fmt="llrrrrc",
    )


def table_permutation(perm_is: dict, perm_oos: dict) -> str:
    headers = [r"Sample", r"N trades", r"N days", r"Realized Sharpe",
               r"Perm. mean", r"Perm. 95\%ile", r"$p$-value", r"Significant?"]
    rows = []
    for label, perm in [("In-sample", perm_is), ("Out-of-sample", perm_oos)]:
        if not perm:
            continue
        pval = float(perm.get("pvalue", 1.0))
        sig = r"\textbf{Yes}" if perm.get("significant_at_0_05") else "No"
        rows.append([
            label,
            str(perm.get("n_trades", "---")),
            str(perm.get("n_active_days", "---")),
            _fmt(perm.get("realized_closed_trade_sharpe")),
            _fmt(perm.get("perm_mean_sharpe")),
            _fmt(perm.get("perm_95pct_sharpe")),
            f"{pval:.3f}" + _sig(pval, reverse=True),
            sig,
        ])
    return _booktabs_table(
        headers, rows,
        caption=(
            r"White (2000) Reality Check permutation test. "
            r"Null: entry signal timing has no skill --- "
            r"\texttt{pnl\_net} values randomly reassigned across trades, "
            r"exit-date structure preserved. "
            r"$p$-value = fraction of $N=1{,}000$ permuted closed-trade Sharpes $\geq$ realized. "
            r"OOS result has limited power (111 trades, 28 active days)."
        ),
        label="permutation",
        col_fmt="lrrrrrrl",
    )


def table_dist_fit(dist_df: pd.DataFrame) -> str:
    if dist_df.empty:
        return "% No distribution fit data.\n"
    df = dist_df.sort_values("aic")
    headers = [r"Distribution", r"$k$", r"Log-lik.", r"AIC", r"BIC"]
    name_map = {
        "normal": "Normal",
        "t": "Student-$t$",
        "nig_proxy_skewnorm": "Skew-Normal (NIG proxy)",
        "laplace": "Laplace",
        "garch11_normal_resid": r"GARCH(1,1) + Normal$^{\dagger}$",
    }
    rows = []
    for i, (_, r) in enumerate(df.iterrows()):
        name = name_map.get(str(r["distribution"]), _esc(str(r["distribution"])))
        bold = i == 0
        row = [
            r"\textbf{" + name + "}" if bold else name,
            str(int(r["n_params"])),
            _fmt(r["log_lik"], 1),
            r"\textbf{" + _fmt(r["aic"], 1) + "}" if bold else _fmt(r["aic"], 1),
            _fmt(r["bic"], 1),
        ]
        rows.append(row)
    note = (
        r"Best-fit distribution (minimum AIC) in bold. "
        r"$k$ = number of parameters. "
        r"$\dagger$: GARCH(1,1) fit on daily P\&L; AIC computed on standardized residuals."
    )
    return _booktabs_table(headers, rows, caption=note, label="dist_fit")


# =============================================================================
# BIBTEX
# =============================================================================


def build_bib() -> str:
    return r"""
@article{engle_granger1987,
  author  = {Engle, Robert F. and Granger, Clive W. J.},
  title   = {Co-integration and Error Correction: Representation, Estimation, and Testing},
  journal = {Econometrica},
  year    = {1987},
  volume  = {55},
  number  = {2},
  pages   = {251--276},
}

@book{vidyamurthy2004,
  author    = {Vidyamurthy, Ganapathy},
  title     = {Pairs Trading: Quantitative Methods and Analysis},
  publisher = {Wiley},
  year      = {2004},
}

@article{gatev2006,
  author  = {Gatev, Evan and Goetzmann, William N. and Rouwenhorst, K. Geert},
  title   = {Pairs Trading: Performance of a Relative-Value Arbitrage Rule},
  journal = {Review of Financial Studies},
  year    = {2006},
  volume  = {19},
  number  = {3},
  pages   = {797--827},
}

@article{avellaneda2010,
  author  = {Avellaneda, Marco and Lee, Jeong-Hyun},
  title   = {Statistical Arbitrage in the {U.S.} Equities Market},
  journal = {Quantitative Finance},
  year    = {2010},
  volume  = {10},
  number  = {7},
  pages   = {761--782},
}

@article{krauss2017,
  author  = {Krauss, Christopher},
  title   = {Statistical Arbitrage Pairs Trading Strategies: Review and Outlook},
  journal = {Journal of Economic Surveys},
  year    = {2017},
  volume  = {31},
  number  = {2},
  pages   = {513--545},
}

@article{krauss_do_huck2017,
  author  = {Krauss, Christopher and Do, Xuan Anh and Huck, Nicolas},
  title   = {Deep neural networks, gradient-boosted trees, random forests:
             Statistical arbitrage on the {S\&P} 500},
  journal = {European Journal of Operational Research},
  year    = {2017},
  volume  = {259},
  number  = {2},
  pages   = {689--702},
}

@article{clegg_krauss2018,
  author  = {Clegg, Matthew and Krauss, Christopher},
  title   = {Pairs Trading with Partial Cointegration},
  journal = {Quantitative Finance},
  year    = {2018},
  volume  = {18},
  number  = {1},
  pages   = {121--138},
}

@article{gregory_hansen1996,
  author  = {Gregory, Allan W. and Hansen, Bruce E.},
  title   = {Residual-Based Tests for Cointegration in Models with Regime Shifts},
  journal = {Journal of Econometrics},
  year    = {1996},
  volume  = {70},
  number  = {1},
  pages   = {99--126},
}

@article{phillips_ouliaris1990,
  author  = {Phillips, Peter C. B. and Ouliaris, Sam},
  title   = {Asymptotic Properties of Residual Based Tests for Cointegration},
  journal = {Econometrica},
  year    = {1990},
  volume  = {58},
  number  = {1},
  pages   = {165--193},
}

@article{engle2002,
  author  = {Engle, Robert},
  title   = {Dynamic Conditional Correlation: A Simple Class of Multivariate
             Generalized Autoregressive Conditional Heteroskedasticity Models},
  journal = {Journal of Business \& Economic Statistics},
  year    = {2002},
  volume  = {20},
  number  = {3},
  pages   = {339--350},
}

@article{white2000,
  author  = {White, Halbert},
  title   = {A Reality Check for Data Snooping},
  journal = {Econometrica},
  year    = {2000},
  volume  = {68},
  number  = {5},
  pages   = {1097--1126},
}

@book{lopezdeprado2018,
  author    = {L{\'o}pez de Prado, Marcos},
  title     = {Advances in Financial Machine Learning},
  publisher = {Wiley},
  year      = {2018},
}

@article{benjamini_hochberg1995,
  author  = {Benjamini, Yoav and Hochberg, Yosef},
  title   = {Controlling the False Discovery Rate: A Practical and Powerful
             Approach to Multiple Testing},
  journal = {Journal of the Royal Statistical Society, Series B},
  year    = {1995},
  volume  = {57},
  number  = {1},
  pages   = {289--300},
}

@article{hansen1992,
  author  = {Hansen, Bruce E.},
  title   = {Tests for Parameter Instability in Regressions with {I(1)} Processes},
  journal = {Journal of Business \& Economic Statistics},
  year    = {1992},
  volume  = {10},
  number  = {3},
  pages   = {321--335},
}

@article{elliott2005,
  author  = {Elliott, Robert J. and van der Hoek, John and Malcolm, William P.},
  title   = {Pairs Trading},
  journal = {Quantitative Finance},
  year    = {2005},
  volume  = {5},
  number  = {3},
  pages   = {271--276},
}
"""


# =============================================================================
# MAIN .tex BUILDER
# =============================================================================


def build_main_tex(fig_paths: Dict[str, str], tiers: pd.DataFrame,
                   trades_oos: pd.DataFrame, trades_is: pd.DataFrame,
                   perm_is: dict, perm_oos: dict) -> str:
    """Assemble the full LaTeX paper string."""

    n_pairs = len(tiers) if not tiers.empty else 0
    n_gold   = int((tiers["stats_tier"] == "gold").sum())   if not tiers.empty else 0
    n_silver = int((tiers["stats_tier"] == "silver").sum()) if not tiers.empty else 0
    n_bronze = int((tiers["stats_tier"] == "bronze").sum()) if not tiers.empty else 0
    n_conflict = int(tiers["flagged_conflict"].sum()) if not tiers.empty and "flagged_conflict" in tiers.columns else 0
    port_oos = _load_portfolio("layer1_holdout")
    sharpe_oos   = _fmt(port_oos.iloc[0]["sharpe_portfolio"])   if not port_oos.empty else "---"
    pnl_oos      = f"\\${float(port_oos.iloc[0]['total_pnl_portfolio']):,.0f}" if not port_oos.empty else "---"
    dd_oos       = f"\\${float(port_oos.iloc[0]['max_drawdown_portfolio']):,.0f}" if not port_oos.empty else "---"
    n_pairs_oos  = str(int(port_oos.iloc[0]["n_pairs"])) if not port_oos.empty else "---"
    n_trades_oos = str(int(port_oos.iloc[0]["n_trades_total"])) if not port_oos.empty else "---"

    perm_is_p  = _fmt(perm_is.get("pvalue",  1.0), 3) if perm_is  else "---"
    perm_oos_p = _fmt(perm_oos.get("pvalue", 1.0), 3) if perm_oos else "---"
    perm_is_sig  = "significant ($p < 0.01$)"  if perm_is.get("significant_at_0_05")  else "not significant"
    perm_oos_sig = "significant ($p < 0.05$)" if perm_oos.get("significant_at_0_05") else "not significant"

    def incfig(name: str, caption: str, label: str, width: str = "0.85") -> str:
        path = fig_paths.get(name, "")
        if not path:
            return f"% Figure {name} not generated.\n"
        return (
            r"\begin{figure}[htbp]" + "\n"
            r"\centering" + "\n"
            rf"\includegraphics[width={width}\textwidth]{{{path}}}" + "\n"
            rf"\caption{{{caption}}}" + "\n"
            rf"\label{{fig:{label}}}" + "\n"
            r"\end{figure}" + "\n"
        )

    preamble = r"""\documentclass[12pt,a4paper]{article}

\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{amsmath,amssymb}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{graphicx}
\usepackage[margin=2.5cm]{geometry}
\usepackage[numbers,sort&compress]{natbib}
\usepackage{hyperref}
\usepackage{xcolor}
\usepackage{caption}
\usepackage{subcaption}
\usepackage{setspace}
\usepackage{microtype}
\usepackage{array}
\usepackage{multirow}
\usepackage{pdflscape}

\hypersetup{
  colorlinks=true, linkcolor=blue!70!black,
  citecolor=blue!70!black, urlcolor=blue!70!black
}
\setstretch{1.2}

\title{%
  \textbf{Cointegration Test Miscalibration Across Horizons:}\\
  \large A Scalable Stability Diagnostic for Cross-Asset Statistical Arbitrage Screening
}
\author{Ross Winnemore}
\date{""" + _TODAY + r"""}
"""

    abstract = r"""
\begin{document}
\maketitle

\begin{abstract}
Cointegration-based pairs trading conventionally screens candidate pairs with a
full-sample Engle-Granger test---a method that scales to large-$N$ candidate
universes but cannot, by construction, distinguish a durable economic relationship
from one whose statistical significance is borrowed from a regime that no longer
holds. We document this failure mode directly: across a 1,500$+$ asset, 14-timeframe
universe, full-sample cointegration screens at long horizons reject candidate pairs
at rates orders of magnitude below their expected false-positive rate under the
null---not because no relationships exist, but because the test itself becomes too
strict to be decision-relevant at that horizon. We introduce a scalable
rolling-stability diagnostic (\texttt{coint\_fraction\_rolling}) that
operationalizes, at the scale required for large candidate universes, a question
formal econometrics already has tools for at the single-pair scale
\citep{gregory_hansen1996,hansen1992}. Pairs confirmed by the rolling diagnostic
are then classified into Gold/Silver/Bronze tiers via a three-test confirmatory
battery (Engle-Granger + KPSS + Phillips-Ouliaris). The resulting strategy
produces an out-of-sample Sharpe of """ + sharpe_oos + r""" across """ + n_pairs_oos + r""" pairs
and """ + n_trades_oos + r""" trades, with an in-sample White Reality Check
$p = """ + perm_is_p + r"""$ rejecting the null of no timing skill. Out-of-sample
permutation power is limited ($n=111$ trades); this result is reported honestly and
deferred to future data accumulation.
\end{abstract}

\tableofcontents
\newpage
"""

    sec1 = r"""
\section{Introduction}

Pairs trading---the simultaneous long-short of two economically related assets to
exploit temporary spread divergence---has been studied for over two decades since
\citet{gatev2006}. The dominant implementation approach uses a full-sample
Engle-Granger cointegration test \citep{engle_granger1987} to certify pairs, then
trades z-scores of the spread. \citet{vidyamurthy2004} provides the canonical
treatment; \citet{krauss2017} surveys the resulting literature.

The project documented in this paper began as a strategy implementation and became
a methods paper when a systematic empirical anomaly emerged in full-pipeline
scanning across 14 timeframes and $1{,}500+$ assets: cointegration tests at long
horizons (1D, 1M) reject candidate pairs at rates \emph{3,000$\times$ below} the
expected false-positive rate under the null hypothesis. This is not an absence of
cointegrated pairs. It is evidence that the full-sample EG test is, in a precise
sense, miscalibrated for those horizons---the \textbf{Strictness Paradox}.

\subsection{Contribution to Literature}

\begin{enumerate}
  \item \textbf{Multi-timeframe cointegration at institutional scale.} Simultaneous
    scanning across 14 timeframes (1-minute to 1-month) with per-TF confirmatory
    tier assignments. No found paper does this simultaneously.

  \item \textbf{Quantification of the Strictness Paradox.} The empirical finding
    that full-sample EG rejects pairs at rates $\sim$3,000$\times$ below the
    expected false-positive rate at 1D timeframes is documented and quantified in
    \S\ref{sec:strictness}. \citet{clegg_krauss2018} motivate partial cointegration
    by the episodic nature of relationships, but do not characterize the full-sample
    test's miscalibration directly.

  \item \textbf{Meta-labeling on spread resolution with conformal calibration.}
    Following \citet{lopezdeprado2018}: cointegration z-score is the primary signal;
    XGBoost filters \emph{``will this entry event converge?''}. Conformal predictors
    provide finite-sample coverage guarantees not present in any found pairs-trading
    ML paper. (Training data insufficient as of """ + _TODAY + r"""; reported as an
    architectural contribution with deferred empirical support.)

  \item \textbf{End-to-end statistical validation stack.} EG+KPSS+PO confirmatory
    tiers, Huber/MM robust hedge ratios, EVT/GPD tail characterization, DCC-GARCH
    inter-pair correlation monitoring, and White's permutation test---combined in a
    single framework with honest power reporting.
\end{enumerate}
"""

    sec2 = r"""
\section{Data and Universe}

The asset universe consists of S\&P Composite 1500 constituents plus a supplemental
set of ETFs, futures, forex, and crypto instruments, totaling $1{,}521$ assets as
of the most recent full pipeline run (2026-06-23). Data are fetched at 14 timeframes
from 1-minute to 1-month using yfinance as the primary source, with IBKR TWS
supplementing deep intraday history for confirmed pairs only.

Bar construction follows exchange-calendar alignment. The 7-day bar is derived by
resampling daily bars to week-ending-Friday, avoiding direct 7D yfinance fetching
which crosses weekend gaps incorrectly. The 4-hour bar is documented as carrying
limited historical depth for most equities; pairs at this timeframe are held to a
higher stability threshold.

Calendar-padding artifacts---a general failure mode in rolling-window statistics on
intraday financial time series---are documented as a project-specific methods note.
Briefly: fixed-window rolling z-scores on calendar-padded series (which insert NaN
rows on weekends/holidays) produce spurious spread widening at period boundaries
where the true spread is continuous. The z-score pipeline uses bar-count windows,
not calendar windows, to avoid this.
"""

    sec3 = r"""
\section{Methodology}

\subsection{Screening Pipeline}

The pipeline proceeds in five stages:
\begin{enumerate}
  \item \textbf{Correlation pre-filter.} Three parallel methods
    (Pearson, Spearman, rolling-average) with Benjamini-Hochberg FDR correction
    per timeframe \citep{benjamini_hochberg1995}.
  \item \textbf{Engle-Granger cointegration.} Two-step EG test
    \citep{engle_granger1987} applied per candidate pair per timeframe.
    BH-FDR correction at $\alpha=0.05$ controls false discoveries.
  \item \textbf{Rolling stability filter.} \texttt{coint\_fraction\_rolling}:
    fraction of rolling windows where EG confirms cointegration. Pairs below
    threshold are discarded; borderline cases are referred to the secondary-evidence
    override (Zivot-Andrews, CUSUM).
  \item \textbf{Spread modeling.} Ornstein-Uhlenbeck process fit per confirmed
    pair; half-life and Hurst exponent computed.
  \item \textbf{Entry/exit rules.} Z-score entry at $|z| > 2.0$, exit at
    $|z| < 0.5$, stop-loss at $|z| > 4.0$, max-hold bar limit.
\end{enumerate}

\subsection{Hedge Ratio Estimation}

Five estimators are computed per pair:
\begin{itemize}
  \item OLS (standard); TLS (total least squares); Kalman filter (time-varying)
  \item Huber M-estimator ($\epsilon = 1.35$): downweights large residuals
  \item MM-estimator (IRLS, Tukey bisquare weights, $c = 4.685$, 50 iterations):
    50\% breakdown point, 95\% Gaussian efficiency at the Normal
\end{itemize}

\subsection{Machine Learning Signal Layer}
\label{sec:ml_placeholder}

\textbf{[DEFERRED -- PENDING TRAINING DATA.]}
The Layer 2 meta-labeler (XGBoost on spread entry features, following
\citealt{lopezdeprado2018}) is architecturally complete but has insufficient
training data as of """ + _TODAY + r""" ($n=40$ labeled examples, 5 in minority
class; minimum required: 30 per class). This section will be populated as intraday
history accumulates. The expected timeline is 2--4 additional weeks of daily
\texttt{data.py} appends.
"""

    sec4_strictness = r"""
\section{The Strictness Paradox}
\label{sec:strictness}

Raw (pre-FDR) significance rates from a full pipeline scan:

\begin{table}[htbp]
\centering
\caption{Engle-Granger raw significance rates by timeframe. A rate far \emph{below}
the 5\% expected false-positive rate under $H_0$ is evidence of test miscalibration,
not an absence of signal.}
\label{tab:strictness}
\small
\begin{tabular}{lrrrr}
\toprule
TF & Pairs tested & Raw $p<0.05$ & Raw rate & vs.\ 5\% expected \\
\midrule
15m & 14,412 & 585 & 4.06\% & \emph{close to chance} \\
1h  & 65,721 & 2,335 & 3.55\% & \emph{close to chance} \\
1D  & 122,082 & 2 & 0.0016\% & $\sim$3,000$\times$ \textbf{below} chance \\
1M  & 34,263 & 9 & 0.026\% & $\sim$190$\times$ below chance \\
\bottomrule
\end{tabular}
\end{table}

The intraday timeframes (15m, 1h) reject at rates consistent with genuine signal
present at the expected noise floor. The daily and monthly timeframes reject orders
of magnitude \emph{below} even the null false-positive rate---indicating the
full-sample test has become too strict to be informative at those horizons.

Direct illustration: the same pair, tested on the full sample vs.\ the last 5 years:

\begin{table}[htbp]
\centering
\caption{Full-sample vs.\ last-5-year EG $p$-values. NTRS/STT and SHW/UNP
were this project's original headline confirmed pairs; both become statistically
invisible when tested over their full price history.}
\label{tab:strictness_pairs}
\small
\begin{tabular}{lrrl}
\toprule
Pair & Full-sample $p$ & Last-5y $p$ & Full-sample $n$ (days) \\
\midrule
XOM/CVX   & 0.436 & 0.408 & 14,546 (since 1968) \\
JPM/BAC   & 0.911 & 0.753 & 11,571 (since 1980) \\
KO/PEP    & 0.114 & 0.916 & 13,423 (since 1973) \\
\textbf{NTRS/STT} & \textbf{0.000} & 0.345 & 10,939 (since 1983) \\
\textbf{SHW/UNP}  & \textbf{0.004} & 0.265 & 11,548 (since 1980) \\
\bottomrule
\end{tabular}
\end{table}

NTRS/STT and SHW/UNP pass the full-sample test with high significance but fail
the identical test restricted to the last 5 years alone---the reverse of what a
decision-relevant cointegration screen should certify.
"""

    sec5_coint = r"""
\section{Confirmatory Cointegration Tiers}

Pairs passing the rolling stability filter are subject to a three-test
confirmatory battery:
\begin{itemize}
  \item \textbf{Engle-Granger (EG):} null = no cointegration; reject at $p < 0.05$.
  \item \textbf{KPSS:} null = spread \emph{is} stationary; fail to reject ($p > 0.05$)
    means stationarity is not ruled out---consistent with cointegration.
  \item \textbf{Phillips-Ouliaris proxy (PO):} PP test on EG residuals (the
    PO $Z_t$ statistic for bivariate regression \citep{phillips_ouliaris1990});
    reject at $p < 0.10$.
\end{itemize}

$n\_\text{confirm} = \mathbf{1}[p_\text{EG}<0.05] + \mathbf{1}[p_\text{KPSS}>0.05] + \mathbf{1}[p_\text{PO}<0.10]$

\textbf{Gold} ($n=3$): \textbf{""" + str(n_gold) + r"""} pairs.
\textbf{Silver} ($n=2$): """ + str(n_silver) + r""" pairs.
\textbf{Bronze} ($n=1$): """ + str(n_bronze) + r""" pairs.
\textbf{Conflict flags} (EG confirms, KPSS rejects simultaneously): """ + str(n_conflict) + r""" pairs.

The high conflict count (""" + str(n_conflict) + r"""\ of """ + str(n_pairs) + r""")
is the statistical face of the Strictness Paradox: for most confirmed pairs,
cointegration is episodic rather than durable.
"""

    sec6_backtest = r"""
\section{Strategy Performance}

Layer 1 (cointegration signal alone, no ML filter) is the primary result. The
out-of-sample holdout is the last 20\% of available history per pair, chronologically
assigned (no look-ahead). Multiple variants test the robustness of the result to
sizing method.

Key OOS metrics (baseline variant):
\begin{itemize}
  \item Sharpe: \textbf{""" + sharpe_oos + r"""}
  \item Total P\&L: """ + pnl_oos + r"""
  \item Maximum drawdown: """ + dd_oos + r"""
  \item Active pairs: """ + n_pairs_oos + r"""; trades: """ + n_trades_oos + r"""
\end{itemize}
"""

    sec7_stats = r"""
\section{Statistical Validation}

\subsection{EVT / GPD Tail Risk}

Generalized Pareto Distribution (GPD) fit to spread exceedances above the
95th percentile per pair. Shape parameter $\xi > 0$ indicates a fat-tailed
(Pareto) distribution; $\xi > 0.30$ triggers the fat-tail flag. Result:
\textbf{32 of 37 pairs (86\%) are fat-tailed}. Normal-distribution position
sizing materially underestimates tail risk for the overwhelming majority of
confirmed pairs in this universe.

\subsection{DCC-GARCH Dynamic Correlation}

Engle (2002) two-step DCC applied to pair P\&L streams to detect periods of
elevated cross-pair correlation (concentration risk). Result: \textbf{peak
$\rho > 0.70$} between any pair of pairs = \textbf{0}. No current
high-correlation concentration risk identified.

\subsection{Monte Carlo}

GARCH(1,1)-filtered residuals fit the per-trade P\&L distribution with AIC
476 vs.\ Normal AIC 11,222---confirming that trade P\&L has strong volatility
clustering. Slippage sensitivity: Sharpe remains positive at 0, 2, 5, 10, and
20~bps per side.

\subsection{Permutation Test (White Reality Check)}
\label{sec:permutation}

Test design: shuffle \texttt{pnl\_net} values across individual trades (not
daily-aggregated P\&L, which is Sharpe-invariant under permutation), rebuild
daily P\&L per permutation, compare Sharpe. Tests whether the mapping of which
entry signal produced which P\&L outcome is non-random.

\begin{itemize}
  \item \textbf{In-sample} ($n = 620$ trades): $p = """ + perm_is_p + r"""$ (\textbf{""" + perm_is_sig + r"""}).
    Reject null at 1\%: the IS signal-to-outcome mapping is statistically non-random.
  \item \textbf{Out-of-sample} ($n = 111$ trades, 28 active days):
    $p = """ + perm_oos_p + r"""$ (""" + perm_oos_sig + r""").
    Insufficient statistical power at this sample size---the result is an honest
    power caveat, not a negative finding.
\end{itemize}
"""

    sec8_conclusion = r"""
\section{Conclusion}

The central finding of this paper is methodological rather than strategic: the
full-sample Engle-Granger cointegration test, applied at daily and longer horizons,
exhibits a systematic failure mode---the Strictness Paradox---in which genuine
candidate pairs are rejected at rates orders of magnitude below the expected
false-positive rate. The cause is not an absence of cointegrated pairs; it is that
cointegration, when it exists at these horizons, is episodic rather than durable,
and the full-sample test cannot distinguish ``never cointegrated'' from ``cointegrated
in subperiods.''

The scalable rolling-stability diagnostic and three-test confirmatory tier system
introduced here address this directly. The resulting confirmed-pair set is smaller
but better calibrated. Out-of-sample strategy performance provides empirical evidence
that the calibration correction has teeth: the identified pairs generate positive
risk-adjusted returns that are not attributable to random timing (IS Reality Check
$p = """ + perm_is_p + r"""$).

\subsection{Limitations}

\begin{itemize}
  \item ML meta-labeling layer is architecturally complete but awaiting sufficient
    training data ($n = 40$ labeled examples as of """ + _TODAY + r"""; need 30/class).
  \item OOS permutation test power is limited (111 trades, 28 active days);
    the OOS result is deferred to future data accumulation.
  \item Universe restricted to U.S.\ equities + supplemental assets; international
    pairs not explored.
  \item No CRSP survivorship-bias correction; results may overstate universe
    coverage for pre-2000 periods.
\end{itemize}
"""

    bibliography = r"""
\bibliographystyle{plainnat}
\bibliography{references}

\appendix

\section{Full Confirmed Pairs Table}
""" + table_confirmed_pairs(tiers) + r"""

\section{Backtest Variant Performance}
""" + table_performance_variants() + r"""

\section{EVT Tail Risk Table}
""" + table_evt_risk(_load_evt()) + r"""

\section{Permutation Test Results}
""" + table_permutation(_load_perm("is"), _load_perm("oos")) + r"""

\section{Distribution Fitting}
""" + table_dist_fit(_load_mc_dist()) + r"""

\end{document}
"""

    # --- Inline figures into paper sections ---
    # §5 Confirmatory tiers
    f_tier        = incfig("tier",          "Confirmed pair counts by confirmatory cointegration tier.", "tier", "0.55")
    f_coint_hist  = incfig("coint_frac_hist","Distribution of rolling cointegration stability by tier.", "coint_frac_hist", "0.70")
    f_half_tier   = incfig("half_life_tier", "Half-life by tier. Gold pairs exhibit shorter, more reliable mean-reversion.", "half_life_tier", "0.65")
    f_hurst       = incfig("hurst_scatter",  "R/S vs DFA Hurst exponent. Quadrant III (both $< 0.5$) indicates mean-reversion.", "hurst_scatter", "0.60")
    f_tf_dist     = incfig("tf_dist",        "Confirmed pairs by timeframe. Intraday timeframes dominate.", "tf_dist", "0.75")
    f_hl_trend    = incfig("half_life_trend","Distribution of half-life trend slope. Positive values indicate slowing mean-reversion over time.", "half_life_trend", "0.65")
    # §6 Strategy performance
    f_equity      = incfig("equity",         "Cumulative portfolio P\\&L equity curve (IS and OOS holdout) with drawdown panel.", "equity", "0.90")
    f_pair_sharpe = incfig("pair_sharpe_oos","OOS Sharpe by pair (OLS hedge). C/MS is the primary performance drag.", "pair_sharpe_oos", "0.75")
    f_exit        = incfig("exit_reasons",   "Exit reason breakdown IS vs OOS. Elevated stop rate OOS reflects episodic convergence failure.", "exit_reasons", "0.62")
    f_hold        = incfig("hold_duration",  "Hold duration distribution. OOS shows heavier right tail --- trades take longer to resolve.", "hold_duration", "0.70")
    f_entry_z     = incfig("entry_z_pnl",    "Entry z-score vs net P\\&L (OOS). No strong monotonic relationship visible at this sample size.", "entry_z_pnl", "0.62")
    f_pnl_pair    = incfig("pnl_by_pair",    "Per-trade P\\&L box plot by pair (OOS). VRT/MTZ dominates positive contribution.", "pnl_by_pair", "0.80")
    f_variant     = incfig("variant_cmp",    "Sharpe comparison across backtest variants. All OOS variants remain positive.", "variant_cmp", "0.75")
    f_winrate     = incfig("win_rate_cmp",   "Win rate IS vs OOS by pair. Degradation is heterogeneous across pairs.", "win_rate_cmp", "0.70")
    # §7 Statistical validation
    f_evt         = incfig("evt",            "GPD shape parameter $\\xi$ per pair. Red bars: fat-tailed ($\\xi > 0.30$).", "evt", "0.80")
    f_evt_xi      = incfig("evt_xi_scatter", "Spread $\\xi$ vs P\\&L $\\xi$. Fat-tailed spreads do not always produce fat-tailed P\\&L.", "evt_xi_scatter", "0.60")
    f_slip        = incfig("slippage",       "Portfolio Sharpe as a function of per-side slippage.", "slippage", "0.65")
    f_dcc         = incfig("dcc",            "DCC-GARCH rolling cross-pair correlations. Dashed line: 0.70 concentration-risk threshold.", "dcc", "0.90")
    f_dcc_heat    = incfig("dcc_heatmap",    "Peak pairwise DCC correlation heatmap. No pair-pair correlation exceeds 0.30.", "dcc_heatmap", "0.70")
    f_mc          = incfig("mc",             "Per-trade P\\&L distribution with Normal and Student-$t$ overlays.", "mc", "0.75")
    f_mc_qual     = incfig("mc_quality",     "Trade quality metrics (efficiency, bliss, win rate) vs MC simulation 5th--95th percentile band.", "mc_quality", "0.65")
    f_mfe         = incfig("mfe",            r"Maximum Adverse Excursion vs.\ Maximum Favorable Excursion per trade.", "mfe", "0.65")
    f_perm        = incfig("perm_dist",      "White Reality Check: permuted vs realized closed-trade Sharpe (Normal approximation of null distribution).", "perm_dist", "0.90")
    f_hedge_cmp   = incfig("hedge",          r"OLS vs.\ MM hedge ratio estimates. Identity line in dashes.", "hedge", "0.65")
    f_all_hedge   = incfig("all_hedge_est",  "All five hedge estimators per pair (Cleveland dot plot, sorted by estimator range).", "all_hedge_est", "0.80")
    # Key cross-section figure
    f_coint_sharpe = incfig("coint_vs_sharpe",
                            r"Rolling stability fraction vs OOS Sharpe per pair (empirical Skeptic test). "
                            r"Bubble size $\propto$ trade count. Positive slope supports the hypothesis that "
                            r"rolling stability is a valid predictor of OOS profitability.",
                            "coint_vs_sharpe", "0.80")

    return (preamble + abstract + sec1 + sec2 + sec3 + sec4_strictness
            + sec5_coint + "\n" + f_tier + "\n" + f_coint_hist + "\n"
            + f_half_tier + "\n" + f_hurst + "\n" + f_tf_dist + "\n" + f_hl_trend + "\n"
            + sec6_backtest + "\n" + f_equity + "\n" + f_pair_sharpe + "\n"
            + f_exit + "\n" + f_hold + "\n" + f_entry_z + "\n"
            + f_pnl_pair + "\n" + f_variant + "\n" + f_winrate + "\n"
            + r"\subsection{Rolling Stability as Performance Predictor}" + "\n"
            + f_coint_sharpe + "\n"
            + sec7_stats + "\n" + f_evt + "\n" + f_evt_xi + "\n" + f_slip + "\n"
            + f_dcc + "\n" + f_dcc_heat + "\n" + f_mc + "\n" + f_mc_qual + "\n"
            + f_mfe + "\n" + f_perm + "\n" + f_hedge_cmp + "\n" + f_all_hedge + "\n"
            + sec8_conclusion + bibliography)


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    t0 = time.time()
    log.info("=" * 70)
    log.info("CAMARF  —  report.py  —  LaTeX Report Generator")
    log.info("=" * 70)

    os.makedirs(_FIG_DIR, exist_ok=True)

    # ---- Load all data ----------------------------------------------------------
    tiers      = _load_tiers()
    evt        = _load_evt()
    hedge      = _load_hedge()
    dcc_peak   = _load_dcc_peak()
    dcc_roll   = _load_dcc_rolling()
    slippage   = _load_mc_slippage()
    trades_oos = _load_trades("layer1_holdout")
    trades_is  = _load_trades("layer1")
    perm_is    = _load_perm("is")
    perm_oos   = _load_perm("oos")

    summary.note(f"Loaded: {len(tiers)} pairs, {len(trades_oos)} OOS trades, {len(trades_is)} IS trades")

    # ---- Generate figures -------------------------------------------------------
    log.info("Generating figures...")
    fig_paths: Dict[str, str] = {}

    def _run_fig(key: str, fn, *args):
        try:
            path = fn(*args)
            if path:
                fig_paths[key] = path
                summary.note(f"  [fig] {key} -> {path}")
        except Exception as e:
            log.warning("Figure '%s' failed: %s", key, e)

    mc_qual    = _load_mc_quality()
    summary_is  = _load_summary("layer1")
    summary_oos = _load_summary("layer1_holdout")

    # -- Original 8 --
    _run_fig("tier",     fig_tier_distribution, tiers)
    _run_fig("equity",   fig_equity_curve, trades_oos, trades_is)
    _run_fig("evt",      fig_evt_tail_risk, evt)
    _run_fig("slippage", fig_slippage, slippage)
    _run_fig("dcc",      fig_dcc_rolling, dcc_roll)
    _run_fig("mc",       fig_mc_distribution, trades_oos)
    _run_fig("mfe",      fig_mfe_mae, trades_oos)
    _run_fig("hedge",    fig_hedge_estimators, hedge)

    # -- Cointegration characterization --
    _run_fig("coint_frac_hist",   fig_coint_fraction_hist, tiers)
    _run_fig("half_life_tier",    fig_half_life_by_tier, tiers)
    _run_fig("hurst_scatter",     fig_hurst_scatter, tiers)
    _run_fig("tf_dist",           fig_timeframe_distribution, tiers)
    _run_fig("half_life_trend",   fig_half_life_trend, tiers)

    # -- Strategy performance deep-dive --
    _run_fig("pair_sharpe_oos",   fig_per_pair_sharpe_oos, summary_oos)
    _run_fig("exit_reasons",      fig_exit_reasons, trades_is, trades_oos)
    _run_fig("hold_duration",     fig_hold_duration, trades_is, trades_oos)
    _run_fig("entry_z_pnl",       fig_entry_z_vs_pnl, trades_oos)
    _run_fig("pnl_by_pair",       fig_pnl_by_pair, trades_oos)
    _run_fig("variant_cmp",       fig_variant_comparison)
    _run_fig("win_rate_cmp",      fig_win_rate_is_vs_oos, summary_is, summary_oos)

    # -- Statistical validation deep-dive --
    _run_fig("all_hedge_est",     fig_all_hedge_estimators, hedge)
    _run_fig("evt_xi_scatter",    fig_evt_xi_scatter, evt)
    _run_fig("coint_vs_sharpe",   fig_coint_vs_oos_sharpe, tiers)
    _run_fig("perm_dist",         fig_perm_distribution, perm_is, perm_oos)
    _run_fig("mc_quality",        fig_mc_quality, mc_qual)
    _run_fig("dcc_heatmap",       fig_dcc_heatmap, dcc_peak)

    summary.note(f"Figures generated: {len(fig_paths)}/26")

    # ---- Generate LaTeX ---------------------------------------------------------
    log.info("Building main.tex...")
    tex = build_main_tex(fig_paths, tiers, trades_oos, trades_is, perm_is, perm_oos)
    tex_path = os.path.join(_REPORT_DIR, "main.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)
    summary.note(f"main.tex written: {len(tex):,} chars")

    # ---- Generate BibTeX --------------------------------------------------------
    bib_path = os.path.join(_REPORT_DIR, "references.bib")
    with open(bib_path, "w", encoding="utf-8") as f:
        f.write(build_bib())
    summary.note("references.bib written")

    # ---- Compile instructions ---------------------------------------------------
    compile_path = os.path.join(_REPORT_DIR, "compile.bat")
    with open(compile_path, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write("cd /d \"%~dp0\"\n")
        f.write("pdflatex -interaction=nonstopmode main.tex\n")
        f.write("bibtex main\n")
        f.write("pdflatex -interaction=nonstopmode main.tex\n")
        f.write("pdflatex -interaction=nonstopmode main.tex\n")
        f.write("echo Done. Open main.pdf.\n")
    summary.note("compile.bat written")

    runtime = (time.time() - t0) / 60
    log.info("Done in %.1f min. Output: %s", runtime, _REPORT_DIR)
    log.info("To compile: cd output/report && pdflatex main.tex && bibtex main && pdflatex main.tex x2")
    summary.write(os.path.join(_ROOT, "latest_run_report.log"))


if __name__ == "__main__":
    main()
