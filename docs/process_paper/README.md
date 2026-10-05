# Process paper data (T5.3)

`failures.csv` — one row per code-review ledger table row (175), built by `python scripts/build_failures_table.py`.
- Extracted from the ledger text: id, group, location, severity, finding, status, tests named, dates.
- `class_rule` is a keyword GUESS (it agrees with the assigned class on only 20/68 rows — never cite it).
- `class_reviewed` comes from `failure_classes.csv` (who assigned it is recorded: currently the assistant, 2026-10-04,
  for the 68 FIXED / CONFIRMED-OPEN rows, **pending Ross's review**). Only reviewed classes go into the paper.

**Not yet in the table (prose findings outside the ledger's tables — add before computing the taxonomy):**
D16 cross-asset symbol collisions, D17 reused tickers given to the oldest holder (2,719 of 4,327), D18/D19 quote-only
series, the 110 Purity "pairs" that were one security against itself, DEV-003 CRSP + Compustat volume split bias
(19% of ADV-gate passes), the A3/A2 forward-filled hedge inputs, the T14 tests that deleted real outputs, and the
T14.7 independent-review findings (docs/INCONSISTENCY_SWEEP_2026-09-27.md, docs/ERRATA.md).
Effects (`effect_reviewed`) are still empty: only 1 of 44 FIXED rows states a before/after number in the ledger text;
each needs its re-derived effect from its evidence before the paper cites it.
