"""
parquet_io.read_parquet: local paths reach Arrow as a path (Arrow opens the file), never as a Python file object.

Cause it fixes (2026-11-02, gdb backtraces from CI run 41577379785, Development.md): pandas wraps a local path in a
Python file object; a late Arrow thread-pool callback releasing it during interpreter finalization aborts the process
(rc -6, "terminate called without an active exception") after every check has passed.
Checks:
  1. production read path (data.DataStore.load) hands pyarrow.parquet.read_table a str + LocalFileSystem -- fails on
     the old code (a Python file object), passes on the new;
  2. same frames as pd.read_parquet: tz-aware DatetimeIndex, columns=, filters=, directory dataset, relative path,
     pathlib.Path; a buffer passes through unchanged; a missing file raises FileNotFoundError either way;
  3. ratchet: no `pd.read_parquet(` call left in tracked .py code outside parquet_io.py (token scan, so strings and
     comments do not count).
Run: python debug/_verify_parquet_io.py
"""
import io
import os
import pathlib
import subprocess
import sys
import tempfile
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd
import pyarrow.fs as pafs
import pyarrow.parquet as pq

import parquet_io
from config import Config

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def _sources_seen(fn):
    """Run fn() and return what pandas passed to pyarrow.parquet.read_table: (type of source, filesystem type)."""
    seen, real = [], pq.read_table

    def spy(source, *a, **k):
        seen.append((type(source).__name__, type(k.get("filesystem")).__name__))
        return real(source, *a, **k)
    pq.read_table = spy
    try:
        fn()
    finally:
        pq.read_table = real
    return seen


def pd_calls_outside_helper():
    files = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    hits = []
    for f in files:
        if f in ("parquet_io.py", "debug/_verify_parquet_io.py") or "archive" in f:   # this file: pd = the reference
            continue
        with open(os.path.join(ROOT, f), "rb") as fh:
            try:
                toks = [t for t in tokenize.tokenize(fh.readline) if t.type not in (tokenize.NL, tokenize.COMMENT)]
            except (tokenize.TokenError, SyntaxError):
                continue
        for i in range(len(toks) - 3):
            if (toks[i].string, toks[i + 1].string, toks[i + 2].string, toks[i + 3].string) == ("pd", ".", "read_parquet", "("):
                hits.append(f"{f}:{toks[i].start[0]}")
    return hits


def main():
    idx = pd.date_range("2020-01-01", periods=50, freq="D", tz="America/New_York", name="timestamp")
    df = pd.DataFrame({"close": np.linspace(1, 2, 50), "volume": np.arange(50, dtype="int64"),
                       "sym": ["A", "B"] * 25}, index=idx)
    with tempfile.TemporaryDirectory() as td:
        # 1. production read path
        old = Config.DATA.CACHE_DIR
        Config.DATA.CACHE_DIR = td
        try:
            import data
            path = data.DataStore._path("ZZTEST", "1D")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            df.to_parquet(path)
            seen = _sources_seen(lambda: data.DataStore.load("ZZTEST", "1D"))
        finally:
            Config.DATA.CACHE_DIR = old
        check("datastore_load_hands_arrow_a_path", seen == [("str", "LocalFileSystem")], seen)

        # 2. same frames
        p = os.path.join(td, "f.parquet")
        df.to_parquet(p)
        check("same_frame_tz_index", parquet_io.read_parquet(p).equals(pd.read_parquet(p))
              and str(parquet_io.read_parquet(p).index.tz) == "America/New_York")
        check("same_columns_subset", parquet_io.read_parquet(p, columns=["close"]).equals(pd.read_parquet(p, columns=["close"])))
        f = [("sym", "==", "A")]
        check("same_filters", parquet_io.read_parquet(p, filters=f).equals(pd.read_parquet(p, filters=f)))
        d = os.path.join(td, "ds")
        df.reset_index().to_parquet(d, partition_cols=["sym"])
        a, b = parquet_io.read_parquet(d), pd.read_parquet(d)
        check("same_directory_dataset", a.sort_values("timestamp").reset_index(drop=True)
              .equals(b.sort_values("timestamp").reset_index(drop=True)), a.shape)
        cwd = os.getcwd()
        os.chdir(td)
        try:
            check("relative_path", parquet_io.read_parquet("f.parquet").equals(df))
        finally:
            os.chdir(cwd)
        check("pathlib_path", parquet_io.read_parquet(pathlib.Path(p)).equals(df))
        buf = io.BytesIO(open(p, "rb").read())
        check("buffer_passthrough", parquet_io.read_parquet(buf).equals(df))
        errs = []
        for fn in (pd.read_parquet, parquet_io.read_parquet):
            try:
                fn(os.path.join(td, "missing.parquet"))
                errs.append(None)
            except FileNotFoundError:
                errs.append("FileNotFoundError")
            except Exception as e:   # noqa: BLE001
                errs.append(type(e).__name__)
        check("missing_file_same_error", errs == ["FileNotFoundError", "FileNotFoundError"], errs)
        check("helper_uses_local_fs", isinstance(parquet_io._LOCAL, pafs.LocalFileSystem))

    # 3. ratchet
    hits = pd_calls_outside_helper()
    check("no_pd_read_parquet_outside_helper", not hits, hits[:5])

    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
