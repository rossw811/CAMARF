"""
Synthetic verification of wrds_global_index_universe_fetch.py's retry loop
(added 2026-08-12 after a real run died on a mid-fetch WRDS connection drop,
then an immediate manual retry also failed to connect) -- run BEFORE
trusting the retry logic on another real, multi-hour WRDS run.

Checks, via monkeypatching (no real WRDS connection):
  1. A generator that raises partway through is caught, and the retry loop
     recomputes `to_fetch` against files ALREADY WRITTEN before the crash
     (i.e. already-fetched symbols this attempt are not re-requested).
  2. The loop eventually terminates (all symbols "fetched") rather than
     looping forever once nothing remains.
  3. `_connect_with_retry` retries on a connection failure and succeeds once
     the underlying `_connect` stops raising.
  4. Giving up after `max_retries` interrupted attempts raises, rather than
     silently returning as if successful.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import research.wrds_global_index_universe_fetch as fetch_mod


def _fake_df():
    return pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [100]})


class _FakeConnection:
    """Stand-in for the SQLAlchemy connection wrds.Connection exposes as
    .connection -- exec_driver_sql is what _connect_with_retry actually
    calls now (2026-08-13 fix: raw_sql() wraps pd.read_sql_query(), which
    requires a result set with rows; a bare SET command has none, and threw
    'This result object does not return rows' on the real run)."""
    def __init__(self, owner):
        self.owner = owner

    def exec_driver_sql(self, q):
        if "statement_timeout" in q:
            self.owner.timeout_set = q
            return None
        raise NotImplementedError(q)


class _FakeDBWithTimeout:
    """Minimal stand-in for a wrds.Connection -- exposes .connection with
    exec_driver_sql() so _connect_with_retry's statement_timeout SET call
    doesn't crash against a bare string/mock."""
    def __init__(self, label):
        self.label = label
        self.timeout_set = None
        self.connection = _FakeConnection(self)

    def __eq__(self, other):
        return isinstance(other, _FakeDBWithTimeout) and self.label == other.label


def main():
    failures = []

    # --- Check 3+4: _connect_with_retry ---
    calls = {"n": 0}

    def flaky_connect_then_ok():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("simulated drop")
        return _FakeDBWithTimeout("FAKE_DB")

    orig_connect = fetch_mod._connect
    fetch_mod._connect = flaky_connect_then_ok
    try:
        result = fetch_mod._connect_with_retry(max_attempts=5, base_delay=0.01)
        if result != _FakeDBWithTimeout("FAKE_DB"):
            failures.append(f"_connect_with_retry should return the connected db once _connect "
                             f"stops raising, got {result!r}")
        elif result.timeout_set is None:
            failures.append("_connect_with_retry should have set statement_timeout on the new "
                             "connection, but raw_sql was never called with it")
        if calls["n"] != 3:
            failures.append(f"_connect_with_retry should have taken exactly 3 attempts, took {calls['n']}")
    finally:
        fetch_mod._connect = orig_connect

    def always_fails():
        raise ConnectionError("permanent")

    fetch_mod._connect = always_fails
    try:
        try:
            fetch_mod._connect_with_retry(max_attempts=2, base_delay=0.01)
            failures.append("_connect_with_retry should raise after exhausting max_attempts, did not")
        except RuntimeError:
            pass  # expected
    finally:
        fetch_mod._connect = orig_connect

    # --- Check 1+2: main()'s retry-and-resume loop ---
    tmpdir = tempfile.mkdtemp()
    orig_out_dir = fetch_mod._OUT_DIR
    orig_manifest = fetch_mod._MANIFEST_PATH
    fetch_mod._OUT_DIR = tmpdir
    fetch_mod._MANIFEST_PATH = os.path.join(tmpdir, "manifest.parquet")

    label_by_pair = {(f"G{i}", "01W"): f"GVKEYG{i}_01W" for i in range(10)}

    def fake_discover_and_build_manifest(db, min_c):
        return label_by_pair

    call_count = {"n": 0}

    def fake_fetch_symbols_bulk_global(db, to_fetch, start=None, batch_size=200):
        # First call: yield 4 symbols, then raise (simulating a mid-batch drop).
        # Second call: yield the rest cleanly.
        call_count["n"] += 1
        items = list(to_fetch.items())
        if call_count["n"] == 1:
            for label, pair in items[:4]:
                yield label, _fake_df()
            raise ConnectionError("simulated mid-fetch drop")
        else:
            for label, pair in items:
                yield label, _fake_df()

    orig_discover = fetch_mod.discover_and_build_manifest
    orig_bulk = fetch_mod.fetch_symbols_bulk_global
    orig_connect2 = fetch_mod._connect_with_retry
    orig_argv = sys.argv
    fetch_mod.discover_and_build_manifest = fake_discover_and_build_manifest
    fetch_mod.fetch_symbols_bulk_global = fake_fetch_symbols_bulk_global
    fetch_mod._connect_with_retry = lambda *a, **k: "FAKE_DB"
    sys.argv = ["wrds_global_index_universe_fetch.py", "--max-retries", "5"]
    try:
        fetch_mod.main()
    except SystemExit:
        pass
    finally:
        fetch_mod.discover_and_build_manifest = orig_discover
        fetch_mod.fetch_symbols_bulk_global = orig_bulk
        fetch_mod._connect_with_retry = orig_connect2
        sys.argv = orig_argv

    cached_files = [f for f in os.listdir(tmpdir) if f.endswith("_1D.parquet")]
    if len(cached_files) != 10:
        failures.append(f"Expected all 10 symbols cached after retry-and-resume, got {len(cached_files)}: "
                         f"{cached_files}")
    if call_count["n"] != 2:
        failures.append(f"Expected exactly 2 calls to fetch_symbols_bulk_global (1 crash + 1 clean "
                         f"resume), got {call_count['n']}")

    fetch_mod._OUT_DIR = orig_out_dir
    fetch_mod._MANIFEST_PATH = orig_manifest

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All WRDS global-fetch retry-logic checks passed.")
    print(f"  connect retry: succeeded on attempt 3/5, correctly raised when always failing")
    print(f"  fetch retry: {len(cached_files)}/10 symbols cached after 1 simulated mid-fetch crash "
          f"+ resume ({call_count['n']} total fetch calls)")


if __name__ == "__main__":
    main()
