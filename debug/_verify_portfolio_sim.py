"""
Synthetic verification for portfolio_sim.py's replay_portfolio() (BUG-D60 / equity-proportional
sizing / mark-to-market build, 2026-07-12). Uses synthetic price/trade fixtures with KNOWN
capital requirements so each case's correct outcome can be verified by hand, not just "did it run."

Monkeypatches get_price_at()/get_spread_at() to fixed synthetic tables instead of hitting real
output/cache/output/results files -- keeps this test fully deterministic and independent of real
market data.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import portfolio_sim
from portfolio_sim import replay_portfolio

# Fixed synthetic prices: $100/share for every leg, every symbol -- makes notional = n_shares * 100
# trivial to hand-verify.
portfolio_sim.get_price_at = lambda symbol, ts: 100.0
# Default: flat spread (no unrealized P&L) unless a case overrides this.
portfolio_sim.get_spread_at = lambda symbol_a, symbol_b, tf, ts: 10.0


def trade(symbol_a, symbol_b, entry, exit_, n_shares_a, n_shares_b, pnl_net,
          entry_spread=10.0, side="long", tf="1h", entry_z=2.0, half_life_at_entry=20.0):
    return {
        "symbol_a": symbol_a, "symbol_b": symbol_b, "tf": tf,
        "entry_time": pd.Timestamp(entry), "exit_time": pd.Timestamp(exit_),
        "entry_z": entry_z, "half_life_at_entry": half_life_at_entry,
        "n_shares_a": n_shares_a, "n_shares_b": n_shares_b, "pnl_net": pnl_net,
        "entry_spread": entry_spread, "side": side,
    }


def main():
    failures = []

    # --- Case 1: two NON-overlapping trades, both well within capital -- both taken at full size ---
    trades1 = pd.DataFrame([
        trade("A", "B", "2026-01-01", "2026-01-02", 100, 100, 500.0),   # notional = 100*100 + 100*100 = 20000
        trade("C", "D", "2026-01-03", "2026-01-04", 100, 100, -200.0),  # starts AFTER trade 1 closes
    ])
    r1 = replay_portfolio(trades1, starting_capital=50_000, sizing_method="fixed")
    if r1["n_taken"] != 2:
        failures.append(f"Case 1: expected both non-overlapping trades taken, got n_taken={r1['n_taken']}")
    if r1["skipped_count"] != 0:
        failures.append(f"Case 1: expected 0 skipped, got {r1['skipped_count']}")
    expected_final = 50_000 + 500.0 - 200.0
    if abs(r1["final_equity"] - expected_final) > 0.01:
        failures.append(f"Case 1: expected final_equity={expected_final}, got {r1['final_equity']}")
    print(f"Case 1 (non-overlapping, ample capital): n_taken={r1['n_taken']}, "
          f"skipped={r1['skipped_count']}, final_equity={r1['final_equity']:.2f} "
          f"(expected {expected_final})")

    # --- Case 2: two OVERLAPPING trades whose combined notional EXCEEDS starting capital ---
    # Each trade needs $20,000 notional (100 shares * $100 * 2 legs). Capital = $25,000 -- can
    # fully fund the first, but the second (still overlapping) can only get $5,000 worth =
    # size_scale 0.25, well above min_size_scale (0.05), so it should be TAKEN but DOWNSIZED,
    # not skipped.
    trades2 = pd.DataFrame([
        trade("A", "B", "2026-01-01", "2026-01-10", 100, 100, 1000.0),
        trade("C", "D", "2026-01-02", "2026-01-05", 100, 100, 1000.0),  # opens while trade 1 still open
    ])
    r2 = replay_portfolio(trades2, starting_capital=25_000, sizing_method="fixed")
    if r2["n_taken"] != 2:
        failures.append(f"Case 2: expected both trades taken (one downsized), got n_taken={r2['n_taken']}")
    else:
        second_scale = r2["taken"].iloc[1]["size_scale"]
        expected_scale = 5_000 / 20_000  # (25000 - 20000 committed) / 20000 target
        if abs(second_scale - expected_scale) > 0.01:
            failures.append(f"Case 2: expected second trade size_scale~{expected_scale:.3f}, "
                             f"got {second_scale:.3f}")
        print(f"Case 2 (capital-constrained overlap): first size_scale="
              f"{r2['taken'].iloc[0]['size_scale']:.3f}, second size_scale={second_scale:.3f} "
              f"(expected ~{expected_scale:.3f})")

    # --- Case 3: capital fully exhausted -- second trade should be SKIPPED entirely ---
    trades3 = pd.DataFrame([
        trade("A", "B", "2026-01-01", "2026-01-10", 100, 100, 1000.0),  # needs $20,000
        trade("C", "D", "2026-01-02", "2026-01-05", 100, 100, 1000.0),  # needs $20,000, overlaps
    ])
    r3 = replay_portfolio(trades3, starting_capital=20_500, sizing_method="fixed")
    # available for 2nd trade = 20500 - 20000 = 500; scale = 500/20000 = 0.025 < min_size_scale(0.05) -> skip
    if r3["n_taken"] != 1 or r3["skipped_count"] != 1:
        failures.append(f"Case 3: expected 1 taken + 1 skipped (capital exhausted), "
                         f"got taken={r3['n_taken']} skipped={r3['skipped_count']}")
    print(f"Case 3 (capital exhausted): n_taken={r3['n_taken']}, skipped={r3['skipped_count']} "
          f"(expected 1 taken, 1 skipped)")

    # --- Case 4: equity_proportional sizing -- a big profitable closed trade should scale UP
    # a later trade's target notional, matching Ross's day-1-$10k/day-10-$15k example.
    # n_shares=50 -> notional = 50*100*2 legs = $10,000, exactly matching starting_capital, so
    # trade 1 itself gets size_scale=1.0 (fully funded, not itself capital-constrained) --
    # isolates the equity-growth effect being tested from a confounding capital constraint on
    # trade 1 (an earlier version of this fixture used n_shares=100/$20k notional against
    # $10k starting capital, which constrained trade 1 too and produced a wrong expected value
    # -- caught by this test failing before being trusted, exactly as intended). ---
    trades4 = pd.DataFrame([
        trade("A", "B", "2026-01-01", "2026-01-02", 50, 50, 5_000.0),  # closes profitably, equity 10k->15k
        trade("C", "D", "2026-01-05", "2026-01-06", 50, 50, 0.0),      # opens AFTER, at higher equity
    ])
    r4 = replay_portfolio(trades4, starting_capital=10_000, sizing_method="equity_proportional")
    if r4["n_taken"] != 2:
        failures.append(f"Case 4: expected both trades taken, got n_taken={r4['n_taken']}")
    else:
        second_target_scale = r4["taken"].iloc[1]["actual_notional"] / r4["taken"].iloc[1]["notional_at_entry"]
        # equity at 2nd trade's entry should be 15000 (10000 + 5000 realized), so target =
        # original * (15000/10000) = 1.5x original notional
        expected_ratio = 15_000 / 10_000
        if abs(second_target_scale - expected_ratio) > 0.02:
            failures.append(f"Case 4: expected 2nd trade's notional scaled by ~{expected_ratio:.2f}x "
                             f"(equity grew 10k->15k), got {second_target_scale:.2f}x")
        print(f"Case 4 (equity-proportional scaling): 2nd trade notional scaled by "
              f"{second_target_scale:.2f}x (expected ~{expected_ratio:.2f}x, since equity grew "
              f"$10,000 -> $15,000 after the first trade closed profitably)")

    # --- Case 5: mark-to-market -- an OPEN (not yet closed) position's UNREALIZED gain must
    # free up capital for a new entry, beyond what realized-only equity would show. This is the
    # highest-risk new logic (Ross's direction, 2026-07-12) and the one most likely to have a
    # sign/direction bug, so it's checked explicitly against a hand-computed expected value. ---
    portfolio_sim.get_spread_at = lambda symbol_a, symbol_b, tf, ts: (
        30.0 if (symbol_a, symbol_b) == ("A", "B") and ts >= pd.Timestamp("2026-01-03") else 10.0
    )
    trades5 = pd.DataFrame([
        # long A/B, entry_spread=10, n_shares_a=50 -> notional $10,000, fully funds trade 1 at
        # starting_capital=$10,000 (size_scale=1.0, not itself capital-constrained).
        trade("A", "B", "2026-01-01", "2026-01-10", 50, 50, 2_000.0, entry_spread=10.0, side="long"),
        # C/D opens on 01-03, WHILE trade 1 is still open (exits 01-10). At 01-03, trade 1's
        # spread has moved from 10 -> 30 (mocked above): unrealized gain = direction(+1) *
        # (30-10) * n_shares_a(50) * size_scale(1.0) = +$1,000. mtm_equity at this instant =
        # realized_equity($10,000, nothing closed yet) + unrealized($1,000) = $11,000.
        # committed_now (trade 1, ORIGINAL basis) = $10,000. available = 11000 - 10000 = $1,000.
        # Trade 2's own notional is set to $11,000 (55 shares * $100 * 2 legs) so its expected
        # size_scale = 1000 / 11000 ~= 0.0909 -- a value that is IMPOSSIBLE to reach if the
        # unrealized gain were ignored (realized-only equity would give available=$0).
        trade("C", "D", "2026-01-03", "2026-01-04", 55, 55, 500.0, entry_spread=10.0, side="long"),
    ])
    r5 = replay_portfolio(trades5, starting_capital=10_000, sizing_method="fixed")
    if r5["n_taken"] != 2:
        failures.append(f"Case 5: expected both trades taken (2nd downsized via MTM headroom), "
                         f"got n_taken={r5['n_taken']}")
    else:
        second_scale = r5["taken"].iloc[1]["size_scale"]
        expected_scale = 1_000 / 11_000
        if abs(second_scale - expected_scale) > 0.01:
            failures.append(f"Case 5: expected 2nd trade size_scale~{expected_scale:.4f} "
                             f"(from trade 1's +$1,000 UNREALIZED gain freeing capital), "
                             f"got {second_scale:.4f} -- if this is ~0 or negative, mark-to-market "
                             f"is not crediting unrealized gains toward available capital")
    print(f"Case 5 (mark-to-market unrealized gain frees capital): "
          f"{'2nd trade size_scale=' + format(r5['taken'].iloc[1]['size_scale'], '.4f') if r5['n_taken']==2 else 'FAILED to take 2nd trade'} "
          f"(expected ~{1000/11000:.4f}, only reachable if trade 1's open +$1,000 unrealized "
          f"gain was correctly counted toward available capital)")
    # Reset mock for any test run after this one.
    portfolio_sim.get_spread_at = lambda symbol_a, symbol_b, tf, ts: 10.0

    # --- Case 6: flat_2pct risk-based sizing against a KNOWN causal volatility ---
    # sigma=5.0, entry_z=2.0, STOP_ZSCORE=3.5 -> z_distance_to_stop=1.5 -> risk_per_share=7.5.
    # current_equity=100,000 (single trade, no prior activity) -> target_shares_a =
    # (0.02 * 100,000) / 7.5 = 266.667. hedge_ratio from fixture (n_shares_b/n_shares_a=100/100=1.0)
    # -> target_notional = 266.667*100 (leg A) + 266.667*1.0*100 (leg B) = $53,333.33.
    portfolio_sim.causal_rolling_std_at_entry = lambda a, b, tf, ts, hl: 5.0
    trades6 = pd.DataFrame([trade("A", "B", "2026-01-01", "2026-01-02", 100, 100, 500.0, entry_z=2.0)])
    r6 = replay_portfolio(trades6, starting_capital=100_000, sizing_method="flat_2pct")
    expected_notional_6 = 53_333.33
    if r6["n_taken"] != 1:
        failures.append(f"Case 6: expected trade taken, got n_taken={r6['n_taken']}")
    else:
        actual_notional_6 = r6["taken"].iloc[0]["actual_notional"]
        if abs(actual_notional_6 - expected_notional_6) > 5:
            failures.append(f"Case 6: expected flat_2pct target_notional~${expected_notional_6:,.2f}, "
                             f"got ${actual_notional_6:,.2f}")
        print(f"Case 6 (flat_2pct risk-based sizing): actual_notional=${actual_notional_6:,.2f} "
              f"(expected ~${expected_notional_6:,.2f}, from 2% of $100,000 equity / $7.50 "
              f"risk-per-share at the causal stop distance)")

    # --- Case 7: half_kelly/full_kelly with < 60 prior closed trades falls back to flat_2pct
    # exactly (same math as Case 6) -- and n_kelly_fallback must count it. ---
    r7 = replay_portfolio(trades6, starting_capital=100_000, sizing_method="half_kelly")
    if r7["n_kelly_fallback"] != 1:
        failures.append(f"Case 7: expected n_kelly_fallback=1 (no trade history yet), "
                         f"got {r7['n_kelly_fallback']}")
    elif r7["n_taken"] == 1:
        actual_notional_7 = r7["taken"].iloc[0]["actual_notional"]
        if abs(actual_notional_7 - expected_notional_6) > 5:
            failures.append(f"Case 7: fallback should match flat_2pct exactly (~${expected_notional_6:,.2f}), "
                             f"got ${actual_notional_7:,.2f}")
    print(f"Case 7 (Kelly fallback, <60 trade history): n_kelly_fallback={r7['n_kelly_fallback']} "
          f"(expected 1), sizing matches flat_2pct: "
          f"{'yes' if r7['n_taken']==1 and abs(r7['taken'].iloc[0]['actual_notional']-expected_notional_6)<=5 else 'NO'}")

    # --- Case 8: half_kelly/full_kelly with >=60 REAL prior closed trades uses the actual
    # Kelly formula. 60 warm-up trades: 36 wins of +100, 24 losses of -50 -> win_rate=0.6,
    # payoff_ratio=100/50=2.0 -> f* = 0.6 - 0.4/2.0 = 0.4. half_kelly=0.2, full_kelly=0.4.
    # Warm-up trades use tiny pnl relative to a large starting_capital ($10M) so current_equity
    # at trade 61 stays close enough to starting_capital for a tolerant hand-check. ---
    warmup = []
    t0 = pd.Timestamp("2026-01-01")
    # Exact 36 win / 24 loss sequence, deterministic.
    pattern = ([100.0] * 3 + [-50.0] * 2) * 12  # 12*(3 win + 2 loss) = 36 win, 24 loss, 60 total
    assert len(pattern) == 60 and pattern.count(100.0) == 36 and pattern.count(-50.0) == 24
    for i, pnl in enumerate(pattern):
        entry = t0 + pd.Timedelta(hours=2 * i)
        exit_ = entry + pd.Timedelta(hours=1)
        warmup.append(trade("W", "X", entry, exit_, 10, 10, pnl, entry_z=2.0))
    test_trade_entry = t0 + pd.Timedelta(hours=2 * 60)
    warmup.append(trade("A", "B", test_trade_entry, test_trade_entry + pd.Timedelta(hours=1),
                         100, 100, 500.0, entry_z=2.0))
    trades8 = pd.DataFrame(warmup)

    r8_half = replay_portfolio(trades8, starting_capital=10_000_000, sizing_method="half_kelly")
    r8_full = replay_portfolio(trades8, starting_capital=10_000_000, sizing_method="full_kelly")
    if r8_half["n_kelly_fallback"] != 60 or r8_full["n_kelly_fallback"] != 60:
        failures.append(f"Case 8: expected exactly 60 fallback trades (warm-up) before real Kelly "
                         f"engages on trade 61, got half={r8_half['n_kelly_fallback']} "
                         f"full={r8_full['n_kelly_fallback']}")
    else:
        # With risk_per_share=$7.50 and a 20-40% risk fraction, the UNCAPPED Kelly target
        # notional vastly exceeds even a $10M account -- both half_kelly and full_kelly
        # correctly hit the SAME capital ceiling here, which is why their notionals come out
        # identical. That's correct capital-constraint behavior (already covered by Cases 1-3),
        # not a Kelly-math bug -- so the Kelly FORMULA itself is verified directly below,
        # decoupled from capital-availability effects, rather than backed out through a replay
        # whose result is dominated by a different mechanism.
        half_notional = r8_half["taken"].iloc[-1]["actual_notional"]
        full_notional = r8_full["taken"].iloc[-1]["actual_notional"]
        if abs(half_notional - full_notional) > 1.0:
            failures.append(f"Case 8: expected half_kelly and full_kelly to BOTH be capped at the "
                             f"same $10M capital ceiling (uncapped targets vastly exceed it), "
                             f"got half=${half_notional:,.2f} full=${full_notional:,.2f} -- "
                             f"if these differ, something other than the capital cap is binding")
        print(f"Case 8 (capital-capped Kelly integration check): half_kelly notional="
              f"${half_notional:,.2f}, full_kelly notional=${full_notional:,.2f} "
              f"(expected equal -- both correctly capital-capped at ~$10M, since the uncapped "
              f"Kelly targets vastly exceed the account size)")

    # Case 8b: the Kelly FORMULA itself, tested directly and precisely, decoupled from capital
    # effects -- 36 wins of +100 / 24 losses of -50 -> win_rate=0.6, payoff_ratio=2.0 ->
    # f* = 0.6 - 0.4/2.0 = 0.4 exactly.
    f_star = portfolio_sim._kelly_fraction(pattern)
    if abs(f_star - 0.4) > 1e-9:
        failures.append(f"Case 8b: expected f*=0.4 exactly from win_rate=0.6/payoff_ratio=2.0, got {f_star}")
    # Below the 60-trade threshold, _kelly_fraction must return NaN (triggering the fallback),
    # not a (falsely precise-looking) estimate from too little data.
    f_star_thin = portfolio_sim._kelly_fraction(pattern[:59])
    if np.isfinite(f_star_thin):
        failures.append(f"Case 8b: expected NaN (insufficient history, <60 trades) for 59 trades, "
                         f"got {f_star_thin} -- the 60-trade floor is not being enforced")
    print(f"Case 8b (Kelly formula, direct): f*(60 trades, win_rate=0.6, payoff=2.0) = {f_star} "
          f"(expected 0.4 exactly); f*(59 trades) = {f_star_thin} (expected NaN, below the "
          f"documented 60-trade reliability floor)")

    portfolio_sim.causal_rolling_std_at_entry = None  # unset mock

    print()
    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("All portfolio_sim.py checks passed: capital constraints, downsizing, skipping, and "
          "equity-proportional scaling all behave correctly on known synthetic cases.")


if __name__ == "__main__":
    main()
