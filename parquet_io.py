"""Parquet reads for the whole project: pd.read_parquet with the path handed to Arrow's own local file system.

Why (2026-11-02, gdb backtraces from CI run 41577379785): for a local path with no `filesystem=`, pandas opens a
Python file object and passes it to Arrow (pandas.io.parquet._get_path_or_handle). Arrow's read-ahead keeps
references to it in its thread pool. When a late callback drops the last one while the interpreter is finalizing,
the destructor (arrow::py::PyReadableFile / PyBuffer) asks for the GIL, CPython ends that thread with pthread_exit,
the forced unwind crosses a noexcept destructor and std::terminate aborts the process (rc -6) -- after the script's
work is done. With `filesystem=LocalFileSystem` pandas passes the path string through and Arrow opens the file
natively, so no Python object is involved. Same pandas reader (read_table -> to_pandas), same result.

Anything that is not a plain local path (a buffer, a URL, an explicit filesystem/engine) goes to pd.read_parquet
unchanged. debug/_verify_parquet_io.py
"""
import os

import pandas as pd
import pyarrow.fs as pafs

_LOCAL = pafs.LocalFileSystem()


def read_parquet(path, *args, **kwargs) -> pd.DataFrame:
    """pd.read_parquet(path, ...) -- same arguments, same result; local paths are opened by Arrow, not Python."""
    if (isinstance(path, (str, os.PathLike)) and "filesystem" not in kwargs
            and kwargs.get("engine", "auto") in ("auto", "pyarrow")):
        p = os.fspath(path)
        if isinstance(p, str) and "://" not in p:
            return pd.read_parquet(os.path.abspath(p), *args, filesystem=_LOCAL, **kwargs)
    return pd.read_parquet(path, *args, **kwargs)
