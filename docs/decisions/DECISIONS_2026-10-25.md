# Decisions 2026-10-25 (Ross)

1. **Production trio test -> restricted-constant Johansen** ("yes to all"). Done: `johansen.py`, commit 8b44e622.
2. **Amendment 6** (monthly re-decided pool membership as a sensitivity arm) ("yes to all"). Prereg 357fd826, code
   8b44e622; chain `debug/_tmp_chain_a6_20261025.sh` queued on CachyOS.
3. **Paper framing: one paper, one claim** ("approve, yes to all"). The two papers merge around: with point-in-time
   selection, executable P&L and a sealed holdout, cointegration pairs trading shows no robust edge on the ~44,700-symbol
   universe, and the screen finds barely more pairs than a correlation-matched null (closest prior work: Farago &
   Hjalmarsson 2019, JFQA). Contributions: pipeline-level placebo (E1), correlation-matched null at scale (N14),
   pre-registered sealed PIT test (Amendments 5/6), edge accounting. The discovery-regime pillar (lead paper section 5)
   becomes a short "claims that did not survive" section; section 7 supporting findings move to an appendix except SPAC
   NAV clustering; PAPER.md's legacy per-pair diagnostics are archived. Drafting starts after E1 and N14 v2 land and
   pass independent review; if E1 shows the pipeline cannot recover planted pairs, the claim becomes "no power" and is
   stated first. Novelty is checked with targeted Scholar/SSRN queries before it is claimed (first pass: Sonnet web
   search, abstracts only).
4. **Edge accounting** ("approve, yes to all"). Design `docs/EDGE_ACCOUNTING_DESIGN_2026-10-25.md` (2e40275a, before
   any result), code e256a734, chain `debug/_tmp_chain_edge_20261025.sh` after Amendment 6.
