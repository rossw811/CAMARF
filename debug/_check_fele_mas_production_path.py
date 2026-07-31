"""
debug/_check_fele_mas_production_path.py -- one-shot diagnostic, NOT a
comparison-arm script. Reproduces the EXACT production path
(UniverseBuilder().build(connect=False, fetch=False) -> _run_one_tf's own
universe/exclusion/frequency-validation logic -> DataAligner.align_universe
-> UniverseFilter.run) for tf_label="1h", then checks directly whether FELE
and MAS survive each stage and what their actual realized Pearson correlation
is on the PRODUCTION-aligned overlap (as opposed to research/
pearson_threshold_sensitivity.py's ad hoc "every symbol with a _1hr.parquet
file" universe, which does not replicate exclusion_set/frequency-validation/
ADV-filter gating).

Read-only. Never fetches (fetch=False). Writes nothing.
"""
import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from data import UniverseBuilder, DataStore, DataAligner
from analysis import UniverseFilter, Config

print("=== Building full universe via UniverseBuilder().build(connect=False, fetch=False) ===")
builder = UniverseBuilder()
universe = builder.build(connect=False, fetch=False)
print(f"universe.assets: {len(universe.assets)}  universe.data keys: {len(universe.data)}")

syms = {s for s, _ in universe.assets}
excl = getattr(universe, "exclusion_set", set()) or set()
print("FELE in universe.assets:", "FELE" in syms, " in exclusion_set:", "FELE" in excl)
print("MAS  in universe.assets:", "MAS" in syms, " in exclusion_set:", "MAS" in excl)
print("FELE_1h in universe.data:", "FELE_1h" in universe.data and universe.data["FELE_1h"] is not None)
print("MAS_1h in universe.data:", "MAS_1h" in universe.data and universe.data["MAS_1h"] is not None)

tf_label = "1h"
_SHALLOW_CAP = {}
tf_data_raw = {}
freq_mismatches = []
for sym, cls in universe.assets:
    if sym in excl:
        continue
    key = f"{sym}_{tf_label}"
    if key not in universe.data or universe.data[key] is None:
        continue
    df = universe.data[key]
    if not DataStore.validate_frequency(sym, tf_label, df):
        freq_mismatches.append(sym)
        continue
    tf_data_raw[sym] = df

print(f"\ntf_data_raw (post exclusion+freq-validation): {len(tf_data_raw)} assets")
print("FELE in tf_data_raw:", "FELE" in tf_data_raw)
print("MAS  in tf_data_raw:", "MAS" in tf_data_raw)
if "FELE" in freq_mismatches:
    print("FELE FAILED validate_frequency in production path")
if "MAS" in freq_mismatches:
    print("MAS FAILED validate_frequency in production path")

# Replicate the ADV filter exactly as _run_one_tf does (post-fix: Config.STATS)
_adv_threshold = getattr(Config.STATS, "ADV_FILTER_USD", 0.0)
print(f"\nADV_FILTER_USD (post-fix): {_adv_threshold}")
if _adv_threshold > 0:
    import pandas as pd
    _cache_dir = Config.DATA.CACHE_DIR
    _adv_map = {}
    for sym in list(tf_data_raw.keys()):
        _hr_path = os.path.join(_cache_dir, f"{sym}_1hr.parquet")
        if not os.path.exists(_hr_path):
            _adv_map[sym] = float("nan")
            continue
        try:
            _hr = pd.read_parquet(_hr_path)
            if "close" in _hr.columns and "volume" in _hr.columns:
                _hr.index = pd.to_datetime(_hr.index)
                _dv = _hr["close"] * _hr["volume"]
                _daily_dv = _dv.groupby(_hr.index.date).sum()
                _adv_map[sym] = float(_daily_dv.mean()) if len(_daily_dv) > 0 else float("nan")
            else:
                _adv_map[sym] = float("nan")
        except Exception:
            _adv_map[sym] = float("nan")
    print("FELE ADV:", _adv_map.get("FELE"), " passes:", _adv_map.get("FELE", 0) >= _adv_threshold)
    print("MAS  ADV:", _adv_map.get("MAS"), " passes:", _adv_map.get("MAS", 0) >= _adv_threshold)
    _adv_filtered = {s: v for s, v in _adv_map.items() if v >= _adv_threshold}
    tf_data_raw_adv = {s: df for s, df in tf_data_raw.items() if s in _adv_filtered}
    print(f"tf_data_raw after ADV filter: {len(tf_data_raw_adv)} (of {len(tf_data_raw)})")
else:
    tf_data_raw_adv = tf_data_raw

print("\n=== DataAligner.align_universe (production path, WITHOUT ADV filter -- pre-fix state) ===")
aligned = DataAligner.align_universe(
    {f"{sym}_{tf_label}": df for sym, df in tf_data_raw.items()}, tf_label
)
print(f"aligned (no ADV): {len(aligned)} assets")
print("FELE_1h in aligned (no ADV):", "FELE_1h" in aligned)
print("MAS_1h in aligned (no ADV):", "MAS_1h" in aligned)

if "FELE_1h" in aligned and "MAS_1h" in aligned:
    import numpy as np
    fa = aligned["FELE_1h"]["close"]
    fb = aligned["MAS_1h"]["close"]
    ra = np.log(fa).diff()
    rb = np.log(fb).diff()
    both = ra.notna() & rb.notna()
    corr = ra[both].corr(rb[both])
    print(f"FELE/MAS realized Pearson corr on PRODUCTION-aligned overlap (n={both.sum()}): {corr:.6f}")

print("\n=== Now WITH the (fixed) ADV filter applied ===")
aligned_adv = DataAligner.align_universe(
    {f"{sym}_{tf_label}": df for sym, df in tf_data_raw_adv.items()}, tf_label
)
print(f"aligned (with ADV): {len(aligned_adv)} assets")
print("FELE_1h in aligned (with ADV):", "FELE_1h" in aligned_adv)
print("MAS_1h in aligned (with ADV):", "MAS_1h" in aligned_adv)

print("\n=== UniverseFilter.run (production path, current MIN_PEARSON_CORR threshold) ===")
asset_class_map = {sym: cls for sym, cls in universe.assets}
threshold = getattr(Config.UNIVERSE, "MIN_PEARSON_CORR", 0.40)
print(f"threshold: {threshold}")
pairs, retained, returns, corr_mat, sym_order = UniverseFilter.run(
    aligned, asset_class_map, threshold, tf_label, return_matrices=True
)
print(f"candidate pairs (no ADV, pre-EG): {len(pairs)}")
has_fele_mas = any(
    {p["symbol_a"], p["symbol_b"]} == {"FELE", "MAS"} for p in pairs
)
print("FELE/MAS in production candidate_pairs (pre-EG):", has_fele_mas)
if "FELE" in sym_order and "MAS" in sym_order:
    ia, ib = sym_order.index("FELE"), sym_order.index("MAS")
    print(f"FELE/MAS correlation in production's own matrix: {corr_mat[ia, ib]:.6f}")
