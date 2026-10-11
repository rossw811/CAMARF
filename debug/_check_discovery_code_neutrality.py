"""
Real-data equivalence check (2026-10-10, CachyOS): lineage marks the finished discovery run (beb004b4) STALE because
code changed afterwards (S35's shared no-trade rule moved into data_wrds, the A1-residual alignment in
_build_log_price_map, Hurst/handler fixes in analysis.py). Before letting the pool chain use those outputs, verify the
changes are behaviour-neutral for them: rebuild the scan's log-price matrix with the CURRENT code exactly as main() does
(load_wrds_universe exclude arm -> build_log_prices_and_returns_bounded(lookback_years=50)) and recompute a seeded random
sample of saved (pair, window) p-values with the same both-directions EG (_eg_worker, max of ab/ba). Every recomputed
p-value must equal the saved one (rtol 1e-9). The ADV / membership gates only choose WHICH windows are tested; their
code (dollar_volume, rolling_adv, membership gate) is unchanged since beb004b4 (git diff checked separately).
Usage (CachyOS): python debug/_check_discovery_code_neutrality.py
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.argv = [sys.argv[0]]   # the scan module parses --d18 / --grid-offset at import


def main():
    import research.wrds_deep_history_episodic_scan as scan
    from analysis import _eg_worker
    from config import Config
    R = os.path.join(ROOT, "output", "research")
    samp = []
    for tier, n in ((2, 300), (3, 200)):
        w = pd.read_parquet(os.path.join(R, f"wrds_deep_history_episodic_scan_tier{tier}_windows.parquet"),
                            columns=["symbol_a", "symbol_b", "window_start", "pvalue"])
        samp.append(w.sample(n=n, random_state=20261010).assign(tier=tier))
    S = pd.concat(samp, ignore_index=True)
    close_by_symbol, _ = scan.load_wrds_universe(d18_arm="exclude")
    need = set(S.symbol_a) | set(S.symbol_b)
    log_price_df, _ = scan.build_log_prices_and_returns_bounded(close_by_symbol, lookback_years=50)
    bad, n_ok = [], 0
    for r in S.itertuples():
        if r.symbol_a not in log_price_df.columns or r.symbol_b not in log_price_df.columns:
            bad.append((r.tier, r.symbol_a, r.symbol_b, "missing column")); continue
        a = log_price_df[r.symbol_a].to_numpy(dtype=float); b = log_price_df[r.symbol_b].to_numpy(dtype=float)
        m = np.isfinite(a) & np.isfinite(b)
        a, b = a[m], b[m]
        s0 = int(r.window_start)
        sa, sb = a[s0:s0 + scan.EPISODIC_WINDOW_BARS], b[s0:s0 + scan.EPISODIC_WINDOW_BARS]
        ab = _eg_worker((r.symbol_a, r.symbol_b, sa, sb, Config.ANALYSIS.EG_MAX_LAG, scan.TF_LABEL))
        ba = _eg_worker((r.symbol_b, r.symbol_a, sb, sa, Config.ANALYSIS.EG_MAX_LAG, scan.TF_LABEL))
        if not (ab.get("ok") and ba.get("ok")):
            bad.append((r.tier, r.symbol_a, r.symbol_b, "eg failed")); continue
        p = max(ab["pvalue"], ba["pvalue"])
        if np.isclose(p, r.pvalue, rtol=1e-9, atol=1e-15):
            n_ok += 1
        else:
            bad.append((r.tier, r.symbol_a, r.symbol_b, f"{p:.6g} vs saved {r.pvalue:.6g}"))
    print(f"symbols needed {len(need)}; sample {len(S)}; identical {n_ok}; differing/failed {len(bad)}")
    for x in bad[:20]:
        print("  ", x)
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
