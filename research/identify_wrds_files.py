"""
research/identify_wrds_files.py -- one canonical label -> PERMNO map for the CRSP files in output/cache/wrds, each
file identified from its CONTENT (2026-10-12, label-map identity bug).

Why: full_us_market_label_map.parquet (built by the D17 relabel against crsp_full_security_master_v2, which holds
ordinary shares only) maps ADR tickers to a reused ticker's OLD holder -- TM -> Toastmaster (77456), SHEL -> Sheldahl,
GSK -> Gamble-Skogmo -- although TM_1D.parquet is Toyota's ADR, 1972-2025. symbol_permno_map.parquet disagrees with it
on 2,450 labels. The DEV-003 volume restatement, universe_loader's D17 PERMNO aliasing and the same-company pool rule
all read the label map.

Method (D17's containment rule, now on the FULL names history, crsp.stocknames every share type --
output/cache/wrds/crsp_stocknames_all.parquet): the candidates for a ticker label are the PERMNOs that HELD the ticker
on the file's last date (+-TOL_DAYS; capped at the names table's end, 2024-12-31, since the files run to 2025-12-31);
a candidate must also have a listing life (all its tickers, min namedt..max nameenddt, open-ended if it reaches the
table's end) containing the file's first..last dates. Exactly one -> 'identified'; none -> 'unidentified'; several ->
'ambiguous' (never guessed). PERMNO<n> labels are 'self'. (A first version used the whole life alone and picked
Barrick for a 2020-2025 ABX file that is Abacus Life -- caught on review of real disagreements.)
Steps (2026-10-12; a dates-only rule cannot be final -- some D17 labels are not a ticker the security held at its
end: the 'B' file is Barrick, 'GOLD' is A-Mark, 'NEG' is labelled by its FIRST ticker):
  identify  -> wrds_label_permno_canonical.parquet (dates rule; compared with both old maps)
  resolve   -> output/research/_identity_resolve_input.parquet: every label where the dates rule and the D17 label map
               disagree or either is missing, with each candidate PERMNO (dates rule, label map, symbol map) and three
               dates (15/50/85% through the file); WRDS job 28_identity_resolve_returns fetches crsp.dsf_v2 dlyret
  finalize  -> wrds_label_permno_final.parquet (label, permno, source): agree -> 'agree'; PERMNO<n> -> 'self';
               otherwise the ONE candidate whose daily returns match the file's on >= 90% of days (+-45 days around
               the three dates, |diff| < 1e-3) -> 'returns'; none / several / untestable -> permno NaN, source
               'unresolved_*' (never guessed). Validated: return check on a 562-label sample, 2026-10-12.
Usage: python research/identify_wrds_files.py [identify|resolve|finalize]
Test:  debug/_verify_identify_wrds_files.py
"""
import glob
import os
import re
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_W = os.path.join(ROOT, "output", "cache", "wrds")
OUT = os.path.join(_W, "wrds_label_permno_canonical.parquet")
TOL_DAYS = 10   # same tolerance as research/relabel_wrds_by_recency_d17.py (listing-date vs first-trade offsets)


def identify(spans: pd.DataFrame, names: pd.DataFrame, names_end, data_end, tol_days: int = TOL_DAYS) -> pd.DataFrame:
    """spans: label, first, last. names: permno, ticker, namedt, nameenddt."""
    tol = pd.Timedelta(days=tol_days)
    names_end, data_end = pd.Timestamp(names_end), pd.Timestamp(data_end)
    nm = names.dropna(subset=["ticker"]).copy()
    # the permno's WHOLE listing life across all its tickers (Toyota traded as TOYOY before TM; the TM file starts 1972)
    life = names.groupby("permno").agg(start=("namedt", "min"), end=("nameenddt", "max"))
    life.loc[life["end"] >= names_end, "end"] = data_end
    nm.loc[nm["nameenddt"] >= names_end, "nameenddt"] = data_end
    by_t = {t: g for t, g in nm.groupby("ticker")}
    rows = []
    for r in spans.itertuples():
        lab = str(r.label)
        m = re.fullmatch(r"PERMNO(\d+)", lab)
        if m:
            rows.append({"label": lab, "permno": int(m.group(1)), "status": "self", "n_candidates_containing": 1})
            continue
        g = by_t.get(lab)
        if g is None:
            rows.append({"label": lab, "permno": np.nan, "status": "unidentified", "n_candidates_containing": 0})
            continue
        # holder of the ticker on the file's last date (capped at the names table's end), +- tol
        t_end = min(pd.Timestamp(r.last), data_end)
        held = g[(g["namedt"] - tol <= t_end) & (g["nameenddt"] + tol >= t_end)]["permno"].unique()
        lf = life.loc[[p for p in held if p in life.index]]
        ok = lf[(lf["start"] - tol <= r.first) & (lf["end"] + tol >= r.last)]
        n = len(ok)
        rows.append({"label": lab, "permno": int(ok.index[0]) if n == 1 else np.nan,
                     "status": "identified" if n == 1 else ("ambiguous" if n > 1 else "unidentified"),
                     "n_candidates_containing": n})
    out = pd.DataFrame(rows)
    return spans.merge(out, on="label")


def file_spans(root: str = _W) -> pd.DataFrame:
    rows = []
    for p in glob.glob(os.path.join(root, "*_1D.parquet")):
        lab = os.path.basename(p)[:-len("_1D.parquet")]
        if lab.startswith("GVKEY"):
            continue
        try:
            idx = pd.to_datetime(pd.read_parquet(p, columns=["close"]).dropna().index)
        except Exception:
            continue
        if len(idx):
            rows.append({"label": lab, "first": idx.min(), "last": idx.max()})
    return pd.DataFrame(rows)


RESOLVE_INPUT = os.path.join(ROOT, "output", "research", "_identity_resolve_input.parquet")
RESOLVE_RETURNS = os.path.join(ROOT, "output", "research", "identity_resolve_returns.parquet")
FINAL = os.path.join(_W, "wrds_label_permno_final.parquet")
MATCH_SHARE, MATCH_TOL, WINDOW_DAYS, MIN_DAYS = 0.9, 1e-3, 45, 15


def return_match_share(file_ret: pd.Series, crsp_ret: pd.Series, dates) -> float:
    """Share of days (+-WINDOW_DAYS around each date) on which the file's close-to-close return equals CRSP's dlyret
    within MATCH_TOL; NaN when fewer than MIN_DAYS overlapping days."""
    f = file_ret[~file_ret.index.duplicated(keep="last")].sort_index()
    c = crsp_ret[~crsp_ret.index.duplicated(keep="last")].sort_index()
    agr = n = 0
    for dt in dates:
        w = pd.concat([f, c], axis=1, keys=["f", "c"], sort=True).loc[
            dt - pd.Timedelta(days=WINDOW_DAYS): dt + pd.Timedelta(days=WINDOW_DAYS)].dropna()
        agr += int((np.abs(w["f"] - w["c"]) < MATCH_TOL).sum()); n += len(w)
    return agr / n if n >= MIN_DAYS else np.nan


def pick(scores: dict):
    """(permno, source) from {permno: share}: exactly one >= MATCH_SHARE -> it; else unresolved."""
    good = [p for p, v in scores.items() if pd.notna(v) and v >= MATCH_SHARE]
    if len(good) == 1:
        return good[0], "returns"
    if len(good) > 1:
        return np.nan, "unresolved_multiple"
    return np.nan, ("unresolved_none" if any(pd.notna(v) for v in scores.values()) else "unresolved_untestable")


def resolve_input():
    r = pd.read_parquet(OUT)
    r = r[r["status"] != "self"]
    agree = r["permno"].notna() & r["permno_label_map"].notna() & (r["permno"] == r["permno_label_map"])
    rows = []
    for x in r[~agree].itertuples():
        cands = sorted({int(p) for p in (x.permno, x.permno_label_map, x.permno_symbol_map) if pd.notna(p)})
        if not cands:
            continue
        d = pd.read_parquet(os.path.join(_W, f"{x.label}_1D.parquet"), columns=["close"]).dropna()
        d.index = pd.to_datetime(d.index)
        if len(d) < 20:
            continue
        for p in cands:
            for q in (0.15, 0.5, 0.85):
                rows.append({"label": x.label, "permno": p, "date": d.index[int((len(d) - 1) * q)]})
    pd.DataFrame(rows).to_parquet(RESOLVE_INPUT)
    print(f"{len(rows)} candidate-date rows for {len({r['label'] for r in rows})} labels -> {RESOLVE_INPUT}")


def finalize():
    c = pd.read_parquet(OUT)
    inp = pd.read_parquet(RESOLVE_INPUT)
    px = pd.read_parquet(RESOLVE_RETURNS); px["date"] = pd.to_datetime(px["date"])
    by = {p: g.groupby("date")["ret"].last().astype(float) for p, g in px.groupby("permno")}
    resolved = {}
    for lab, g in inp.groupby("label"):
        d = pd.read_parquet(os.path.join(_W, f"{lab}_1D.parquet"), columns=["close"]); d.index = pd.to_datetime(d.index)
        f = d["close"].astype(float).abs().pct_change()
        sc = {int(p): (return_match_share(f, by[p], gp["date"]) if p in by else np.nan) for p, gp in g.groupby("permno")}
        resolved[lab] = pick(sc) + (str({k: (round(v, 3) if pd.notna(v) else None) for k, v in sc.items()}),)
    rows = []
    for x in c.itertuples():
        if x.status == "self":
            rows.append((x.label, int(x.permno), "self", ""))
        elif pd.notna(x.permno) and pd.notna(x.permno_label_map) and x.permno == x.permno_label_map:
            rows.append((x.label, int(x.permno), "agree", ""))
        elif x.label in resolved:
            p, src, sc = resolved[x.label]
            rows.append((x.label, p, src, sc))
        else:
            rows.append((x.label, np.nan, "unresolved_untestable", ""))
    F = pd.DataFrame(rows, columns=["label", "permno", "source", "return_scores"])
    F.to_parquet(FINAL)
    print(F["source"].value_counts().to_string()); print(f"-> {FINAL}")


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "identify"
    if step == "resolve":
        return resolve_input()
    if step == "finalize":
        return finalize()
    names = pd.read_parquet(os.path.join(_W, "crsp_stocknames_all.parquet"))
    for c in ("namedt", "nameenddt"):
        names[c] = pd.to_datetime(names[c])
    names_end = names["nameenddt"].max()
    spans = file_spans()
    print(f"{len(spans):,} CRSP-labelled files; names table ends {names_end.date()}")
    res = identify(spans, names, names_end=names_end, data_end=spans["last"].max())
    lm = pd.read_parquet(os.path.join(_W, "full_us_market_label_map.parquet"))
    sm = pd.read_parquet(os.path.join(_W, "symbol_permno_map.parquet"))
    res["permno_label_map"] = res["label"].map(dict(zip(lm["label"], lm["permno"])))
    res["permno_symbol_map"] = res["label"].map(dict(zip(sm["symbol"], sm["permno"])))
    res.to_parquet(OUT)
    print(res["status"].value_counts().to_string())
    idf = res[res["status"].isin(["identified", "self"])]
    for col in ("permno_label_map", "permno_symbol_map"):
        has = idf[idf[col].notna()]
        bad = has[has[col].astype(int) != has["permno"].astype(int)]
        print(f"{col}: {len(has):,} identified labels mapped; {len(bad):,} point at a DIFFERENT security")
    print(f"-> {OUT}")


if __name__ == "__main__":
    main()
