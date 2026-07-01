"""
trial_registry.py — append-only record of every backtest.py run's reported
portfolio Sharpe, so a Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014)
can correct the headline Sharpe for the actual number of strategy variants/
configurations tried, instead of only ever reporting the single best-looking
number. Shared by backtest.py (writer, one entry per run) and
deflated_sharpe.py (reader).

Each entry: {label, sharpe, n_trades, holdout, timestamp_run}. `timestamp_run`
is passed in by the caller (Date.now()-equivalent isn't computed here) so
callers control what "now" means for their own run.

Deliberately dumb and append-only: no dedup, no locking. If backtest.py is
run twice with the same flags, that's two genuine trials (re-running IS
itself a trial in the backtest-overfitting sense the DSR corrects for), not
a duplicate to be collapsed.
"""
import json
import os
from typing import Any, Dict, List, Optional

_REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "output", "backtest", "trial_registry.json"
)


def record_trial(
    label: str,
    sharpe: Optional[float],
    n_trades: int,
    script: str = "backtest.py",
    timestamp_run: Optional[str] = None,
) -> None:
    """Append one trial to the registry. No-op if sharpe is None/NaN — a
    trial that produced no usable Sharpe isn't a comparable "variant tried"
    for DSR purposes (e.g. an empty --pairs-override subset)."""
    if sharpe is None:
        return
    try:
        if sharpe != sharpe:  # NaN check without importing numpy here
            return
    except TypeError:
        return
    os.makedirs(os.path.dirname(_REGISTRY_PATH), exist_ok=True)
    trials = load_trials()
    trials.append({
        "script": script,
        "label": label,
        "sharpe": float(sharpe),
        "n_trades": int(n_trades),
        "timestamp_run": timestamp_run,
    })
    with open(_REGISTRY_PATH, "w") as f:
        json.dump(trials, f, indent=2)


def load_trials() -> List[Dict[str, Any]]:
    if not os.path.exists(_REGISTRY_PATH):
        return []
    with open(_REGISTRY_PATH, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []
