"""
Synthetic check for research/crsp_volume_split_adjustment.py (DEV-003). A security with a 2:1 split (disfacpr 1.0)
ex 2020-03-02 and a 3:1 split (disfacpr 2.0) ex 2021-03-01: volume before 2020-03-02 x 6, between x 3, from the
second ex-date on x 1 (ex-date itself already in post-split shares). No events -> unchanged. Dollar volume with the
adjusted volume equals raw price x raw volume (the invariant that makes the fix right).
Same-date events combine ADDITIVELY, as CRSP's dlycumfacpr does: factor = 1 + sum(disfacpr) (found 2026-10-03
comparing against CRSP's own dlycumfacpr on 307 securities: multiplying two spin-off rows on one ex-date mismatched,
e.g. 1.0822 x 1.3272 / (1 + 0.0822 + 0.3272) = 1.0191, the observed jump). Terminal events (disfacpr -1: merger,
liquidation) occur after the last trade; the factor is normalised to the security's LAST day, which neutralises them
(an un-normalised first impact run zeroed whole histories).
Cash-payment / partial-liquidation events (disfacpr between -1 and 0, not a split: CPBLST, CPSCMO, CPSCM, SECDO...)
follow a CRSP convention not reproduced here -> factor NaN (unknown) before them; 40 of 30,256 labelled securities.
Run: python debug/_verify_crsp_volume_split_adjustment.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from research.crsp_volume_split_adjustment import adjusted_volume, cumulative_factor

dates = pd.to_datetime(["2020-02-28", "2020-03-02", "2021-02-26", "2021-03-01", "2022-01-03"])
ev = pd.DataFrame({"disexdt": pd.to_datetime(["2021-03-01", "2020-03-02"]), "disfacpr": [2.0, 1.0]})
f = cumulative_factor(dates, ev)
raw_px = np.array([60.0, 30.0, 30.0, 10.0, 10.0])          # real traded prices around the splits
adj_px = raw_px / f                                          # what the cache stores as `close`
raw_vol = np.array([100.0, 200.0, 200.0, 600.0, 600.0])
av = adjusted_volume(pd.DataFrame({"volume": raw_vol}, index=dates), ev).to_numpy()
same_day = pd.DataFrame({"disexdt": pd.to_datetime(["2021-03-01", "2021-03-01"]), "disfacpr": [0.5, 0.25]})
merged = pd.DataFrame({"disexdt": pd.to_datetime(["2021-03-01", "2023-01-02"]), "disfacpr": [1.0, -1.0]})
cash = pd.DataFrame({"disexdt": pd.to_datetime(["2021-03-01"]), "disfacpr": [-0.3], "distype": ["CP"]})
cf = cumulative_factor(dates, cash)
checks = {
    "cash_event_unknown_before": bool(np.isnan(cf[:3]).all()) and cf[3:].tolist() == [1.0, 1.0],
    "same_date_additive": cumulative_factor(dates, same_day).tolist() == [1.75, 1.75, 1.75, 1.0, 1.0],
    "terminal_event_normalised": cumulative_factor(dates, merged).tolist() == [2.0, 2.0, 2.0, 1.0, 1.0],
    "factors": f.tolist() == [6.0, 3.0, 3.0, 1.0, 1.0],
    "no_events_unchanged": cumulative_factor(dates, pd.DataFrame(columns=["disexdt", "disfacpr"])).tolist() == [1.0] * 5,
    "dollar_volume_invariant": np.allclose(adj_px * av, raw_px * raw_vol),
}
for k, v in checks.items():
    print(f"[{'PASS' if v else 'FAIL'}] {k}")
print(); print(f"{sum(checks.values())}/{len(checks)} checks passed")
sys.exit(0 if all(checks.values()) else 1)
