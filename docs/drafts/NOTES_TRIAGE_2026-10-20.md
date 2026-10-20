# Triage of Ross's notes: CAMARF items (2026-10-20)

Ross: "read through and see if we should do it" (health items excluded). 133 CAMARF items
(`notes_triage_items_2026-10-20.md`). Status was mapped by a read-only Sonnet search, spot-checked by hand (one
correction: item 64, compounding, IS built -- `portfolio_sim.py:493` sizes on current equity).

## The one thing that matters most

**About 92 of the 133 items are already built or done** (built 67, docs/process 26). But almost every built
comparison arm ran before the 2026-10 fixes (WRDS priority, point-in-time pools, the PIT spread fix, the strict
engine). The claims evaluation already CUT those old arms from the papers unless re-run. So the bottleneck is not new
concepts. It is re-running the ones that feed a claim on the new chain's pools.
**Recommendation:** add no new concept until the chain finishes and the 150 central claims are re-derived; then
re-run, in this order, only the built arms a paper cites; then the new arms below.

## Open items: one recommendation each

### Do (after the chain), as comparison arms or paper work
| # | Item | Why |
|---|---|---|
| 55/71 | Paper section comparing each finding with the literature (agrees / disagrees / answers an open question) | High value for both audiences; uses the re-derived numbers |
| 65 | Paper in impersonal academic style: no "Ross", no "Option A", no first/second person (PAPER.md has 13 "Ross") | Required for a submittable paper; do at the redraft, with 67 |
| 81 | report.py: PIT capital-constrained portfolio vs buy-and-hold S&P 500, with alpha and beta | Cheap, the honest benchmark a reader asks for first |
| 3 | One heat map: risk-sizing method x strategy on the PIT capsim (the arms exist separately) | Cheap once the arms are re-run; DSR counts each cell as a trial |
| 91 | Statistical jump model regimes (Shu, Yu & Mulvey 2024; Bemporad et al. 2018) vs the HMM labels | Directly tests the regime-of-discovery claims' regime labels; concept-level, needs your yes |
| 131 | Hawkes-process clustered null (already scheduled) | Keeps the clustering claims honest |
| 132 | TimesFM arm (approved E10/E11) | Already approved; queued |

### Skip, with the reason (push back)
| # | Item | Reason |
|---|---|---|
| 90 | Heikin-Ashi candles | A smoothed transform of the same OHLC; adds no information to close-based cointegration and adds lag |
| 120 | Synthetic Monte Carlo bars from the higher timeframe | Synthetic bars carry no market information; useful only as a null, which the D11 design already covers |
| 86/127 | Apply every concept to every metric | Each extra metric is another trial in the deflated Sharpe; untargeted it guarantees false discoveries. Only pre-registered hypotheses |
| 133 | Area under vol-standardized metrics / monotone convergence | No hypothesis yet; tell me what it should predict and I will scope it |
| 18 | Prime brokerage data | Not available free; FINRA short interest (data_finra.py) is the stand-in |
| 40 | Real-time standing measurement | Needs a live strategy; nothing has survived the holdout yet |
| 57 | Karpathy autoresearch | An automated experiment loop multiplies trials without the verify step this project requires |
| 83 | Steinberger graph workflow / Hermes agent | Workflow tooling; no research gain |
| 92 | MC option pricing with antithetic variates, efficient frontier | Textbook exercises; no CAMARF claim depends on them (the frontier-style optimizers were already compared, item 9) |
| 103, 106, 117, 118, 124 | awesome-systematic-trading, hf mito0o852, public-apis, prompt-master / playwright / serena / wshobson, agent-skills / ian-xiaohei / arXiv 2603.28052 / ponytail | Nothing in them that the project lacks; ponytail already rejected (conflicts with verify-everything) |
| 15/19/22/89 | Options surface, open interest, dealer gamma, vanna/charm, TAQ intraday | **Checked 2026-10-20 (WRDS job 34):** the subscription reads only samples -- OptionMetrics `optionmsamp_us` (2014) / `_europe` (2013), TAQ `taqmsamp` (2 days, Oct 2021) and `taqsamp_all` (one week, Jan 2008); full `optionm` / `taqmsec` / `taqm_*` return "insufficient privilege". Not buildable without a subscription change (free-data rule). CBOE library is readable (indices, not chains) |
| 20 | Donchian channels as ML features | The ML gate first has to show any signal on PIT pools (PAPER-161..163); add features after that, not before |

### Need your input (questions batch)
1. **21 "Johns Hopkins HLPPL" and 29 "Singha, hidden order in trades":** neither reference could be located (Development.md:6071, 6144). Do you have the citation or link?
2. **91 jump-model regimes** as a comparison arm against the HMM regime labels: yes / no?
3. **67 "market structure in every claim":** I propose one extra field in each claims-registry entry ("market-structure reading: what about market structure would make this claim fail"), rather than a paragraph per claim in the paper. Agree?
4. **113 GitHub About text:** proposed "Statistical-arbitrage research framework: point-in-time pair discovery on the WRDS/CRSP US market (~45,000 securities, delisted included), with every claim registered, re-derived and open to attack." Set it with `gh repo edit` -- yes / edit?
5. **110 model / effort:** keep Opus 5.5 for this project (code review and claim verification are where errors are expensive); searches stay on Sonnet. OK?

### Notes on items the search marked built but that need a caveat
- 31 universe: NASDAQ, Russell 2000 and Dow members are already inside the CRSP full-market universe; index
  membership adds nothing for discovery. Asia/London sessions come via Compustat Global (daily, USD).
- 64 compounding: built (current-equity sizing in portfolio_sim.py); the search missed it.
- 75 KO/PEP: tested (Development.md:13847); on CRSP, full-sample p = 0.11, last 5 years 0.96 -- not cointegrated in
  log prices under the production test; episodic periods are the open question, answered by the episodic screen.
- 89 TAQ: "TAQ unlocked" turned out to be the sample libraries only (job 34) -- if your account page shows a full TAQ
  entitlement, the library name differs from taqmsec / taqm_YYYY and I need it.
