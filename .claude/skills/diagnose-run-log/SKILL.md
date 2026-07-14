---
name: diagnose-run-log
description: Parse and diagnose CAMARF's structured run-summary logs (latest_run_data.log, latest_run_analysis.log, and other latest_run_*.log files) for anomalies, instead of manually reading raw console scrollback. Use whenever a data.py/analysis.py/backtest.py run just completed and needs a health check, or when debugging why a run behaved unexpectedly.
---

# diagnose-run-log

CAMARF writes structured, LLM-readable run summaries after every `data.py`/`analysis.py`/other
pipeline script run — `latest_run_data.log`, `latest_run_analysis.log`, `latest_run_<script>.log`
generally. CLAUDE.md's own working-style rule: "Ask for these directly instead of raw console
scrollback." This skill packages that into a repeatable diagnostic pass.

## When to use

- Right after any pipeline script completes, as a health check before trusting its output.
- When a run behaved unexpectedly and the raw stdout/stderr is too long to read productively.
- When comparing a new run against a prior one to see what changed.

## What to actually do

1. Read the relevant `latest_run_<script>.log` file directly (it's already structured — don't
   also read the raw stdout/stderr log unless the summary itself points to something needing
   deeper investigation).
2. Check for the standard health signals this project's logs report: final universe/candidate
   count vs. the `<1000` sanity-guard floor (CLAUDE.md flags this as catching a real past
   incident — universe silently shrinking to 86 assets went unnoticed for multiple runs), the
   config hash (for reproducibility tracking), exclusion counts and their stated reasons, and any
   `ERROR`/`WARNING` density that looks abnormal relative to a typical run (a handful of
   individual-symbol fetch failures is normal; a large spike is not).
3. If something looks anomalous, THEN go to the raw `latest_run_<script>_stdout.log`/`_stderr.log`
   for the specific window around the anomaly — not the whole file.
4. Compare against the previous run's summary if one exists, to distinguish "this run has a new
   problem" from "this has always been the case."
5. Report findings plainly — if the run is clean, say so; if something needs attention, name the
   specific anomaly and where in the log it shows up, not a vague "something might be off."

## What NOT to do

Do not read raw console scrollback as the first step when a structured summary exists — that's
exactly the inefficiency this skill and CLAUDE.md's own rule exist to avoid.
