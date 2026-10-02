---
name: Find a hole
about: Report a flaw in a claim, a method, the code or the data handling. Every report is verified and answered.
title: "[hole] "
labels: find-a-hole
---

**What claim, method or code is affected?**
(A claims-registry ID from docs/CLAIMS_REGISTRY.md if there is one, or file:line / doc:line.)

**What is wrong?**
(Lookahead, selection bias, wrong statistic, data mislabel, untested assumption, misleading wording, ...)

**Evidence**
(How to see it: a command, a minimal example, a reference. Exact numbers help.)

**What would change?**
(Your estimate of the effect on the claim, if you have one.)

---
*What happens next:* we reproduce it, then fix it (with a test that fails before the fix) or disclose it as a
limitation, and log the outcome under the registry entry and in the errata. Reports that turn out to be wrong are
answered with the evidence, not closed silently.
