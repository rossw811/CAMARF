# Contributing to / Modifying CAMARF

This is a solo research project (Ross W.), but this doc exists so anyone —
including future-me — can pick the project back up, validate a result, or
extend the pipeline without re-deriving context from scratch. Read
`CLAUDE.md` first for the project's non-negotiable architecture rules and
working-style conventions; `Development.md` is the canonical, full
session-by-session memory (bug registry, design rationale) if you need more
depth than this file provides.

---

## Environment setup

Run everything through the project's pinned conda environment, not a bare
`python` on PATH:

```bash
conda env create -f environment.yml   # if provided, else:
pip install -r requirements.txt       # into a dedicated env (see below)
```

`pyarrow==24.0.0` is specifically pinned — installing into a different
environment (or letting a bare `pip install` elsewhere touch your base
Python) can silently downgrade pyarrow and make every parquet file this
project writes look corrupted to the older version (`Repetition level
histogram size mismatch`). Always verify `python -c "import pyarrow;
print(pyarrow.__version__)"` reports `24.0.0` in whatever environment you run
scripts from.

---

## Running the pipeline

See `README.md`'s "Pipeline" section for the full ordered command sequence.
Two things worth knowing before you run anything:

- **`data.py` is yfinance-only and safe to run repeatedly** — it appends new
  bars incrementally rather than re-fetching full history. `data_ibkr.py` is
  a *separate*, manually-run script that requires a live IB Gateway
  connection and only fetches deep history for pairs already listed in
  `confirmed_pairs_manifest.json` — don't try to merge it back into the main
  `data.py` path (this was tried before and was the source of weeks of
  instability; see `Development.md` Session 5–7).
- **`analysis.py` clears `output/results/` when its own script hash (or
  `config.py`'s) changes**, so results always correspond to the code that
  produced them. If you're iterating on `analysis.py` itself, expect a full
  re-run each time you change it, not an incremental one.

For a single-timeframe debug run instead of the full ~13-timeframe sweep:

```bash
python analysis.py --timeframes 1h
```

---

## Adding a new backtest variant (the "STORM variant" pattern)

Every existing position-sizing/execution variant in `backtest.py`
(`--risk-parity`, `--storm-mm-exec`, `--storm-session-edge`, `--entry-z`,
etc.) follows the same four-stage pattern. To add a new one:

1. **CLI flag** — add an `argparse` flag near the other `--storm-*` /
   `--risk-parity` definitions.
2. **Config override / precompute** — if the variant needs a precomputed
   input (e.g. `compute_risk_parity_weights()` reads `trades_layer1.parquet`
   for per-pair volatility), compute it once in `main()` before constructing
   the engine, and pass it through as a `BacktestEngine` constructor
   argument. Never mutate global `Config` state directly — pass overrides
   explicitly (see `--entry-z`'s `copy.copy()` pattern rather than mutating
   `Config.BACKTEST.ENTRY_ZSCORE` in place).
3. **Apply in the engine** — the actual sizing/execution logic change goes in
   `BacktestEngine`'s position-sizing loop or cost function, gated on
   whether the new variant's flag/weights dict was passed in.
4. **Output naming** — append a suffix to the output label (e.g.
   `_riskparity`) so the variant's `trades_*`/`summary_*`/`portfolio_*`
   parquet files never collide with the baseline or other variants.

Once built, add the variant to the comparison table in `PAPER.md` §7 with
honest OOS numbers — don't cherry-pick only favorable variants into the
paper. If the variant is a genuine, verified result but doesn't belong in
`PAPER.md`'s tight core narrative (most won't — see `README.md`'s
Documentation Map), it still belongs somewhere: add it to `docs/FINDINGS.md`
and a one-line pointer in `PAPER.md` §7.15, not silently left undocumented.

---

## Where things are validated / where biases live

- **Bias documentation:** `output/results/bias_audit.json`. Every known bias
  (survivorship, Kelly lookahead, in-sample stop comparison, small-n
  filtering) has a mechanism/remedy/residual-risk entry. If you find a new
  one, add an entry — don't silently correct it away in the code without
  documenting what was there before and why it changed.
- **Synthetic verification tests:** `debug/_verify_*.py`. If you're
  modifying a statistical computation (a filter threshold, a test
  statistic, a rolling-window calculation), write or update the
  corresponding synthetic test that reproduces a known-answer case *before*
  trusting the change on real data — this project's own history is that
  code presented without this verification step has had bugs, and code
  verified this way has not.
- **Reproducibility chain:** `reproduce.py` maps every `PAPER.md` finding to
  the exact script/flags that generated it (`--list` to see the mapping,
  `--verify-only` to confirm outputs still exist without re-running
  anything).

---

## Standing project principles (see `CLAUDE.md` for the full statement)

- No bandaid fixes — find the single correct root-cause fix, verified with a
  synthetic reproduction, not the first thing that makes a symptom go away.
- New methodology/design ideas get discussed (what it is, why it's relevant,
  the tradeoffs) before being built — this project is a learn-as-you-go
  research thesis, not a black-box execution exercise.
- Confidence scores, Sharpe ratios, and reliability ratings are never
  inflated to make a result look stronger than the evidence supports. If a
  finding is genuinely contested in the literature or the data, report that
  honestly rather than engineering around it.
