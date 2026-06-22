# =============================================================================
# CAMARF — Cross-Asset Co-Movement Arbitrage Research Framework
# macro.py — FRED macro regime context
# github.com/rossw811/CAMARF
#
# Fetches macro series from FRED's public, keyless CSV endpoint, aligns them
# to the NYSE trading calendar, and classifies them into daily regime labels
# (yield curve, credit, volatility, recession) — Level-3 context features
# for the not-yet-built ml.py meta-labeler and analyzer.py.
#
# Same role as data.py: this module fetches and caches. It has no consumers
# today, so the only contract that matters is the flat-import surface a
# future ml.py will use: `from macro import build, MacroResult, ...`,
# mirroring `from data import UniverseBuilder, UniverseResult, ...`.
# =============================================================================

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests

from config import Config
from data import DataAligner, DataStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("CAMARF.macro")

# FRED series ID -> friendly output column name for the raw/diagnostic value.
_RAW_COLUMN_NAMES: Dict[str, str] = {
    "T10Y2Y": "t10y2y",
    "BAMLH0A0HYM2": "hy_oas_spread_pct",
    "VIXCLS": "vix_close",
    "DCOILWTICO": "wti_crude",
    "BAA10Y": "baa10y_spread_pct",  # full-history credit-stress PROXY — see
    # MacroConfig comment; not the same metric as hy_oas_spread_pct
    "DTWEXBGS": "usd_index",
    "DFII10": "real_yield_10y",
    "T10YIE": "breakeven_inflation_10y",
    "FEDFUNDS": "fed_funds_rate",
    "CPIAUCSL": "cpi",
    "USREC": "recession_flag",  # raw 0/1 — replaced by recession_state below,
    # never exposed directly (regimes are the primary output, not binaries)
    "UNRATE": "unemployment_rate",  # feeds the derived sahm_indicator in build()
}


# =============================================================================
# DATACLASSES
# =============================================================================


@dataclass
class MacroResult:
    """
    Output of build(). A single wide DataFrame indexed by NYSE trading date —
    one row per session, columns are regime labels + raw series + staleness
    indicators. Mirrors UniverseResult's role as the typed return wrapper
    consumers import and pass around.
    """

    data: pd.DataFrame
    series_fetched: List[str]
    series_failed: List[str]
    start_date: str
    end_date: str


# =============================================================================
# CLASS 1 — FREDFeed
# =============================================================================


class FREDFeed:
    """
    Fetches macro series from FRED's public, keyless CSV endpoint
    (fredgraph.csv — confirmed via live probe on 2026-06-21 to need no API
    key/account). Mirrors CBOEFeed in data.py: raw `requests`-based fetch,
    in-memory session cache, disk cache via DataStore under a synthetic
    "fred_{series_id}" key — plus a freshness check via DataStore.is_fresh()
    (CBOEFeed has none, which is fine for a static options snapshot but
    wrong for a daily-updating macro series).
    """

    _SESSION_CACHE: Dict[str, Optional[pd.DataFrame]] = {}

    @staticmethod
    def get_series(
        series_id: str,
        force_refresh: bool = False,
        summary: Optional["MacroRunSummary"] = None,
    ) -> Optional[pd.DataFrame]:
        cache_key = f"fred_{series_id}"

        if not force_refresh and series_id in FREDFeed._SESSION_CACHE:
            return FREDFeed._SESSION_CACHE[series_id]

        cached = DataStore.load(cache_key, "daily")

        if not force_refresh and DataStore.is_fresh(
            cache_key, "daily", max_age_hours=Config.MACRO.CACHE_MAX_AGE_HOURS
        ):
            if summary:
                summary.record_series(
                    series_id,
                    rows=len(cached) if cached is not None else 0,
                    source="cache",
                )
            FREDFeed._SESSION_CACHE[series_id] = cached
            return cached

        fresh = FREDFeed._fetch_with_retry(series_id, summary)

        # Never let an empty/failed fetch overwrite a good cache — mirrors
        # data.py's _fetch_constituents_cached rule: a stale-but-complete
        # series is far more useful than a fresh-but-empty one.
        if fresh is None or fresh.empty:
            if summary:
                summary.warn(
                    f"{series_id}_fetch_failed_used_cache"
                    if cached is not None
                    else f"{series_id}_fetch_failed_no_cache"
                )
            result = cached
        else:
            DataStore.save(cache_key, "daily", fresh)
            result = fresh
            if summary:
                summary.record_series(series_id, rows=len(fresh), source="fred")

        FREDFeed._SESSION_CACHE[series_id] = result
        return result

    @staticmethod
    def _fetch_with_retry(
        series_id: str, summary: Optional["MacroRunSummary"] = None
    ) -> Optional[pd.DataFrame]:
        url = Config.MACRO.FRED_CSV_URL.format(series_id=series_id)
        for attempt in range(Config.MACRO.FETCH_RETRY_ATTEMPTS):
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code != 200:
                    time.sleep(Config.MACRO.FETCH_RETRY_DELAY_SEC)
                    continue
                df = pd.read_csv(StringIO(resp.text))
                if df.empty or df.shape[1] < 2:
                    if summary:
                        summary.warn(f"{series_id}_empty_result")
                    return None
                date_col, value_col = df.columns[0], df.columns[1]
                # FRED's CSV represents missing observations as a blank
                # field (pandas already reads these as NaN); some older
                # FRED API surfaces have used a literal "." for the same
                # purpose — handled defensively here too.
                df[value_col] = pd.to_numeric(
                    df[value_col].replace(".", np.nan), errors="coerce"
                )
                df[date_col] = pd.to_datetime(df[date_col])
                df = df.set_index(date_col).rename(columns={value_col: series_id})
                df.index.name = "date"
                return df[[series_id]]
            except (requests.RequestException, pd.errors.ParserError, ValueError) as e:
                # ParserError/ValueError: FRED returning a malformed/non-CSV
                # body with HTTP 200 (e.g. a maintenance page) — same
                # failure tolerance as a network error, not an unhandled
                # crash of the whole run.
                if summary:
                    summary.warn(f"{series_id}_network_error")
                log.debug(f"FRED fetch error ({series_id}, attempt {attempt+1}): {e}")
                time.sleep(Config.MACRO.FETCH_RETRY_DELAY_SEC)
        return None


# =============================================================================
# REGIME CLASSIFICATION — pure functions (mirrors _gap_aware_returns /
# _clean_close's convention: stateless transforms as plain functions, not
# class methods)
# =============================================================================


def _bucket(series: pd.Series, edges: List[float], labels: List[str]) -> pd.Series:
    """
    Shared threshold-bucketing helper for the pd.cut-based classifiers below.

    Uses right=False (left-closed/right-open bins: [edge_i, edge_i+1)) for
    all of them. This means a value exactly AT an edge falls into the
    bucket ABOVE it, not below — e.g. with edges=[0, 1.5], a T10Y2Y of
    exactly 1.5 is "steep", not "normal". The original spec's wording
    ("steep (>1.5)") suggests the opposite convention at that specific edge;
    pd.cut can't apply a different inclusivity per-edge in one call, and
    real FRED floats essentially never land exactly on a threshold, so this
    is documented here rather than engineered around.
    """
    return pd.cut(series, bins=[-np.inf, *edges, np.inf], labels=labels, right=False).astype(
        object
    )


def _classify_yield_curve(t10y2y: pd.Series) -> pd.Series:
    """flat_inverted (<0) / normal ([0,1.5)) / steep (>=1.5) — see _bucket()."""
    c = Config.MACRO
    return _bucket(
        t10y2y,
        [c.YIELD_CURVE_INVERTED, c.YIELD_CURVE_STEEP],
        ["flat_inverted", "normal", "steep"],
    )


def _classify_credit(spread_pct: pd.Series) -> pd.Series:
    """tight (<3.0%) / normal ([3.0,5.0)%) / wide (>=5.0%) — see _bucket()."""
    c = Config.MACRO
    return _bucket(
        spread_pct,
        [c.CREDIT_TIGHT_PCT, c.CREDIT_WIDE_PCT],
        ["tight", "normal", "wide"],
    )


def _classify_credit_proxy(baa10y_spread_pct: pd.Series) -> pd.Series:
    """
    tight (<2.0%) / normal ([2.0,3.0)%) / wide (>=3.0%) — see _bucket().

    PROXY, not a substitute for credit_regime: BAA10Y (Moody's Baa
    corporate yield minus 10Y Treasury) is a different instrument than
    BAMLH0A0HYM2 (high-yield option-adjusted spread) with a different scale
    and different sensitivity — it exists solely to extend credit-stress
    coverage back to 1986, where credit_regime only has ~3 years (FRED's
    keyless endpoint caps BAMLH0A0HYM2 specifically). Thresholds are
    independently calibrated against BAA10Y's own history
    (MacroConfig.CREDIT_PROXY_TIGHT_PCT/WIDE_PCT), not derived from
    credit_regime's thresholds. Do not compare the two columns' values
    directly or treat them as the same regime taxonomy.
    """
    c = Config.MACRO
    return _bucket(
        baa10y_spread_pct,
        [c.CREDIT_PROXY_TIGHT_PCT, c.CREDIT_PROXY_WIDE_PCT],
        ["tight", "normal", "wide"],
    )


def _classify_vix(vix: pd.Series) -> pd.Series:
    """calm (<15) / normal ([15,25)) / elevated ([25,35)) / crisis (>=35)."""
    c = Config.MACRO
    return _bucket(
        vix,
        [c.VIX_CALM, c.VIX_NORMAL_HI, c.VIX_ELEVATED_HI],
        ["calm", "normal", "elevated", "crisis"],
    )


def _classify_recession(usrec: pd.Series) -> pd.Series:
    """
    NBER USREC binary -> regime label. Raw 0/1 is never exposed directly.

    Known bias (document, don't silently correct away): NBER's recession
    dating committee announces calls 6-18 months after the fact, and FRED
    backdates USREC to the actual recession month once announced. A recent
    date showing "expansion" may later be retroactively revised to
    "contraction" once NBER actually calls it — do not treat recession_state
    for the last ~18 months as ground truth.
    """
    return usrec.map({0: "expansion", 1: "contraction"}).astype(object)


def _classify_recession_realtime(sahm_indicator: pd.Series) -> pd.Series:
    """
    Sahm Rule: "contraction_risk" when the 3-month average unemployment
    rate has risen >= SAHM_TRIGGER (0.50pp) above its trailing-12-month
    low; "expansion" otherwise. NaN until ~14 months of UNRATE history
    exist (3mo MA + 12mo min of that MA both need to fill).

    NOT the same signal as recession_state (USREC/NBER): this is a
    real-time, momentum-based heuristic with a strong historical hit rate
    but no deliberative confirmation behind it; recession_state is the
    eventual, deliberated ground truth but lags 6-18 months. Use this one
    for "what would a live strategy actually have known at the time" —
    e.g. the WFA emulation test — and recession_state for in-sample
    historical/backtest analysis where the eventual NBER call is fair game.
    """
    c = Config.MACRO
    triggered = sahm_indicator >= c.SAHM_TRIGGER
    label = triggered.map({True: "contraction_risk", False: "expansion"}).astype(object)
    return label.where(sahm_indicator.notna())


def _classify_relative_level(
    series: pd.Series,
    low_pctile: float,
    high_pctile: float,
    labels: List[str],
) -> pd.Series:
    """
    Rolling-percentile regime classifier (window/min_periods from
    MacroConfig.RELATIVE_LEVEL_*) for series whose "normal" level drifts
    structurally over a multi-year horizon — dollar index, real yields,
    breakeven inflation. An absolute-level threshold (like VIX's 15/25/35)
    would misclassify across different multi-year eras (e.g. real yields
    near 0% through the post-2008 ZIRP/QE era vs. ~2% now are not
    comparable on an absolute scale the way VIX's vol-based levels are).
    NaN until RELATIVE_LEVEL_MIN_PERIODS trailing observations exist.
    """
    c = Config.MACRO
    pctile = series.rolling(
        c.RELATIVE_LEVEL_WINDOW, min_periods=c.RELATIVE_LEVEL_MIN_PERIODS
    ).rank(pct=True)
    return pd.cut(
        pctile, bins=[-np.inf, low_pctile, high_pctile, np.inf], labels=labels, right=False
    ).astype(object)


def _classify_dollar(usd_index: pd.Series) -> pd.Series:
    """weak (<25th pctile) / neutral / strong (>=75th pctile), trailing ~2yr."""
    c = Config.MACRO
    return _classify_relative_level(
        usd_index,
        c.RELATIVE_LEVEL_LOW_PCTILE,
        c.RELATIVE_LEVEL_HIGH_PCTILE,
        ["weak", "neutral", "strong"],
    )


def _classify_real_rate(real_yield_10y: pd.Series) -> pd.Series:
    """low / normal / high real yield, relative to trailing ~2yr — see _classify_relative_level."""
    c = Config.MACRO
    return _classify_relative_level(
        real_yield_10y,
        c.RELATIVE_LEVEL_LOW_PCTILE,
        c.RELATIVE_LEVEL_HIGH_PCTILE,
        ["low", "normal", "high"],
    )


def _classify_breakeven(breakeven_inflation_10y: pd.Series) -> pd.Series:
    """low / normal / high inflation expectations, relative to trailing ~2yr — see _classify_relative_level."""
    c = Config.MACRO
    return _classify_relative_level(
        breakeven_inflation_10y,
        c.RELATIVE_LEVEL_LOW_PCTILE,
        c.RELATIVE_LEVEL_HIGH_PCTILE,
        ["low", "normal", "high"],
    )


# =============================================================================
# CALENDAR ALIGNMENT — genuinely new ground for this codebase: no existing
# coarse-to-fine (monthly -> daily) forward-fill utility to reuse. The
# fine-to-coarse direction (YFinanceFeed._resample_from_daily) solves the
# opposite problem and isn't applicable here.
# =============================================================================


def _stale_days(reindexed: pd.Series) -> pd.Series:
    """
    Trading days since `reindexed` last changed value (0 on the day it
    changed). NaN wherever the underlying value is itself still NaN (e.g.
    before the series' own history begins) — staleness is meaningless
    there, not zero.
    """
    changed = reindexed.ne(reindexed.shift(1)) & reindexed.notna()
    group = changed.cumsum()
    stale = reindexed.groupby(group).cumcount()
    return stale.where(reindexed.notna())


def _align_to_trading_calendar(
    daily_native: Dict[str, pd.Series],
    monthly_native: Dict[str, pd.Series],
    master_idx: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Reindex FRED series (mixed native release frequency) onto the shared
    NYSE trading-date index (DataAligner._get_nyse_calendar — reused
    directly rather than reinventing calendar logic).

    Daily-native series get forward-filled — FRED's own holiday/missing-print
    gaps, the same FILL-style treatment DataAligner gives <=5-bar gaps.

    Monthly-native series get the same forward-fill, plus a
    `{name}_days_stale` column. This is intentionally NOT GapFlag.DATA_GAP:
    a monthly print held flat for ~21 trading days is expected/structural
    (the publication cadence itself), not an unexpected provider gap —
    conflating the two would violate the project's "never silently treat
    expected staleness as a real gap" principle.

    Uses reindex(..., method="ffill") rather than plain reindex().ffill().
    The two are NOT equivalent here: monthly series are stamped on the 1st
    of the month, which is frequently a non-trading day (holiday/weekend)
    absent from master_idx entirely. A plain reindex only copies a value
    into the output where the ORIGINAL index has an exact-date match against
    master_idx — if a given month's 1st isn't a trading day, that month's
    value is silently dropped rather than forward-filled, and the prior
    month's value keeps propagating until some LATER month-start happens to
    land on a trading day. reindex(method="ffill") instead looks up, for
    every master_idx date, the nearest preceding date in the series' own
    (sorted) native index — correct regardless of whether that native date
    is itself a trading day. Verified: without this, FEDFUNDS (native data
    since 1954) showed NaN for all of January 1990 (Jan 1 1990 was a
    holiday) despite 36 years of real prior history, and cpi_days_stale
    spiked to 103 (a skipped release silently extending the previous
    month's "current" value) instead of resetting near each ~21-trading-day
    BLS release cadence.
    """
    out = pd.DataFrame(index=master_idx)

    for name, s in daily_native.items():
        out[name] = s.sort_index().reindex(master_idx, method="ffill")

    for name, s in monthly_native.items():
        reindexed = s.sort_index().reindex(master_idx, method="ffill")
        out[name] = reindexed
        out[f"{name}_days_stale"] = _stale_days(reindexed)

    return out


# =============================================================================
# CLASS 2 — MacroRunSummary
# =============================================================================


class MacroRunSummary:
    """
    Accumulates key metrics during a macro.py run and writes a compact
    structured summary at completion — same role as data.py's RunSummary,
    written to latest_run_macro.log instead of latest_run_data.log.
    """

    _LOG_PATH = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "latest_run_macro.log"
    )

    def __init__(self):
        self.start_time = time.time()
        self.series: Dict[str, Dict] = {}
        self.regime_distributions: Dict[str, Dict] = {}
        self.errors: List[str] = []
        self.warnings: Dict[str, int] = {}

    def record_series(self, series_id: str, **kwargs) -> None:
        self.series.setdefault(series_id, {}).update(kwargs)

    def record_regime_distribution(self, name: str, counts: Dict) -> None:
        self.regime_distributions[name] = counts

    def error(self, msg: str) -> None:
        key = msg[:100]
        if key not in self.errors:
            self.errors.append(key)

    def warn(self, category: str) -> None:
        self.warnings[category] = self.warnings.get(category, 0) + 1

    def write(self) -> None:
        elapsed = (time.time() - self.start_time) / 60
        lines = [
            "=== CAMARF macro.py ===",
            f"date:        {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}",
            f"runtime_min: {elapsed:.1f}",
            "",
            "=== series ===",
        ]
        if self.series:
            # Fixed-format line per series — at most 7 FRED series with 2-3
            # diagnostic keys each, unlike RunSummary's dynamic union-of-keys
            # table (built for 13 timeframes with a growing diagnostic set);
            # that machinery would be solving a problem that doesn't exist
            # at this scale.
            for sid, s in self.series.items():
                rows = s.get("rows", "?")
                source = s.get("source", "?")
                lines.append(f"  {sid:<14} rows={rows:<6} source={source}")
        else:
            lines.append("  (none)")

        if self.regime_distributions:
            lines += ["", "=== regime_distributions ==="]
            for name, counts in self.regime_distributions.items():
                lines.append(f"{name}: {counts}")

        if self.warnings:
            lines += ["", "=== warnings (top 10) ==="]
            for cat, n in sorted(self.warnings.items(), key=lambda x: -x[1])[:10]:
                lines.append(f"  {n:>4}x  {cat}")

        if self.errors:
            lines += ["", "=== errors ==="]
            for e in self.errors:
                lines.append(f"  {e}")

        lines += ["", "=== end ==="]
        try:
            with open(self._LOG_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            log.info(f"Run summary → {self._LOG_PATH}")
        except Exception as e:
            log.debug(f"MacroRunSummary write failed: {e}")


# =============================================================================
# ENTRY POINT
# =============================================================================


def build(
    series: Optional[List[str]] = None,
    force_refresh: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> MacroResult:
    """
    Fetch all configured FRED series, align them to the NYSE trading
    calendar, and classify them into daily regime labels.

    Args:
        series:        Subset of FRED series IDs to fetch (from
                        Config.MACRO.FRED_SERIES_DAILY/MONTHLY), or None
                        for all configured series.
        force_refresh: Re-fetch from FRED even if the cache is fresh
                       (Config.MACRO.CACHE_MAX_AGE_HOURS).
        start_date:    Earliest date to align to (default:
                       Config.MACRO.MIN_HISTORY_START).
        end_date:      Latest date to align to (default: today).
    """
    summary = MacroRunSummary()
    start_date = start_date or Config.MACRO.MIN_HISTORY_START
    end_date = end_date or datetime.now().strftime("%Y-%m-%d")

    daily_ids = [s for s in Config.MACRO.FRED_SERIES_DAILY if series is None or s in series]
    monthly_ids = [
        s for s in Config.MACRO.FRED_SERIES_MONTHLY if series is None or s in series
    ]

    daily_raw: Dict[str, pd.Series] = {}
    monthly_raw: Dict[str, pd.Series] = {}
    series_fetched: List[str] = []
    series_failed: List[str] = []

    def _fetch_into(series_id: str, target: Dict[str, pd.Series]) -> None:
        df = FREDFeed.get_series(series_id, force_refresh=force_refresh, summary=summary)
        if df is None or df.empty:
            series_failed.append(series_id)
            log.warning(f"  {series_id}: no data available (fetch failed, no cache)")
            return
        series_fetched.append(series_id)
        target[_RAW_COLUMN_NAMES[series_id]] = df[series_id]

    for series_id in daily_ids:
        _fetch_into(series_id, daily_raw)
    for series_id in monthly_ids:
        _fetch_into(series_id, monthly_raw)

    if "unemployment_rate" in monthly_raw:
        # Derived series, computed on UNRATE's NATIVE monthly frequency —
        # not the daily-ffilled version, since the Sahm Rule's 3-month/
        # 12-month windows must operate in calendar-month terms (a 63/252
        # trading-day window on the ffilled series would drift against
        # actual months as trading-days-per-month varies 19-23). Injecting
        # it into monthly_raw lets it flow through the same
        # align+ffill+days_stale machinery as any other monthly series.
        u = monthly_raw["unemployment_rate"].sort_index()
        sahm_3mo_avg = u.rolling(3).mean()
        monthly_raw["sahm_indicator"] = sahm_3mo_avg - sahm_3mo_avg.rolling(12).min()

    if not daily_raw and not monthly_raw:
        # Loud guard, mirroring data.py's universe-size sanity check — never
        # silently return an empty macro context.
        log.error("!!! macro.py: ALL FRED series failed to fetch and no cache exists !!!")

    master_idx = DataAligner._get_nyse_calendar(start_date, end_date)
    wide = _align_to_trading_calendar(daily_raw, monthly_raw, master_idx)

    if "t10y2y" in wide:
        wide["yield_curve_regime"] = _classify_yield_curve(wide["t10y2y"])
    if "hy_oas_spread_pct" in wide:
        wide["credit_regime"] = _classify_credit(wide["hy_oas_spread_pct"])
    if "baa10y_spread_pct" in wide:
        wide["credit_regime_proxy"] = _classify_credit_proxy(wide["baa10y_spread_pct"])
    if "vix_close" in wide:
        wide["vix_regime"] = _classify_vix(wide["vix_close"])
    if "usd_index" in wide:
        wide["dollar_regime"] = _classify_dollar(wide["usd_index"])
    if "real_yield_10y" in wide:
        wide["real_rate_regime"] = _classify_real_rate(wide["real_yield_10y"])
    if "breakeven_inflation_10y" in wide:
        wide["inflation_expectation_regime"] = _classify_breakeven(
            wide["breakeven_inflation_10y"]
        )
    if "recession_flag" in wide:
        wide["recession_state"] = _classify_recession(wide["recession_flag"])
        if "recession_flag_days_stale" in wide:
            wide["recession_state_days_stale"] = wide["recession_flag_days_stale"]
        wide = wide.drop(
            columns=["recession_flag", "recession_flag_days_stale"], errors="ignore"
        )
    if "sahm_indicator" in wide:
        wide["recession_state_realtime"] = _classify_recession_realtime(
            wide["sahm_indicator"]
        )

    for regime_col, dist_name in [
        ("yield_curve_regime", "yield_curve"),
        ("credit_regime", "credit"),
        ("credit_regime_proxy", "credit_proxy"),
        ("vix_regime", "vix"),
        ("dollar_regime", "dollar"),
        ("real_rate_regime", "real_rate"),
        ("inflation_expectation_regime", "inflation_expectation"),
        ("recession_state", "recession"),
        ("recession_state_realtime", "recession_realtime"),
    ]:
        if regime_col in wide:
            summary.record_regime_distribution(
                dist_name, wide[regime_col].value_counts(dropna=False).to_dict()
            )

    summary.write()

    return MacroResult(
        data=wide,
        series_fetched=series_fetched,
        series_failed=series_failed,
        start_date=start_date,
        end_date=end_date,
    )


def main(
    series: Optional[List[str]] = None,
    force_refresh: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> MacroResult:
    """Entry point — fetch FRED macro series and classify daily regimes."""
    log.info("=" * 70)
    log.info("CAMARF  —  macro.py  —  FRED Macro Regime Context")
    log.info("=" * 70)

    result = build(
        series=series,
        force_refresh=force_refresh,
        start_date=start_date,
        end_date=end_date,
    )

    n_total = len(result.series_fetched) + len(result.series_failed)
    log.info(
        f"  Fetched {len(result.series_fetched)}/{n_total} series, "
        f"{len(result.data)} trading days ({result.start_date} to {result.end_date})"
    )
    if result.series_failed:
        log.warning(f"  Failed/cache-only series: {result.series_failed}")
    log.info("=" * 70)
    return result


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="CAMARF macro regime pipeline")
    p.add_argument(
        "--series",
        nargs="+",
        default=None,
        help="Specific FRED series IDs to fetch (default: all)",
    )
    p.add_argument(
        "--force-refresh", action="store_true", help="Re-fetch even if cache is fresh"
    )
    args = p.parse_args()

    main(series=args.series, force_refresh=args.force_refresh)
