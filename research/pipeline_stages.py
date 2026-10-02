"""
research/pipeline_stages.py -- the discovery -> pools -> search chain declared ONCE for lineage.py (2026-09-27).

Every script in the chain gets its stage from here (`stage(name)`) and calls `.record()` after a successful run, so
the dependency graph cannot drift between scripts. `python research/pipeline_stages.py` prints the whole chain's
status (up to date / stale and why).

Chain:
  episodic_scan (1D, WRDS) ─┐
  intraday_scan_1h ─────────┼─> adapter ─> comparison_arms ─> pit_eligibility ─> clean_pools ─> pool_spreads
  intraday_scan_4h ─────────┘                                      ▲                                   │
                              (tier-3 windows also feed pit_eligibility)          squeeze_features <─┘
                                                                       strategy_search <─ clean_pools, squeeze_features
Notes: squeeze_features rewrites the spread files IN PLACE, so the spread directories are ITS outputs and
pool_spreads declares only its report (otherwise a squeeze run would look like tampering with pool_spreads' output).
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from lineage import Lineage

_R = "output/research"
_CORE = ["analysis.py", "universe_loader.py", "config.py", "stats.py", "data.py"]
_SPREAD_DIRS = ["output/results/1D", "output/results/1hr", "output/results/4hr"]


def _declare(lin: Lineage) -> Lineage:
    lin.stage("episodic_scan",
              code=["research/wrds_deep_history_episodic_scan.py", "data_wrds.py", "research/rolling_adv_comparison.py"]
              + _CORE, inputs=["output/cache/wrds"],
              outputs=[f"{_R}/wrds_deep_history_episodic_scan_{n}.parquet" for n in
                       ("tier1", "tier2_windows", "tier2_confirmed", "tier3_pairs", "tier3_windows", "tier3_confirmed")],
              params={"lookback_years": 50, "d18_arm": "exclude"})
    # D18 sensitivity arm (Ross 2026-10-02): same scan with CRSP midpoint days and quote-only files INCLUDED
    lin.stage("episodic_scan_d18incl",
              code=["research/wrds_deep_history_episodic_scan.py", "data_wrds.py", "research/rolling_adv_comparison.py"]
              + _CORE, inputs=["output/cache/wrds", "output/cache/wrds/_quote_only"],
              outputs=[f"{_R}/wrds_deep_history_episodic_scan_{n}_d18incl.parquet" for n in
                       ("tier1", "tier2_windows", "tier2_confirmed", "tier3_pairs", "tier3_windows", "tier3_confirmed")],
              params={"lookback_years": 50, "d18_arm": "include"})
    for tf in ("1h", "4h"):
        lin.stage(f"intraday_scan_{tf}", code=["research/intraday_episodic_scan.py",
                                               "research/wrds_deep_history_episodic_scan.py"] + _CORE,
                  inputs=["output/cache", "output/research/intraday_cache_coverage.parquet"],
                  outputs=[f"{_R}/intraday_episodic_scan_{tf}_tier3_windows.parquet"], params={"tf": tf})
    lin.stage("adapter", code=["research/episodic_pairs_adapter.py"] + _CORE,
              inputs=["episodic_scan", "intraday_scan_1h", "intraday_scan_4h"],
              outputs=[f"{_R}/episodic_confirmed_pairs_adapter_output.parquet"])
    lin.stage("comparison_arms", code=["research/build_comparison_arm_pairs.py"], inputs=["adapter"],
              outputs=[f"{_R}/{n}_pairs.parquet" for n in ("purity", "hybrid", "tiered")])
    lin.stage("pit_eligibility", code=["research/purity_pit_eligibility.py"],
              inputs=["comparison_arms", "episodic_scan", "intraday_scan_1h", "intraday_scan_4h"],
              outputs=[f"{_R}/purity_pairs_pit_k{k}.parquet" for k in (1, 2)])
    lin.stage("clean_pools", code=["research/clean_pool_identity_pairs.py", "research/episodic_pairs_adapter.py"],
              inputs=["pit_eligibility"],
              outputs=[f"{_R}/purity_pairs_pit_k{k}_clean.parquet" for k in (1, 2)]
              + [f"{_R}/clean_pool_identity_pairs_report.parquet"])
    lin.stage("pool_spreads", code=["research/regenerate_pool_spread_series.py", "research/episodic_pairs_adapter.py"]
              + _CORE, inputs=["clean_pools"], outputs=[f"{_R}/regenerate_pool_spread_series_report.parquet"])
    lin.stage("squeeze_features", code=["research/squeeze_momentum_features.py"], inputs=["pool_spreads"],
              outputs=_SPREAD_DIRS)
    lin.stage("strategy_search", code=["research/strategy_search.py", "portfolio_sim.py", "portfolio_math.py",
                                       "pnl_dollar.py", "backtest.py", "deflated_sharpe.py"],
              inputs=["clean_pools", "squeeze_features", "docs/PREREGISTRATION_STRATEGY_SEARCH_2026-09-27.md"],
              outputs=[f"{_R}/strategy_search"])
    return lin


def pipeline() -> Lineage:
    return _declare(Lineage())


def stage(name: str):
    return pipeline()._stages[name]


if __name__ == "__main__":
    for n, s in pipeline().status().items():
        print(f"{'OK   ' if s['up_to_date'] else 'STALE'}  {n:18s} {s['reason'][:150]}")
