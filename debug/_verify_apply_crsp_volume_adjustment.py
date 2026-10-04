"""
Synthetic check for research/apply_crsp_volume_adjustment.py (DEV-003, Ross 2026-10-03: "stop, fix, restart" the
discovery whose ADV gate used raw CRSP volume). Temp WRDS dir:
  1. a mapped CRSP file with a 2:1 split: `volume` becomes raw x factor, `volume_raw` keeps the raw values,
     `volume_adj_factor` stores the factor, close untouched;
  2. re-running is a no-op (idempotent: a file that already has volume_raw is skipped);
  3. a PERMNO-labelled file is mapped from its name;
  4. an unmapped label is left untouched and reported "unmapped";
  5. a security with a cash-payment event gets NaN volume before it (unknown factor), never a guess;
  6. a file under _quote_only/ is adjusted too;
  8. an EXTRA verified map (`extra_maps`, e.g. ETFs/ADRs resolved 2026-10-04) adds labels the security master lacks;
     only rows with identity_ok are used;
  7. future fetches: all four CRSP fetch paths in data_wrds.py write volume = raw x fac and keep volume_raw
     (source check -- the fetch itself needs a live WRDS connection).
Run: python debug/_verify_apply_crsp_volume_adjustment.py
"""
import os
import re
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def main():
    try:
        import research.apply_crsp_volume_adjustment as ap
    except ImportError as e:
        check("module_exists", False, str(e)); return finish()
    root = tempfile.mkdtemp(prefix="apply_vol_")
    try:
        idx = pd.bdate_range("2020-02-24", periods=10)
        mk = lambda: pd.DataFrame({"close": 50.0, "volume": 100.0}, index=idx)
        mk().to_parquet(os.path.join(root, "AAA_1D.parquet"))
        mk().to_parquet(os.path.join(root, "PERMNO222_1D.parquet"))
        mk().to_parquet(os.path.join(root, "NOMAP_1D.parquet"))
        mk().to_parquet(os.path.join(root, "CASHY_1D.parquet"))
        os.makedirs(os.path.join(root, "_quote_only"))
        mk().to_parquet(os.path.join(root, "_quote_only", "PERMNO444_1D.parquet"))
        events = pd.DataFrame({"permno": [111, 222, 333, 444], "disexdt": pd.to_datetime(["2020-03-02"] * 4),
                               "disfacpr": [1.0, 1.0, -0.3, 1.0], "distype": ["FRS", "FRS", "CP", "FRS"]})
        label_map = pd.DataFrame({"label": ["AAA", "CASHY"], "permno": [111, 333]})
        rep = ap.apply(root, events, label_map)
        a = pd.read_parquet(os.path.join(root, "AAA_1D.parquet"))
        before = idx < pd.Timestamp("2020-03-02")
        check("1.adjusted_raw_kept", np.allclose(a.loc[before, "volume"], 200.0) and np.allclose(a.loc[~before, "volume"], 100.0)
              and np.allclose(a["volume_raw"], 100.0) and np.allclose(a.loc[before, "volume_adj_factor"], 2.0)
              and np.allclose(a["close"], 50.0), a.head(3).to_string())
        rep2 = ap.apply(root, events, label_map)
        a2 = pd.read_parquet(os.path.join(root, "AAA_1D.parquet"))
        check("2.idempotent", a2.equals(a) and (rep2.set_index("label").loc["AAA", "status"] == "already_adjusted"))
        p = pd.read_parquet(os.path.join(root, "PERMNO222_1D.parquet"))
        check("3.permno_label", np.allclose(p.loc[before, "volume"], 200.0))
        n = pd.read_parquet(os.path.join(root, "NOMAP_1D.parquet"))
        check("4.unmapped_untouched", "volume_raw" not in n.columns and rep.set_index("label").loc["NOMAP", "status"] == "unmapped")
        c = pd.read_parquet(os.path.join(root, "CASHY_1D.parquet"))
        check("5.cash_event_unknown", c.loc[before, "volume"].isna().all() and np.allclose(c.loc[~before, "volume"], 100.0))
        q = pd.read_parquet(os.path.join(root, "_quote_only", "PERMNO444_1D.parquet"))
        check("6.quote_only_adjusted", np.allclose(q.loc[before, "volume"], 200.0))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    root2 = tempfile.mkdtemp(prefix="apply_vol2_")
    try:
        idx2 = pd.bdate_range("2020-02-24", periods=10)
        for lab in ("ETFX", "BADX"):
            pd.DataFrame({"close": 50.0, "volume": 100.0}, index=idx2).to_parquet(os.path.join(root2, f"{lab}_1D.parquet"))
        ev2 = pd.DataFrame({"permno": [555, 666], "disexdt": pd.to_datetime(["2020-03-02"] * 2), "disfacpr": [1.0, 1.0],
                            "distype": ["FRS", "FRS"]})
        extra = pd.DataFrame({"label": ["ETFX", "BADX"], "permno": [555, 666], "identity_ok": [True, False]})
        r8 = ap.apply(root2, ev2, pd.DataFrame(columns=["label", "permno"]), extra_maps=[extra]).set_index("label")
        e = pd.read_parquet(os.path.join(root2, "ETFX_1D.parquet"))
        check("8.extra_map", r8.loc["ETFX", "status"] == "adjusted" and np.allclose(e.loc[idx2 < "2020-03-02", "volume"], 200.0)
              and r8.loc["BADX", "status"] == "unmapped", r8["status"].to_dict())
    finally:
        shutil.rmtree(root2, ignore_errors=True)
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data_wrds.py"), encoding="utf-8").read()
    n_adj = len(re.findall(r'"volume": (?:g|df)\["(?:dlyvol|mthvol)"\] \* fac,', src))
    n_raw = len(re.findall(r'"volume_raw": (?:g|df)\["(?:dlyvol|mthvol)"\],', src))
    n_bare = len(re.findall(r'"volume": (?:g|df)\["(?:dlyvol|mthvol)"\],', src))
    check("7.fetch_paths_adjusted", n_adj == 4 and n_raw == 4 and n_bare == 0, f"adjusted={n_adj} raw_kept={n_raw} bare={n_bare}")
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
