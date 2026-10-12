# Parameter registry — why every value has the value it has

Ross, 2026-10-12: *"we shouldn't have any arbitrary values and we need to show why they were chosen, then we need to
account for the overfitting."*

- **Registry:** `docs/PARAMETER_REGISTRY.csv`, built by `scripts/build_parameter_registry.py` (AST scan of `config.py`
  and every module-level UPPERCASE numeric constant in the core modules and `research/`). 337 values on 2026-10-12.
- **Gate:** `debug/_verify_parameter_registry.py` (in the verify suite) fails if a value in the code is not
  registered, if its registered value differs from the code, if a justified row lacks a reason or evidence, or if the
  number of `unjustified` rows rises above `docs/PARAMETER_REGISTRY_CEILING.txt` (a ratchet: the backlog may only
  shrink).
- **Not yet covered:** numbers written inline in code (`p < 0.05`, the stress test's 0.15 gap). Phase 2 scans numeric
  literals in comparisons and thresholds and registers them the same way.

## Categories

| Category | Meaning | Evidence required |
|---|---|---|
| definition | Follows from a definition or unit (252 trading days/year, numerical tolerances) | the definition |
| convention | Standard practice in the literature | citation |
| data_constraint | Forced by the data (Yahoo's 8-day 1m limit, CRSP coverage) | source of the limit |
| calibrated | Set from an empirical test | script + output + date |
| preregistered | Fixed in a pre-registration before any result | document + commit |
| engineering | Performance, memory, I/O only; cannot change a result | why it is result-neutral (ideally a test) |
| unjustified | No recorded reason yet | — (the backlog) |

`outcome_informed` records whether the value was chosen or changed **after** seeing a result it affects, and
`alternatives_tried` how many other values were tried on outcome data. Those two columns are the input to the
overfitting account below.

## Accounting for overfitting — PROPOSAL (needs Ross's buy-in before it changes any reported number)

A value chosen after looking at results is a hidden trial. Three complementary corrections, each standard:

1. **Trial count in the deflated Sharpe.** Every result-affecting value marked `outcome_informed = yes/unknown`
   multiplies the effective number of specifications that were (implicitly) tried. The project-wide trial ledger
   (brainstorm item 16) counts them from the registry plus the run logs/lineage; every reported Sharpe is deflated
   (Bailey & López de Prado 2014) with that N, not only with the grid it came from. Unknown counts as tried.
2. **Specification curve** (Simonsohn, Simmons & Nelson 2020). For each headline result, re-run it across the
   defensible range of every outcome-informed value (e.g. MIN_COINT_FRAC 0.5–0.8, window 5–15 years) and report the
   whole distribution of outcomes, with the chosen point marked. A result that only holds near the chosen values is
   reported as fragile.
3. **Discovery-side calibration.** For screening thresholds (FDR alpha, windows, liquidity gates), the end-to-end
   placebo discovery (brainstorm item 1) measures the false-discovery rate the pipeline actually delivers with the
   values as set — the overfitting check for the discovery machine, independent of any P&L.
4. **Final arbiter:** the sealed holdout (brainstorm item 14), declared before it is touched, used once.

Decision needed from Ross: adopt 1–4 as the reporting standard (each enters as a comparison beside the current
numbers first), or modify.
