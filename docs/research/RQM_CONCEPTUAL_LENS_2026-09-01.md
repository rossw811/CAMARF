# Relational Quantum Mechanics as a research lens for CAMARF — findings, 2026-09-01

**Origin**: Ross asked, early in the 2026-08-23/28 session (recovered from the browser transcript
after two Windows restarts — see `docs/HANDOFF.md`), to use Rovelli's Relational Quantum Mechanics
("Helgoland") as a conceptual lens "wherever we can integrate concepts from those for research and
testing." That request sat unactioned. This is the real follow-through: RQM's actual formal
postulates (not the popularized "everything is relative" gloss), checked against what CAMARF has
already built and found, to separate genuine structural analogy from decorative metaphor.

**Discipline used here, stated up front**: financial writing borrowing physics language ("quantum
finance," "market entanglement") is a well-documented pattern for dressing up ordinary statistics in
false authority. Nothing below claims quantum mechanics *causes* or *explains* market behavior. The
claim is narrower and checkable: RQM is fundamentally a theory about **what a fact about a system's
state is allowed to mean** — and that specific question turns out to line up with three things CAMARF
has already learned the hard way through its own bug history, independently of any physics framing.
Where a postulate doesn't map to something real, that's stated plainly rather than stretched.

## The actual postulates (Rovelli & Adlam's formulation, verified via arXiv, not the pop-sci gloss)

- **RQM-1 (Relative facts)**: an event/fact can happen *relative to* a physical system — there is no
  observer-independent state.
- **RQM-2 (No hidden variables)**: unitary QM is complete. *(No CAMARF analogue — this is a claim
  about physical completeness with no finance-domain counterpart. Skipped below.)*
- **RQM-3 (Relations are intrinsic)**: the relation between two systems A and B is independent of
  anything outside A and B's own perspectives.
- **RQM-4 (Relativity of comparisons)**: comparing two different systems' "accounts" is meaningless
  except via a third system relative to which the comparison is made.

Source: Adlam & Rovelli's axiomatization, cross-checked against the Stanford Encyclopedia of
Philosophy's RQM entry and the original 1996 Rovelli paper (arXiv:quant-ph/9609002).

## Where this is a genuine structural match, not decoration

### 1. RQM-1 ↔ CAMARF's own "unwarranted confidence" thesis (already proposed, independently)

This is the strongest match, and it isn't a coincidence worth dressing up — it's the same idea
arrived at twice, once empirically and once philosophically. The paper reframe already sitting
unanswered in `docs/HANDOFF.md` (proposed 2026-08-28, still awaiting your reaction) argues that all
seven of `PAPER_MAGNITUDE.md`'s findings are cases where a fact was mistaken for **absolute** when it
was only ever **relative to a specific measurement**: a raw p-value relative to one test among
thousands, a whole-history confirmation relative to a lookahead-contaminated window, a full-history
screen's tradeability relative to a static rather than point-in-time universe. RQM-1's formal content
— *a fact about a system's state only ever holds relative to another system, never absolutely* — is a
precise, checkable restatement of that same thesis. This isn't "physics inspiring finance"; it's the
same logical structure recognized in two domains. **Recommendation: if you accept the paper reframe,
RQM-1 is a legitimate one-paragraph framing device for the abstract/§11** ("a cointegration finding is
a fact relative to a specific test, window, and universe — never a property of the pair itself"), not
a separate research program. Cite it as an analogy, not a method.

### 2. RQM-3 ↔ a real, testable, currently-unasked methodology question

This is the one genuinely new research question this lens produces, not just a repackaged existing
result. RQM-3 says the relation between A and B must be independent of anything outside A and B's own
perspectives — no third system's information should leak into what's meant to be a purely pairwise
fact. CAMARF already has a script that does exactly the kind of thing RQM-3 would flag:
`research/sector_restricted_fdr_rescan.py` **restricts the candidate pool to same-GICS-sector pairs
only, shrinking the multiple-testing burden m, then applies one standard FDR correction to that
smaller pool** (checked directly against the actual source — it's a pool restriction, not a
per-sector-separate correction; corrected here after an earlier draft of this document described it
imprecisely). Either way, the same RQM-3 concern applies: a pair's confirmed status now depends on
*how many other same-sector candidates happened to exist*, i.e. a fact about a third system (the
sector's own candidate density) has been folded into what's presented as evidence about the pair
alone.

**Concrete, checkable question this motivates**: does the same-sector restriction change which pairs
survive FDR *because sector identity is doing real work*, or would *any* equally-sized restriction of
the candidate pool — chosen at random, with no economic meaning — produce a similarly different
survivor set just from shrinking m? A cheap diagnostic: draw many random restrictions of the exact
same size as the real same-sector-restricted pool (same m), re-run the same FDR methods on each, and
check whether the real same-sector result's survivor count sits inside or outside that random null's
typical range. If sector-restricted lands well inside the random null's range, "same-sector" isn't
doing anything sector-specific — it's just an m-reduction effect in disguise, a real methodological
finding either way. If it sits clearly outside, that's evidence sector identity carries real signal.
**This has never been checked.** It's a small, cheap, well-scoped comparison-arm candidate — exactly
the shape of thing `CLAUDE.md`'s "build it as a comparison arm, discuss, then decide" rule wants.
**Not building this without your go-ahead** — flagging it as the one concrete deliverable from this
whole RQM detour.

### 3. RQM-4 ↔ the magnitude-number incommensurability lesson (already learned, now has a name)

The 454/182/29 "magnitude number" confusion (`docs/HANDOFF.md`'s 2026-08-28 entry) was exactly RQM-4's
mistake: comparing three pair-counts from different methodologies (pre-fix episodic, post-fix
episodic, static full-history) as if they were directly comparable numbers, when they were actually
incommensurable without a shared frame (same universe, same date range, same method). The fix already
applied — pair the fresh episodic count against the fresh static count from the *same* corrected
universe as the real headline comparison, retire the rest to a footnote — is precisely RQM-4's
prescription: comparisons need a third, shared reference frame, or they're not really comparisons at
all. No new action here; it's already fixed. Worth noting only because it means this project has
already been *doing* RQM-4 correctly without naming it, which is a small piece of independent
corroboration that the lens isn't empty.

## Where it does NOT apply — stated plainly rather than stretched

- **No literal quantum formalism belongs anywhere in CAMARF.** Superposition, entanglement, and
  measurement collapse are not stand-ins for correlation, cointegration, or volatility clustering.
  Anywhere this project's own scripts already use "relative" framing (`inverse_polarity.py`'s
  percentile-rank-vs-own-history metrics, `trig_convergence.py`'s phase-synchronization work) that's
  because those are the right statistical tools for the job, not because they're secretly RQM in
  disguise — `trig_convergence.py`'s own docstring is explicit that Pearson correlation was always
  `cos(θ)` and PLV was always the trig-identity form of phase sync, independent of any RQM framing.
  Retroactively relabeling existing, already-justified methods as "RQM-inspired" would be exactly the
  kind of borrowed-authority decoration this document is trying to avoid.
- **RQM-2 (no hidden variables) has no finance analogue** and isn't force-fit into one above.
- This is **not a new pillar, not a new section, not a new backtest arm.** It's a framing device for
  the already-proposed reframe (item 1) plus one small, cheap, optional methodology check (item 2).
  Treating it as more than that would repeat the exact mistake the reframe itself is about: mistaking
  a philosophically satisfying story for something that's earned load-bearing status in the paper.

## Bottom line / what actually needs a decision from you

1. **Nothing here should be built without your say-so** — this document is the "explain it, get buy-in
   before building" step `CLAUDE.md` requires for new methodology.
2. If you want it, item 1 (RQM-1 as an abstract/§11 framing sentence) is essentially free — it's the
   same reframe already sitting in `docs/HANDOFF.md`, just with a citation-worthy name attached.
3. Item 2 (the sector-restricted-FDR comparison arm) is the one real, new, cheap research task this
   produced. Say the word and it gets scoped properly and built as a comparison arm, not wired into
   production.
4. Everything else was either already true independent of RQM (item 3) or explicitly ruled out above.

Sources:
- [Relational Quantum Mechanics (Stanford Encyclopedia of Philosophy)](https://plato.stanford.edu/entries/qm-relational/)
- [Relational Quantum Mechanics, Rovelli 1996 (arXiv:quant-ph/9609002)](https://arxiv.org/pdf/quant-ph/9609002)
- [Relational Quantum Mechanics and Contextuality, Adlam (arXiv:2308.08922)](https://arxiv.org/pdf/2308.08922)
