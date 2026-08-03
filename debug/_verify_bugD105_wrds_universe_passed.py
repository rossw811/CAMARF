"""
Synthetic verification for BUG-D105: UniverseBuilder.build()'s WRDS-primary
routing (data.py, 2026-08-01 addition) removed WRDS-covered symbols from
`yf_assets` (so they wouldn't be redundantly re-fetched from yfinance), but
the ONLY place that added symbols to the final `passed` list read from that
same mutated `yf_assets` -- so every WRDS-sourced symbol silently never
became "passed". Confirmed directly via a real run (2026-08-02):
"Universe complete: 148 assets passed" instead of the ~1650+ expected, with
0 confirmed pairs at every timeframe including 2m/3m (previously KVUE/KMB).

This mirrors data.py::UniverseBuilder.build()'s exact passed-list
construction sequence at small scale (the logic is inline in a ~1200-line
method, not a standalone importable function, so it's reproduced here --
same "duplicated to match a closure" precedent as
debug/_verify_wrds_primary_wiring.py) rather than mocking the full method.
Real-data integration confirmation (does the actual fixed data.py code
produce the expected universe size) happens via a real analysis.py run,
tracked separately -- this test proves the MECHANISM is fixed.
"""


def _passed_list_pre_fix(yf_assets, wrds_daily_done, yf_daily_done):
    """Pre-fix behavior: passed only ever populated from yf_assets, which
    has already had WRDS symbols removed."""
    passed = []
    passed_symbols = {s for s, _ in passed}
    for symbol, asset_class in yf_assets:
        if symbol in yf_daily_done and symbol not in passed_symbols:
            passed.append((symbol, asset_class))
    return passed


def _passed_list_post_fix(yf_assets, wrds_daily_done, yf_daily_done):
    """Post-fix behavior: adds the yf_assets loop's results, THEN
    explicitly adds every wrds_daily_done symbol not already present --
    matches the actual data.py:5007-5024 fix exactly."""
    passed = []
    passed_symbols = {s for s, _ in passed}
    for symbol, asset_class in yf_assets:
        if symbol in yf_daily_done and symbol not in passed_symbols:
            passed.append((symbol, asset_class))

    passed_symbols = {s for s, _ in passed}
    for symbol, asset_class in wrds_daily_done.items():
        if symbol not in passed_symbols:
            passed.append((symbol, asset_class))
    return passed


def main():
    failures = []

    # Simulate: 5 equity symbols total. AAPL/MSFT/JPM are WRDS-covered
    # (removed from yf_assets, per the real WRDS branch's own filtering).
    # GME/AMC have no WRDS coverage and go through the normal yfinance path.
    wrds_daily_done = {"AAPL": "equity", "MSFT": "equity", "JPM": "equity"}
    yf_assets = [("GME", "equity"), ("AMC", "equity")]  # WRDS symbols already removed, matching data.py:4095
    yf_daily_done = set(wrds_daily_done) | {"GME", "AMC"}  # all 5 confirmed to have daily data

    pre = _passed_list_pre_fix(yf_assets, wrds_daily_done, yf_daily_done)
    post = _passed_list_post_fix(yf_assets, wrds_daily_done, yf_daily_done)

    pre_symbols = {s for s, _ in pre}
    post_symbols = {s for s, _ in post}

    print(f"pre-fix passed:  {sorted(pre_symbols)}")
    print(f"post-fix passed: {sorted(post_symbols)}")

    # The bug: pre-fix drops all 3 WRDS symbols despite having confirmed
    # daily data for them.
    if {"AAPL", "MSFT", "JPM"} & pre_symbols:
        failures.append(
            "pre-fix simulation unexpectedly included WRDS symbols in passed "
            "-- this test no longer reproduces BUG-D105, review it"
        )
    if pre_symbols != {"GME", "AMC"}:
        failures.append(f"pre-fix simulation expected exactly {{GME, AMC}}, got {pre_symbols}")

    # The fix: all 5 symbols (2 yfinance + 3 WRDS) end up passed.
    expected_post = {"AAPL", "MSFT", "JPM", "GME", "AMC"}
    if post_symbols != expected_post:
        failures.append(f"post-fix simulation expected {expected_post}, got {post_symbols}")

    # No duplicates introduced (a symbol already in `passed` from the
    # yf_assets loop should not be double-appended by the wrds loop).
    if len(post) != len(post_symbols):
        failures.append(f"post-fix produced duplicate entries: {post}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)

    print("\nBUG-D105 fix verified: WRDS-sourced symbols now reach `passed` "
          "without duplicating yfinance-sourced ones.")


if __name__ == "__main__":
    main()
