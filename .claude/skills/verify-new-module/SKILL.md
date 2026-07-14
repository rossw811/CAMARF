---
name: verify-new-module
description: Package CAMARF's own verify-before-trusting discipline (synthetic ground-truth check → real run → Development.md write-up) as a repeatable workflow. Use whenever building a new research/ module, a new analysis technique, or any statistical method that will run on real data. Invoke with the module's purpose and what it computes.
---

# verify-new-module

CAMARF's standing rule (CLAUDE.md, "Working Style"): "Verify before claiming done. Write a
synthetic test that reproduces the bug, confirm the fix resolves it, THEN present the fix." This
skill packages that exact sequence, since it's been applied by hand dozens of times across this
project's sessions.

## When to use

Any time a new `research/*.py` module, a new statistical technique, or any new analysis is about
to be built and run on real data.

## The sequence, followed in this exact order

1. **Full comprehension first.** Read any existing, related code this new module extends or is
   analogous to (e.g. a similar `research/` module, or the production code path it's testing
   against). Don't guess at conventions — match them.
2. **Design the synthetic ground-truth check FIRST**, before writing the real module. Construct a
   case with a KNOWN correct answer (e.g. synthetic data with a planted, known relationship) and
   define what "correct" output looks like. Write this as `debug/_verify_<module_name>.py`,
   matching CAMARF's existing naming convention.
3. **Build the real module.** `research/<module_name>.py`, matching this project's established
   style (see any recent `research/` module for the current convention — imports, docstring
   format, output-saving pattern to `output/research/*.parquet`).
4. **Run the synthetic verification FOR REAL** — actually execute it, don't assume it would pass.
   If it fails, that's real signal: either the module has a bug, or (as has happened multiple
   times in this project's history) the synthetic test's own construction is flawed and needs
   fixing. Diagnose which, fix it, re-run until it genuinely passes.
5. **Run on real data.** Only after step 4 passes.
6. **Write the Development.md entry** — mechanism, the synthetic verification result (including
   any failed-then-fixed attempt, per CLAUDE.md rule 8: document what was tried, not just what
   worked), the real numbers, and an honest conclusion whichever way it comes out. A clean null
   result is exactly as valuable as a positive one — do not manufacture significance.
7. **Do not promote to PAPER.md automatically.** New findings default to `docs/FINDINGS.md`
   (or stay purely in Development.md if not yet at write-up quality). Promotion to PAPER.md's
   headline claims is a separate, deliberate decision — see CLAUDE.md's research/paper decoupling
   policy.

## What NOT to do

Do not skip step 2 to save time — this project's own history (BUG-D62, the capital-sim
Sharpe-convention bug; the near-miss lag scan's calendar-alignment false positive) shows real,
headline-affecting bugs that only synthetic verification caught. Do not report a real-data result
before the synthetic check has genuinely passed.
