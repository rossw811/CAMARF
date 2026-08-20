"""
research/jkp_thread_m_driver.py -- Thread M's actual purpose: regress CAMARF's
real, realized Step 5 backtest-arm returns (output/research/step5_arm_results/
real_*_trades_capsim.parquet) against both Option A's long-short JKP factor
portfolios and Option B's raw pair-leg characteristic exposures, for every
arm (baseline/hybrid/purity/tiered) x split (is/oos) combination.

Reuses research/fama_french_risk_decomposition.py::build_daily_return_series
directly (same realized-trade -> daily-return reconstruction Thread F Part A
already built and verified) -- NOT reimplemented. Aggregates to MONTHLY here
(new, since JKP's factor panel and Option A's constructed factor returns are
both monthly, and run_regression's own daily-frequency assumption doesn't
apply without this adaptation).

HONESTY ABOUT DEGREES OF FREEDOM (real constraint found while building this,
not glossed over): CAMARF's real backtest history only spans ~2023-2026 for
the Purity arm (its longest), giving ~30-36 overlapping months against a
17-factor regression (18 parameters incl. intercept) -- thin enough that a
full 17-factor fit would have very few residual degrees of freedom and be
prone to overfitting-flavored, inflated-looking R² without real statistical
power (CLAUDE.md rule 7: never let a result look stronger than the evidence
supports). Reports BOTH a "core 6" regression (the original FF5+momentum-
equivalent factors, plenty of DOF at this sample size) as the PRIMARY,
trustworthy result, and the full 17-factor regression as a SECONDARY result
explicitly flagged when DOF is thin (n_months - n_params < 15, arbitrary but
disclosed threshold).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.fama_french_risk_decomposition import build_daily_return_series
from research.jkp_factor_portfolio_construction import _FACTOR_DEFS
from research.jkp_raw_characteristic_regression import (
    fetch_pairleg_characteristics, build_portfolio_characteristic_exposure,
    run_raw_characteristic_regression,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WRDS_CACHE_DIR = os.path.join(_ROOT, "output", "cache", "wrds")
_STEP5_DIR = os.path.join(_ROOT, "output", "research", "step5_arm_results")
_FACTORS_PATH = os.path.join(_ROOT, "output", "research", "jkp_factor_portfolios_monthly.parquet")
_FF5_DAILY_PATH = os.path.join(_WRDS_CACHE_DIR, "ff_factors_5_daily.parquet")
_OUT_PATH = os.path.join(_ROOT, "output", "research", "jkp_thread_m_regression_results.parquet")

_CORE6_FACTORS = ["value", "size", "momentum", "profitability", "investment", "betting_against_beta"]
_ALL_FACTORS = sorted(_FACTOR_DEFS.keys())

_ARMS = ["baseline", "hybrid", "purity", "tiered"]
_SPLITS = ["is", "oos"]
_STARTING_CAPITAL = 100_000
_MIN_DOF_TRUSTWORTHY = 15  # residual degrees of freedom below this -> flag, don't hide
_MAX_ZERO_MONTH_FRAC = 0.30  # real finding, 2026-08-14: baseline/tiered arms' realized monthly
# return series were found to be 81% EXACT ZEROS (17/21 months, only ~16-24 total trades across
# each arm's whole IS+OOS history) -- a regression against a return series this sparse produces
# spuriously tight, extreme-looking t-statistics (observed: |t| up to 67) that reflect the
# regression trivially fitting "mostly zero, occasionally a big move," not a genuine risk-factor
# relationship. Flagged separately from the DOF guard above -- a result can have ample DOF and
# STILL be untrustworthy if the underlying return series itself is this sparse.


def monthly_returns_from_trades(trades_path: str) -> pd.Series:
    trades_df = pd.read_parquet(trades_path)
    if trades_df.empty:
        return pd.Series(dtype=float)
    daily_returns = build_daily_return_series(trades_df, _STARTING_CAPITAL)
    if daily_returns.empty:
        return pd.Series(dtype=float)
    monthly = (1.0 + daily_returns).resample("ME").prod() - 1.0
    return monthly


def monthly_rf_series() -> pd.Series:
    ff = pd.read_parquet(_FF5_DAILY_PATH)
    ff["date"] = pd.to_datetime(ff["date"])
    daily_rf = ff.set_index("date")["rf"]
    return (1.0 + daily_rf).resample("ME").prod() - 1.0


def run_monthly_regression(portfolio_returns: pd.Series, factors_df: pd.DataFrame,
                            factor_cols: list, rf: pd.Series) -> dict:
    """Same OLS mechanics as fama_french_risk_decomposition.run_regression, but
    MONTHLY frequency (annualized *12, not *252) and taking rf as a separate
    series (JKP's own factor panel has no 'rf' column, unlike the FF daily
    cache run_regression was built against)."""
    joined = pd.DataFrame({"portfolio_return": portfolio_returns}).join(
        factors_df[factor_cols], how="inner"
    ).join(rf.rename("rf"), how="inner").dropna()
    n_params = len(factor_cols) + 1
    if len(joined) < n_params + 3:
        return {"ok": False, "reason": "insufficient_overlap", "n_months": len(joined),
                "n_params": n_params}

    zero_month_frac = float((joined["portfolio_return"].abs() < 1e-9).mean())
    sparse_trading = zero_month_frac > _MAX_ZERO_MONTH_FRAC

    y = (joined["portfolio_return"] - joined["rf"]).to_numpy()
    x_cols = [joined[c].to_numpy() for c in factor_cols]
    x = np.column_stack([np.ones(len(joined))] + x_cols)
    beta, _, _, _ = np.linalg.lstsq(x, y, rcond=None)

    y_hat = x @ beta
    resid = y - y_hat
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    n, k = x.shape
    dof = max(n - k, 1)
    sigma2 = ss_res / dof
    xtx_inv = np.linalg.pinv(x.T @ x)
    se = np.sqrt(np.diag(sigma2 * xtx_inv))
    alpha_monthly = float(beta[0])
    alpha_se = float(se[0]) if se[0] > 0 else np.nan

    return {
        "ok": True,
        "n_months": n,
        "n_params": k,
        "dof": dof,
        "dof_trustworthy": dof >= _MIN_DOF_TRUSTWORTHY,
        "zero_month_frac": zero_month_frac,
        "sparse_trading": sparse_trading,
        "trustworthy": (dof >= _MIN_DOF_TRUSTWORTHY) and not sparse_trading,
        "alpha_monthly": alpha_monthly,
        "alpha_annualized": alpha_monthly * 12,
        "alpha_tstat": alpha_monthly / alpha_se if np.isfinite(alpha_se) and alpha_se > 0 else np.nan,
        "loadings": {c: float(beta[i + 1]) for i, c in enumerate(factor_cols)},
        "loading_tstats": {
            c: float(beta[i + 1] / se[i + 1]) if se[i + 1] > 0 else np.nan
            for i, c in enumerate(factor_cols)
        },
        "r_squared": r_squared,
    }


def _option_b_results(db) -> dict:
    """Fetches raw pair-leg characteristics for every distinct pair traded
    across all arms/splits (one live WRDS query, cheap -- restricted to just
    these permnos, not the full market panel), then builds a leg_permnos map
    keyed by (symbol_a, symbol_b). Returns {(arm, split): exposure_df} pieces
    used by main() below."""
    from data_wrds import resolve_permnos_bulk

    all_pairs = set()
    trades_by_arm_split = {}
    for arm in _ARMS:
        for split in _SPLITS:
            trades_path = os.path.join(_STEP5_DIR, f"real_{arm}_{split}_trades_capsim.parquet")
            if not os.path.exists(trades_path):
                continue
            trades_df = pd.read_parquet(trades_path)
            trades_by_arm_split[(arm, split)] = trades_df
            for _, row in trades_df[["symbol_a", "symbol_b"]].drop_duplicates().iterrows():
                all_pairs.add((row["symbol_a"], row["symbol_b"]))

    all_symbols = sorted({s for pair in all_pairs for s in pair})
    print(f"\nOption B: resolving permnos for {len(all_symbols)} distinct symbols across "
          f"{len(all_pairs)} distinct pairs...")
    symbol_to_permno = resolve_permnos_bulk(db, all_symbols)
    leg_permnos = {
        pair: (symbol_to_permno[pair[0]], symbol_to_permno[pair[1]])
        for pair in all_pairs
        if pair[0] in symbol_to_permno and pair[1] in symbol_to_permno
    }
    n_unresolved_pairs = len(all_pairs) - len(leg_permnos)
    print(f"Option B: {len(leg_permnos)}/{len(all_pairs)} pairs resolved to permnos "
          f"({n_unresolved_pairs} dropped -- symbol not found in CRSP, e.g. an ETF or a delisted "
          f"name outside contrib_global_factor's coverage)")

    all_permnos = sorted({p for pair in leg_permnos.values() for p in pair})
    panel = fetch_pairleg_characteristics(db, all_permnos)
    print(f"Option B: fetched {len(panel)} characteristic rows for {len(all_permnos)} permnos")

    return trades_by_arm_split, leg_permnos, panel


def main():
    factors_df = pd.read_parquet(_FACTORS_PATH)
    rf = monthly_rf_series()

    from data_wrds import _connect
    db = _connect()
    trades_by_arm_split, leg_permnos, panel = _option_b_results(db)
    db.close()

    results = []
    for arm in _ARMS:
        for split in _SPLITS:
            trades_path = os.path.join(_STEP5_DIR, f"real_{arm}_{split}_trades_capsim.parquet")
            if not os.path.exists(trades_path):
                print(f"{arm}/{split}: no trades file, skipping")
                continue
            monthly_ret = monthly_returns_from_trades(trades_path)
            if monthly_ret.empty:
                print(f"{arm}/{split}: no realized trades, skipping")
                continue

            core6 = run_monthly_regression(monthly_ret, factors_df, _CORE6_FACTORS, rf)
            full17 = run_monthly_regression(monthly_ret, factors_df, _ALL_FACTORS, rf)

            zero_month_frac = float((monthly_ret.abs() < 1e-9).mean())
            sparse_trading = zero_month_frac > _MAX_ZERO_MONTH_FRAC
            trades_df = trades_by_arm_split.get((arm, split))
            arm_pairs = {
                (row["symbol_a"], row["symbol_b"]): leg_permnos[(row["symbol_a"], row["symbol_b"])]
                for _, row in trades_df[["symbol_a", "symbol_b"]].drop_duplicates().iterrows()
                if (row["symbol_a"], row["symbol_b"]) in leg_permnos
            }
            optionb_res = {"ok": False, "reason": "no_resolvable_pairs"}
            if arm_pairs:
                exposure_df = build_portfolio_characteristic_exposure(panel, arm_pairs)
                if not exposure_df.empty:
                    optionb_res = run_raw_characteristic_regression(monthly_ret, exposure_df)
                    if "error" not in optionb_res:
                        optionb_res["ok"] = True
                        optionb_res["sparse_trading"] = sparse_trading
                        optionb_res["zero_month_frac"] = zero_month_frac
                        optionb_res["trustworthy"] = not sparse_trading
                    else:
                        optionb_res = {"ok": False, "reason": optionb_res["error"]}

            print(f"\n=== {arm}/{split} (n_months_realized={len(monthly_ret)}) ===")
            if optionb_res.get("ok"):
                flag = "  ** SPARSE TRADING -- NOT TRUSTWORTHY **" if optionb_res["sparse_trading"] else ""
                print(f"  [option_b] n_obs={optionb_res['n_obs']}{flag} "
                      f"alpha_ann={optionb_res['alpha_annualized']:.4f} "
                      f"t={optionb_res['alpha_tstat']:.2f} R2={optionb_res['r_squared']:.3f}")
                results.append({
                    "arm": arm, "split": split, "regression": "option_b",
                    "n_months": optionb_res["n_obs"], "dof": None, "dof_trustworthy": None,
                    "zero_month_frac": optionb_res["zero_month_frac"],
                    "sparse_trading": optionb_res["sparse_trading"],
                    "trustworthy": optionb_res["trustworthy"],
                    "alpha_annualized": optionb_res["alpha_annualized"],
                    "alpha_tstat": optionb_res["alpha_tstat"], "r_squared": optionb_res["r_squared"],
                    "loadings": str(optionb_res["loadings"]),
                })
            else:
                print(f"  [option_b] skipped: {optionb_res.get('reason')}")

            for label, res in (("core6", core6), ("full17", full17)):
                if not res["ok"]:
                    print(f"  [{label}] insufficient overlap: n_months={res['n_months']}, "
                          f"needs >= {res['n_params'] + 3}")
                    continue
                flags = []
                if not res["dof_trustworthy"]:
                    flags.append("LOW DOF")
                if res["sparse_trading"]:
                    flags.append(f"SPARSE TRADING ({res['zero_month_frac']:.0%} zero months)")
                trust_flag = f"  ** {', '.join(flags)} -- NOT TRUSTWORTHY **" if flags else ""
                print(f"  [{label}] n_months={res['n_months']} dof={res['dof']}{trust_flag} "
                      f"alpha_ann={res['alpha_annualized']:.4f} t={res['alpha_tstat']:.2f} "
                      f"R2={res['r_squared']:.3f}")
                results.append({
                    "arm": arm, "split": split, "regression": label,
                    "n_months": res["n_months"], "dof": res["dof"],
                    "dof_trustworthy": res["dof_trustworthy"],
                    "zero_month_frac": res["zero_month_frac"],
                    "sparse_trading": res["sparse_trading"],
                    "trustworthy": res["trustworthy"],
                    "alpha_annualized": res["alpha_annualized"],
                    "alpha_tstat": res["alpha_tstat"], "r_squared": res["r_squared"],
                    "loadings": str(res["loadings"]),
                })

    if results:
        out_df = pd.DataFrame(results)
        out_df.to_parquet(_OUT_PATH, index=False)
        print(f"\nSaved {len(out_df)} regression results -> {_OUT_PATH}")
    else:
        print("\nNo regressions produced (no arms had both realized trades and factor overlap).")


if __name__ == "__main__":
    main()
