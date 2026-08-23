# Instruction Audit — 2026-08-23

Full originals backed up in this folder (`CLAUDE.md.pre-audit-backup.md`) and in
`~/.claude/projects/C--Users-RossW-Projects-CAMARF/memory/archive_2026-08-23/`. Nothing was
permanently deleted — everything below still exists in those two locations.

## Method

For every discrete instruction found in `CLAUDE.md`, the 3 skill files, the 6 agent files, the
hook, and the 8 memory files, I asked:

1. Would I already do this without being told (covered by my own default behavior or by live
   tooling — e.g. the skill-listing system-reminder now auto-describes what each skill does)?
2. Is it correcting a weakness I no longer have (an obsolete/stale correction)?
3. Does it conflict with, or duplicate, something else I've been told?

**A "yes" to any question → removed/archived.** Only rules that were "no" on all three —
genuinely non-default, still relevant, and not stated anywhere else — survived into the rebuilt
`CLAUDE.md`.

## What was removed and why

### CLAUDE.md — "Claude Behavioral Guidelines (Karpathy method)" section — REMOVED IN FULL
"Simplicity first" and "Surgical changes" are near-verbatim duplicates of my own base system
prompt ("Don't add features... beyond what the task requires," "Prefer editing existing files,"
"Don't 'improve' adjacent code"). "Think before coding" and "Goal-driven execution" are
generic project-management advice I already follow, and are restated more specifically in
"Working Style" below. Q1 = yes for all four → redundant with default behavior.

### CLAUDE.md — "Recommended Plugins / Tools" section — trimmed from ~1,050 words to 3 lines
Almost every entry ("here's what `/code-review` does," "here's what STORM is for") is now
auto-surfaced every session by the harness's own skill-listing system-reminder, which already
carries each skill's description and trigger conditions. Q1 = yes for the great majority of
this section. Kept only the 3 items that are genuinely CAMARF-specific *policy* the generic
descriptions don't carry: run the 5 council lenses together (not alone), run `/code-review`
after nontrivial pipeline-file changes, and don't install `ponytail` (conflicts with this
project's verify-everything discipline).

### CLAUDE.md — "Data Test Range & Reproducibility" and "Current State" sections — moved out
These are project *status/history*, not instructions — and CLAUDE.md's own opening line already
says `Development.md` is "the canonical project memory" and this file is only "the fast
orientation layer." Duplicating ~2,500 words of session-by-session results here works against
that stated design and goes stale fast (`project_status.md` in memory, below, is a direct
casualty of exactly this — it still says "23 confirmed pairs" from Session 25, superseded by
Session 31's 182-pair PIT-safe set). Kept a single pointer to `Development.md` / `docs/HANDOFF.md`
/ `PAPER.md` instead of inlining the numbers. This isn't a Q1/Q2/Q3 call (it's not an
instruction) but it's the single biggest word-count cut, so it's logged here for visibility.

### CLAUDE.md — "Working Style" — de-duplicated, not cut
Every substantive rule here survived (verify-before-done, one-fix-not-three, stuck-after-3,
distrust-summaries, honesty-over-agreeableness, comparison-arm-before-prod, buy-in-before-new-
methodology). "Don't curse, keep it direct" was folded into the one-fix-not-three rule — it
was restating the same "no hedging, no menus" preference a second time.

### Memory — `feedback_code_patterns.md` — ARCHIVED IN FULL (redundant)
Every rule in this file (python.exe path, `connect=False`, GapFlag, `_clean_close` return type,
no bandaid fixes, don't silently cache empty) is already stated in CLAUDE.md's "Non-Negotiable
Architecture Rules" or "Known-Resolved Issues." Since CLAUDE.md loads every session regardless,
this file added nothing and was a second copy to drift out of sync. The two genuinely useful
facts not already in CLAUDE.md (`_clean_close` returns `ndarray`; don't import `data_ibkr`
directly, use `ibkr_supplement_reader`) were folded into CLAUDE.md's Known-Resolved-Issues list.

### Memory — `feedback_comparison_before_prod.md` — ARCHIVED (merged)
Restates CLAUDE.md's "comparison arm before production" rule with historical precedent
(coint_frac_override, HRP vs risk-parity) as the "why." The rule itself is now stated once,
concisely, in the rebuilt CLAUDE.md; the precedent examples are historical detail that belongs
in Development.md, not a standing rule file.

### Memory — `feedback_working_style.md` — ARCHIVED (content promoted, not lost)
5 of its 9 rules were pure duplicates of CLAUDE.md (no-menus, buy-in-before-new-concepts,
verify-before-done, stuck-after-3, use-latest-run-logs, don't-curse). The 3 genuinely new,
non-redundant rules it held — **one agent at a time, never parallel dispatch**; **findings from
a sweep become a comparison arm before touching production code**; **self-check against known
bug classes before running a new script** — did not exist in CLAUDE.md at all and are real,
Ross-stated standing corrections. These were promoted into the rebuilt CLAUDE.md rather than
left only in memory (which is more fragile / easier to lose track of than the file read every
session).

### Memory — `feedback_autonomous_progress.md` — ARCHIVED (mostly redundant)
This session's own "Auto Mode Active" system-reminder now states almost the same thing
platform-wide ("bias toward working without stopping for clarifying questions... keep going").
The CAMARF-specific nuance (finish other list items before circling back to a blocker) was
folded into one line in the rebuilt CLAUDE.md rather than kept as a full memory file.

### Memory — `feedback_pair_confirmation_rigor.md` — KEPT, promoted into CLAUDE.md
Genuinely CAMARF-specific methodological instinct (question pair-*selection* criteria, not just
strategy, when backtests are weak) that led directly to finding BUG-D112. Not default LLM
behavior, not stated elsewhere, no conflicts. Promoted into the rebuilt CLAUDE.md as one line;
archived as a standalone memory file since it's now covered there.

### Memory — `project_pit_backtest_priority.md` — KEPT, promoted into CLAUDE.md
Same treatment: genuinely non-derivable priority (realistic capital-constrained portfolio PIT
result over per-pair backtest), promoted into CLAUDE.md, archived as a standalone file.

### Memory — `project_status.md` — ARCHIVED (stale, not just redundant)
Frozen at Session 25 (2026-07-01): "23 confirmed pairs," Sharpe 5.29/5.24. CLAUDE.md's own
Session 31 entries already superseded this (182-pair PIT-safe set, very different headline
Sharpe numbers, and the 23-pair framing was explicitly retracted). Q2 = yes (this is exactly
"correcting/informing from a state that no longer holds") — kept as-is it's actively
misleading, not just unused. Archived, not deleted, per your standing "never delete" rule.

### Memory — `user_profile.md` — ARCHIVED (redundant)
Its "who Ross is" paragraph duplicates CLAUDE.md's project-identity section (MFE applications,
sole developer). Its "knowledge level / interaction style" paragraph duplicates the rebuilt
Working Style section almost line for line (no menus, direct/technical, wants buy-in on new
methods). No unique content survived independent of what's now in CLAUDE.md.

### Skills / agents / hooks — reviewed, none archived
- `diagnose-run-log`, `premortem`, `verify-new-module` (skills): each is opt-in (invoked
  explicitly, not loaded as a standing rule) and encodes a real, non-obvious CAMARF-specific
  procedure I would not reconstruct on my own. Kept as-is. Minor note: `verify-new-module`
  overlaps partially with the generic `superpowers:verification-before-completion` skill — not
  worth removing since it's opt-in and the CAMARF version adds specific detail (Development.md
  write-up requirement) the generic one doesn't have.
- `guard_manifest.py` (hook): kept — this is a *mechanical* backstop, not a behavioral rule I
  "carry." Its own justification is that the behavioral instruction alone (documented in
  CLAUDE.md since BUG-D63) already failed to prevent a recurrence once via a different script.
  A rule I've already been told once and still violated fails Q1 in the opposite direction — I
  would *not* reliably avoid this without a hard block, so the mechanism stays regardless of
  what CLAUDE.md says.
- 6 council/adversarial agent files: kept as-is — each encodes a distinct review lens used only
  at deliberate milestones, non-default, no conflicts between them (independence from each
  other is the entire point).
- `settings.local.json` permission allow-list and the two graphify PreToolUse hooks: out of
  scope for this audit. These aren't instructions I follow, they're accumulated tool-permission
  grants and a separate plugin's own automation — not something this 3-question test applies to.

## Stats

| | Before | After |
|---|---|---|
| Discrete behavioral/procedural rules (CLAUDE.md + memory, deduplicated count) | ~63 rule-atoms across 2 systems, with real duplication (e.g. the data.py/IBKR boundary rule stated 3×, GapFlag 2×, "verify before done" 2×, "use latest_run logs" 3×) | **24** rules, each stated exactly once |
| `CLAUDE.md` word count | 7,374 | ~2,050 (see rebuilt file) |
| Active memory files | 8 (1 index + 7 content) | 1 (index only, near-empty — see below) |
| Memory word count (7 content files) | ~2,450 | 0 (all archived; genuinely new content promoted into CLAUDE.md instead) |

Going forward: memory stays empty by default. Per your instruction, a rule only gets added back
to memory (or to CLAUDE.md) when you correct the same mistake twice — a single correction gets
noted in the moment but isn't promoted to a standing rule on the first occurrence.
