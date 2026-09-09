"""
debug/_verify_pit_wfa_wrds_daily.py -- synthetic ground-truth verification
for research/pit_wfa_wrds_daily.py, BEFORE trusting it against real full-
universe WRDS daily data. Focuses on what's actually NEW in this script
(the memory-bounded correlation wiring via build_returns_matrix +
chunked_pearson_candidate_pairs, replacing pit_wfa.py's dense
UniverseFilter.run() call) -- the downstream machinery (CointScanner,
AnalysisPipeline, BacktestEngine) is already verified extensively
elsewhere in this project and is reused unmodified here, not re-verified.

Run: python debug/_verify_pit_wfa_wrds_daily.py
(All checks are synthetic/offline -- no WRDS connection needed.)
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from debug.synthetic_pair_factory import make_synthetic_pair
import research.pit_wfa_wrds_daily as pw


def check(name, cond):
    cond = bool(cond)
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}")
    return cond


def _to_daily_close_df(price_series: pd.Series) -> pd.DataFrame:
    """Reindexes a synthetic hourly-frequency price Series (from
    make_synthetic_pair, whose statistical content -- OU-mean-reverting
    spread vs. random walk -- doesn't depend on calendar frequency) onto a
    daily DatetimeIndex of the same length, wrapped as a minimal OHLCV
    DataFrame with the "close" column DataAligner/build_returns_matrix
    require."""
    idx = pd.date_range("2015-01-01", periods=len(price_series), freq="B")  # business days
    return pd.DataFrame({"close": price_series.values}, index=idx)


def verify_screen_finds_real_pair_rejects_noise():
    print("\n=== 1. screen_universe_at_cutoff (daily, chunked-correlation path): finds a real "
          "cointegrated pair, rejects an uncorrelated noise pair ===")
    price_a, price_b, gt = make_synthetic_pair(n_bars=1500, seed=1, cointegrated=True,
                                                 mean_reversion_speed=0.08, noise_std=1.0)
    # screen_universe_at_cutoff has a real, deliberate `len(truncated) < 10: return []`
    # minimum-universe-size guard (copied faithfully from pit_wfa.py's own, reasonable
    # safeguard against running EG on a statistically meaningless tiny sample) -- need at
    # least 10 total symbols for this test to actually exercise the function, not just
    # trip the guard and return early regardless of correctness. 4 noise pairs (8 symbols)
    # + the 2 real ones (AAA/BBB) = 10 exactly.
    noise_pairs = {}
    for i, seed in enumerate([99, 7, 42, 13]):
        pc, pd_, _ = make_synthetic_pair(n_bars=1500, seed=seed, cointegrated=False, noise_std=1.0)
        noise_pairs[f"N{i}A"] = _to_daily_close_df(pc)
        noise_pairs[f"N{i}B"] = _to_daily_close_df(pd_)

    universe = {
        "AAA": _to_daily_close_df(price_a), "BBB": _to_daily_close_df(price_b),
        **noise_pairs,
    }
    train_start = universe["AAA"].index.min()
    train_end = universe["AAA"].index.max()

    confirmed = pw.screen_universe_at_cutoff(universe, train_start, train_end, n_workers=2)
    confirmed_keys = {frozenset((p.symbol_a, p.symbol_b)) for p in confirmed}

    ok = check("the genuinely cointegrated pair (AAA/BBB) IS confirmed",
               frozenset(("AAA", "BBB")) in confirmed_keys)
    ok &= check("confirmed set is EXACTLY {AAA/BBB} -- no false positives from the noise pairs",
                confirmed_keys == {frozenset(("AAA", "BBB"))})
    return ok


def verify_determine_analysis_window():
    print("\n=== 2. determine_analysis_window: correct min/max across ragged-length series ===")
    short = pd.DataFrame({"close": [1.0, 2.0]}, index=pd.date_range("2018-06-01", periods=2, freq="D"))
    long = pd.DataFrame({"close": np.arange(500.0)}, index=pd.date_range("2018-01-01", periods=500, freq="D"))
    start, end = pw.determine_analysis_window({"SHORT": short, "LONG": long})
    ok = check("window start is the EARLIEST symbol's first date (2018-01-01, from LONG)",
               start == pd.Timestamp("2018-01-01"))
    ok &= check("window end is the LATEST symbol's last date (from LONG, since it extends "
                "past SHORT's end date)", end == long.index.max())
    return ok


def verify_load_universe_wrapper_calls_loader_correctly():
    print("\n=== 3. load_universe_wrds_daily: calls universe_loader with the right tf_label "
          "and all 4 sources included (WRDS-priority is the loader's own merge order, not "
          "reimplemented here -- checking the call is wired correctly, not re-testing the "
          "loader's own merge logic, already verified elsewhere) ===")
    import unittest.mock as mock
    with mock.patch("universe_loader.load_full_universe") as mocked:
        mocked.return_value = {}
        pw.load_universe_wrds_daily()
        _, kwargs = mocked.call_args
        ok = check("tf_label='1D' passed through", kwargs.get("tf_label") == "1D")
        ok &= check("include_wrds=True (WRDS is in the merge, wins on collision by the "
                    "loader's own documented order)", kwargs.get("include_wrds") is True)
        ok &= check("include_yfinance/include_binance/include_ibkr all True (gap-filling "
                    "sources stay included, they just never override WRDS)",
                    kwargs.get("include_yfinance") is True and kwargs.get("include_binance") is True
                    and kwargs.get("include_ibkr") is True)
    return ok


def verify_trades_to_replay_df():
    print("\n=== 4. trades_to_replay_df: converts Trade dataclass instances into the exact "
          "DataFrame shape portfolio_sim.replay_portfolio() requires ===")
    from backtest import Trade
    t1 = Trade(tf="1D", symbol_a="AAA", symbol_b="BBB", hedge_method="ols", hedge_ratio=1.05,
               entry_time=pd.Timestamp("2020-01-01"), entry_z=3.2, entry_spread=1.5,
               side="short", n_shares_a=100, n_shares_b=105.0, half_life_at_entry=20.0,
               hurst_at_entry=0.3, exit_time=pd.Timestamp("2020-01-10"), pnl_net=250.0)
    df = pw.trades_to_replay_df([t1])
    required_cols = ["symbol_a", "symbol_b", "tf", "entry_time", "exit_time", "entry_spread",
                      "entry_z", "half_life_at_entry", "side", "n_shares_a", "n_shares_b", "pnl_net"]
    ok = check("all columns replay_portfolio() requires are present",
               all(c in df.columns for c in required_cols))
    ok &= check("values are carried through correctly, not dropped or transformed "
               "(pnl_net=250.0, n_shares_a=100)",
               df.iloc[0]["pnl_net"] == 250.0 and df.iloc[0]["n_shares_a"] == 100)
    empty_df = pw.trades_to_replay_df([])
    ok &= check("an empty trade list produces an empty DataFrame with the right columns "
               "(not a crash, not a missing-column error downstream)",
               len(empty_df) == 0 and all(c in empty_df.columns for c in required_cols))
    return ok


def verify_load_universe_strips_timezone():
    print("\n=== 5. load_universe_wrds_daily: normalizes tz-AWARE indices to tz-naive -- real "
          "bug found live (2026-09-03): 15 of 43,883 real symbols (Binance crypto) are "
          "tz-aware while everything else is tz-naive, crashing determine_analysis_window's "
          "min()/max() on the very first full-scale run ===")
    import unittest.mock as mock
    naive_idx = pd.date_range("2020-01-01", periods=5, freq="D")
    aware_idx = pd.date_range("2020-01-01", periods=5, freq="D", tz="UTC")
    fake_universe = {
        "EQUITY": pd.DataFrame({"close": [1.0] * 5}, index=naive_idx),
        "BTC": pd.DataFrame({"close": [2.0] * 5}, index=aware_idx),
    }
    with mock.patch("universe_loader.load_full_universe", return_value=fake_universe):
        result = pw.load_universe_wrds_daily()
    ok = check("the tz-aware symbol (BTC) is normalized to tz-naive",
               result["BTC"].index.tz is None)
    ok &= check("the already-tz-naive symbol (EQUITY) is left unchanged",
               result["EQUITY"].index.tz is None)
    try:
        min(result["EQUITY"].index.min(), result["BTC"].index.min())
        no_crash = True
    except TypeError:
        no_crash = False
    ok &= check("min()/max() across the mixed-tz universe no longer raises TypeError "
               "(this is the exact crash the real live run hit)", no_crash)
    return ok


def main():
    results = [
        verify_screen_finds_real_pair_rejects_noise(),
        verify_determine_analysis_window(),
        verify_load_universe_wrapper_calls_loader_correctly(),
        verify_trades_to_replay_df(),
        verify_load_universe_strips_timezone(),
    ]
    print("\n" + "=" * 60)
    if all(results):
        print("ALL CHECKS PASSED")
    else:
        print(f"FAILURES: {results.count(False)}/{len(results)} check groups failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
