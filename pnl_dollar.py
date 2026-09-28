"""
pnl_dollar.py -- dollar P&L for pair trades, marked at real leg prices (2026-09-26; fixes code-review
findings B2 and B3; Ross-approved "dollar P&L" methodology, built as a COMPARISON column set first).

Why
---
backtest.py books gross P&L as side * (exit_spread - entry_spread) * n_shares_a, where
spread_t = log_a - beta_t * log_b and beta_t is re-estimated every bar. That (B2) includes
(beta_entry - beta_exit) * log_b_exit, a term no held position earns -- measured on 2,062 real
momentum-gate trades it was ALL of the positive gross P&L (+31,865 recorded vs -983 with beta held
at entry) -- and (B3) is in log-units x shares while costs are dollars.

Convention implemented here
---------------------------
Position fixed at entry, each leg marked at its own price. Leg-A dollar notional N_a is either a
FIXED DOLLAR amount per trade (sizing="fixed_notional", default) or n_shares_a * P_a(entry)
(sizing="shares", backtest.py's share count). Fixed notional is the default because P_a is a
split-ADJUSTED close: a fixed 100 shares of AMAT in 1991 (adjusted $0.42) is a $42 position, so
share-based sizing gives early trades negligible weight and a per-share commission out of all
proportion (found hand-checking real trades, 2026-09-27). Sharpe is invariant to the fixed amount.
    N_a        = notional_per_trade  |  n_shares_a * P_a(entry)
    n_b        = beta_entry * N_a / P_b(entry)                 (beta-weighted dollar hedge)
    gross      = side * N_a * (r_a - beta_entry * r_b)          (side = +1 long spread = long A/short B)
    cost       = commission * (n_a + |n_b|) * 2 + slippage_bps/1e4 * N_a * (1 + |beta|) * 2
where r = total return over [entry date, exit date] from a dividend-inclusive series (WRDS
close_total_return; yfinance adjusted close is already dividend-adjusted). Entry/exit prices are the
last close AT OR BEFORE each date (never a later one).

Scope limits, returned as an explicit per-trade status rather than a number:
  * "non_usd_leg": Compustat Global (GVKEY*) legs are in local currency with no stored currency code
    (code review R1.1). Excluded until the approved USD conversion is built -- 764 of the 1,180
    symbols in the current 1,375-pair pool are GVKEY.
  * "intraday": only daily bars are marked here (1D is >99.8% of current trades).
  * "missing_price" / "bad_hedge": no usable price or hedge ratio.

The original pnl_gross / pnl_cost / pnl_net columns are left untouched (comparison arm).
Verified against hand-computed cases: debug/_verify_pnl_dollar.py.
"""
import os
import re
from typing import Callable, Optional

import numpy as np
import pandas as pd

from config import Config

_WRDS_DIR = os.path.join("output", "cache", "wrds")
_YF_DIR = Config.DATA.CACHE_DIR
_SHARE_CLASS = {"A", "B", "C"}
_cache = {}


def is_usd_symbol(symbol: str) -> bool:
    s = str(symbol)
    if "GVKEY" in s:
        return False
    m = re.search(r"\.([A-Z0-9]+)$", s)
    return not (m and m.group(1) not in _SHARE_CLASS)


def load_daily_prices(symbol: str) -> Optional[pd.DataFrame]:
    """DataFrame[close, tr] on a date index, or None. WRDS first (close = split-adjusted price,
    tr = close_total_return), then the yfinance daily cache (adjusted close for both)."""
    if symbol in _cache:
        return _cache[symbol]
    out = None
    for path, tr_col in ((os.path.join(_WRDS_DIR, f"{symbol}_1D.parquet"), "close_total_return"),
                         (os.path.join(_YF_DIR, f"{symbol}_1day.parquet"), None)):
        # Compustat Global files carry close_usd once research/apply_fx_to_wrds_global.py has run (R1.1):
        # both price level and return series then come from the USD column.
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            continue
        try:
            d = pd.read_parquet(path)
        except Exception:
            continue
        if "close" not in d.columns:
            continue
        if "close_usd" in d.columns and d["close_usd"].notna().any():
            px = d["close_usd"]
            # 2026-09-28: USD total return from Compustat's verified trfd factor when present
            # (research/apply_trfd_total_return.py) -- before, returns came from the price-only close_usd, so a
            # Compustat leg's dividends never reached the P&L while CRSP legs' did.
            tr = d["close_total_return"] if "close_total_return" in d.columns and \
                d["close_total_return"].notna().any() else px
            usd = True
        else:
            px = d["close"]
            tr = d[tr_col] if tr_col and tr_col in d.columns else d["close"]
            usd = is_usd_symbol(symbol)
        out = pd.DataFrame({"close": pd.to_numeric(px, errors="coerce").astype(float),
                            "tr": pd.to_numeric(tr, errors="coerce").astype(float)})
        out.index = pd.to_datetime(out.index).tz_localize(None).normalize() if getattr(out.index, "tz", None) \
            else pd.to_datetime(out.index).normalize()
        out = out[~out.index.duplicated(keep="last")].sort_index()
        out.attrs["usd"] = usd
        break
    _cache[symbol] = out
    return out


def _at_or_before(df: pd.DataFrame, ts: pd.Timestamp):
    i = df.index.searchsorted(pd.Timestamp(ts).normalize(), side="right") - 1
    return None if i < 0 else df.iloc[i]


def add_dollar_pnl(trades: pd.DataFrame, commission_per_share: float = None, slippage_bps: float = None,
                   price_loader: Callable[[str], Optional[pd.DataFrame]] = None,
                   sizing: str = "fixed_notional", notional_per_trade: float = 10_000.0) -> pd.DataFrame:
    """Returns a copy of `trades` with pnl_dollar_gross / pnl_dollar_cost / pnl_dollar_net /
    notional_dollar_entry / n_shares_b_dollar / pnl_dollar_status added."""
    commission_per_share = Config.BACKTEST.COMMISSION_PER_SHARE if commission_per_share is None else commission_per_share
    slippage_bps = Config.BACKTEST.SLIPPAGE_BPS if slippage_bps is None else slippage_bps
    loader = price_loader or load_daily_prices
    out = trades.copy()
    cols = {k: np.full(len(out), np.nan) for k in
            ("pnl_dollar_gross", "pnl_dollar_cost", "pnl_dollar_net", "notional_dollar_entry", "n_shares_b_dollar")}
    status = np.array(["ok"] * len(out), dtype=object)
    for i, t in enumerate(out.itertuples(index=False)):
        if str(t.tf) != "1D":
            status[i] = "intraday"; continue
        beta = float(t.hedge_ratio)
        if not np.isfinite(beta):
            status[i] = "bad_hedge"; continue
        A, B = loader(t.symbol_a), loader(t.symbol_b)
        # A leg is usable only if its price series is in USD: a US listing, or a Compustat Global listing
        # converted via close_usd (frame attrs set by load_daily_prices; name rule as the fallback).
        _usd = lambda F, sym: F.attrs.get("usd", is_usd_symbol(sym)) if F is not None else is_usd_symbol(sym)
        if not (_usd(A, t.symbol_a) and _usd(B, t.symbol_b)):
            status[i] = "non_usd_leg"; continue
        if A is None or B is None or pd.isna(t.exit_time):
            status[i] = "missing_price"; continue
        ae, ax, be, bx = (_at_or_before(A, t.entry_time), _at_or_before(A, t.exit_time),
                          _at_or_before(B, t.entry_time), _at_or_before(B, t.exit_time))
        if any(v is None for v in (ae, ax, be, bx)):
            status[i] = "missing_price"; continue
        vals = [ae["close"], be["close"], ae["tr"], ax["tr"], be["tr"], bx["tr"]]
        if not all(np.isfinite(vals)) or ae["close"] <= 0 or be["close"] <= 0 or ae["tr"] <= 0 or be["tr"] <= 0:
            status[i] = "missing_price"; continue
        side = 1.0 if t.side == "long" else -1.0
        if sizing == "fixed_notional":
            N_a = float(notional_per_trade)
            n_a = N_a / ae["close"]
        elif sizing == "shares":
            n_a = float(t.n_shares_a)
            N_a = n_a * ae["close"]
        else:
            raise ValueError(f"unknown sizing {sizing!r}")
        n_b = beta * N_a / be["close"]
        r_a = ax["tr"] / ae["tr"] - 1.0
        r_b = bx["tr"] / be["tr"] - 1.0
        gross = side * N_a * (r_a - beta * r_b)
        cost = commission_per_share * (n_a + abs(n_b)) * 2 + slippage_bps / 1e4 * N_a * (1 + abs(beta)) * 2
        cols["pnl_dollar_gross"][i] = gross
        cols["pnl_dollar_cost"][i] = cost
        cols["pnl_dollar_net"][i] = gross - cost
        cols["notional_dollar_entry"][i] = N_a * (1 + abs(beta))
        cols["n_shares_b_dollar"][i] = n_b
    for k, v in cols.items():
        out[k] = v
    out["pnl_dollar_status"] = status
    return out
