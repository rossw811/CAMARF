# Citation-Accuracy Audit: PAPER.md, PAPER_MAGNITUDE.md, README.md (2026-09-26)

Read-only audit. No existing file was modified. Scope: every author-attributed bibliographic citation in
`PAPER.md`, `PAPER_MAGNITUDE.md` and `README.md`, plus the code-level items the audit brief named
explicitly (BH/PRDS, Reimers, Costa MSE, QRF, sequential bootstrap, French 1980, Kyle-Obizhaeva).

## Method and limits (read first)

- **Bibliographic checks** used the Crossref REST API (`api.crossref.org/works/<DOI>` and
  `query.bibliographic`), cross-checked against OpenAlex (`api.openalex.org/works/doi:<DOI>`) and, where
  available, Semantic Scholar, JMLR's own page, and the installed scikit-learn source. The DOI shown in the
  URL column is the record I checked.
- **Claim-fidelity checks** used the published abstract (via OpenAlex/Semantic Scholar) where one was
  retrievable, plus the project's own code and `docs/CODE_REVIEW_2026-09-26.md` for items whose problem is
  in the implementation.
- **Limit:** WebSearch/WebFetch were unavailable this session (account spend limit), and no PDF library was
  available to read full texts. Where a claim depends on the body of a paper and not its abstract, it is
  marked **CANNOT-ASSESS** unless the point is canonical and the basis is stated. The one exception to
  that rule, Gatev et al.'s 12-month formation window, is labeled in the table and should get a full-text
  check before correction text is finalized.
- Status keys follow the brief. Bibliographic: CORRECT / MINOR ERROR / MAJOR ERROR / NOT FOUND /
  FABRICATION-RISK. Claim: FAITHFUL / OVERSTATED / MISATTRIBUTED / CANNOT-ASSESS (N/A = never cited in
  the text).

## Summary counts (74 distinct works)

| Bibliographic status | Count |
|---|---|
| CORRECT (incl. Grinold-Kahn, partially verified) | 61 |
| MINOR ERROR | 10 |
| MAJOR ERROR | 0 |
| NOT FOUND (Meucci 2009, Carver 2015, Hooker 1993: non-DOI outlets / index gap; none look fabricated) | 3 |
| FABRICATION-RISK | 0 |

| Claim-fidelity status (one status per work; GGR's worst status is used) | Count |
|---|---|
| FAITHFUL | 42 |
| OVERSTATED | 5 (plus the GGR P:1430 sentence, counted under GGR's MISATTRIBUTED) |
| MISATTRIBUTED | 9 in the paper files (plus 1 code-only: the BH-1995 PRDS docstring) |
| CANNOT-ASSESS | 12 |
| N/A (reference-list entry never cited in the text, or cut) | 6 |

Structural problems: **31 works cited in the text have no reference-list entry**, **5 reference entries are
never cited in the text**, AFML is listed twice (#7 and #21), and the paper's own sourcing statements
contradict each other (see the "Structural" section).

## Table

"P" = PAPER.md, "M" = PAPER_MAGNITUDE.md, "R" = README.md, "code" = a .py file (outside the paper, included
because the brief named it). "Ref#" = entry number in PAPER.md's reference list (lines 3451-3635). "no ref" =
cited in the text with no reference-list entry.

| # | Work | Where cited | Bibliographic status + fix | Claim fidelity + note | Verification URL |
|---|---|---|---|---|---|
| 1 | Engle & Granger (1987), Econometrica 55(2) 251-276 | P:155,256; Ref#1 (P:3460) | CORRECT | FAITHFUL | https://doi.org/10.2307/1913236 |
| 2 | Vidyamurthy (2004), *Pairs Trading*, Wiley | P:221,265; Ref#2 | CORRECT (exists: in Krauss 2017's Crossref reference list) | CANNOT-ASSESS. P:221 puts **"the most cited work on cointegration-based pairs trading"** in quotation marks with no source; as written it reads like a quote from Vidyamurthy. Ref#2 says "described independently" but names nobody. Give a source (likely Krauss 2017) and verify the wording, or remove the quote marks. | https://api.crossref.org/works/10.1111/joes.12153 (reference list) |
| 3 | Gregory & Hansen (1996), J. Econometrics 70(1) 99-126 | P:155,270,454; R:102; Ref#3 | CORRECT | FAITHFUL | https://doi.org/10.1016/0304-4076(69)41685-7 |
| 4 | Hansen (1992), JBES 10(3) 321-335 | P:155,276; R:102; Ref#4 | CORRECT | FAITHFUL | https://doi.org/10.1080/07350015.1992.10509908 |
| 5 | Quintos & Phillips (1993), Empirical Economics 18(4) 675-706 | P:156,278; R:102; Ref#5 | CORRECT (issue (4) omitted, optional) | FAITHFUL | https://doi.org/10.1007/bf01205416 |
| 6 | Benjamini & Hochberg (1995), JRSS-B 57(1) 289-300 | P:291,606,2212; M:166,408,1109; Ref#6 | CORRECT | FAITHFUL in the paper. **Known issue (b), code only:** `research/bh_fdr_dependence_check.py:38-41` says the PRDS guarantee is "all BH's own 1995 proof covers". BH 1995 proves independence only. PRDS validity is **Benjamini & Yekutieli (2001), Theorem 1.2**. PAPER.md does **not** repeat this. M:1113 ("BH's independence-ish assumption") is vague but not wrong. Fix the docstring. | https://doi.org/10.1111/j.2517-6161.1995.tb02031.x |
| 7 | Benjamini & Yekutieli (2001), Ann. Statist. 29(4) 1165-1188 | M:1114,1820 (called "shared bibliography"); code | CORRECT at the level the text gives. **No ref entry in either paper**, although M:1819-1820 says it is in the shared bibliography. | FAITHFUL ("no assumption about dependence", "provably more conservative") | https://doi.org/10.1214/aos/1013699998 |
| 8 | López de Prado (2018), *Advances in Financial Machine Learning*, Wiley | P:393,2231,2583,2840,3196; Ref#7 **and** Ref#21 | CORRECT. Listed twice (#7 "Lopez", #21 "López"): merge them and cite chapters in the text. The chapter numbers used (Ch. 4 sample weights / sequential bootstrap, Ch. 15 strategy risk) match the book's structure, but the table of contents was not retrieved online this session. | Ch. 15 binomial Sharpe (P:2231): FAITHFUL. **Ch. 4 sequential bootstrap (P:2583-2606): OVERSTATED.** CODE_REVIEW R4.6 says uniqueness is computed against all n labels, not drawn set + candidate (AFML Snippet 4.5), so the "full sequential bootstrap" arm is roughly uniqueness-weighted resampling. R4.6 is UNVERIFIED; if confirmed, the §7.19 "+3.1pp" compares mislabeled arms. Ch. 7 purged CV: **not cited in any paper file** (ml.py has no purge/embargo, R2.3, but no paper sentence credits AFML Ch. 7). Meta-labeling/triple-barrier/CPCV/PBO (P:393): FAITHFUL. | Wiley ISBN 9781119482086 |
| 9 | Gatev, Goetzmann & Rouwenhorst (2006), RFS 19(3) 797-827 | P:320,1430,1883-1889,1922; M:95,266-270,1027; Ref#8 | CORRECT | P:320: FAITHFUL (abstract: 1962-2002, "up to 11%"; "~11%" should read "up to 11%"). **P:1430: OVERSTATED.** "Gatev et al. 2006 document substantial OOS decay" treats the whole-sample time decline as IS-vs-OOS decay. GGR's returns are already out-of-sample (trading period after formation), so they do not measure an IS/OOS gap. **M:95, M:266-270, M:1027: MISATTRIBUTED.** M says GGR treat pair selection "as a given input, computed once over full available history, and validate only the trading rule causally". GGR pick pairs over a rolling 12-month formation window that is strictly before each 6-month trading window, so their selection is itself point-in-time. Basis: GGR's methodology section, which is canonical but whose full text was not retrieved this session (the abstract only says pairs are matched on "historical prices"); confirm against the RFS text before finalizing the wording. The contrast §4 draws with GGR does not hold as stated. | https://doi.org/10.1093/rfs/hhj020 |
| 10 | Avellaneda & Lee (2010), Quant. Finance 10(7) 761-782 | P:334,452; Ref#9 | CORRECT | CANNOT-ASSESS for the figures (1.44 / 0.9 post-2002 / ETF 1.1): they match the widely quoted abstract, but no abstract was retrievable via API this session. Labeling 1.44 as "IS" (P:334) is misleading: these are backtest results, not in-sample fits. | https://doi.org/10.1080/14697680903124632 |
| 11 | Krauss (2017), J. Econ. Surveys 31(2) 513-545 | P:346,453; Ref#10 | CORRECT | OVERSTATED (minor). P:350 lists the fifth family as "ML-based". The abstract's fifth category is **"other approaches"** (ML is one member). The §2.4 table (P:453) already says "other", so P:350 is inconsistent with it. | https://doi.org/10.1111/joes.12153 |
| 12 | Hamilton (1989), Econometrica 57(2) 357-384 | Ref#11 only | CORRECT | N/A: never cited in the text | https://doi.org/10.2307/1912559 |
| 13 | Durbin & Koopman (2001/2012), OUP | Ref#12 only | CORRECT (2nd ed. confirmed on OUP/Crossref 2012) | N/A: never cited in the text | https://doi.org/10.1093/acprof:oso/9780199641178.001.0001 |
| 14 | Rabiner (1989), Proc. IEEE 77(2) 257-286 | Ref#13 only | CORRECT | N/A: never cited in the text | https://doi.org/10.1109/5.18626 |
| 15 | Engle (1982), Econometrica 50(4) 987-1007 | Ref#14 only | CORRECT | N/A: never cited in the text. Ref#14 also says "Engle's DCC already cited above", but Engle (2002) has **no** ref entry. | https://doi.org/10.2307/1912773 |
| 16 | Hansen & Seo (2002), J. Econometrics 110(2) 293-318 | P:2207; Ref#15 | CORRECT: can drop [TBD] | FAITHFUL | https://doi.org/10.1016/s0304-4076(02)00097-0 |
| 17 | Lo & MacKinlay (1988), RFS 1(1) 41-66 | P:2216; Ref#16 | CORRECT: can drop [TBD] | FAITHFUL | https://doi.org/10.1093/rfs/1.1.41 |
| 18 | Kupiec (1995), J. Derivatives 3(2) 73-84 | P:1377; Ref#17 | CORRECT | FAITHFUL | https://doi.org/10.3905/jod.1995.407942 |
| 19 | Christoffersen (1998), IER 39(4) 841-862 | P:1377; Ref#17 | CORRECT | FAITHFUL | https://doi.org/10.2307/2527341 |
| 20 | Grinold & Kahn (2000), *Active Portfolio Management* 2nd ed. | P:1248,1515,1532; M:1820; Ref#18 | CORRECT, partially verified. The 1st ed. is confirmed (JF 1996 review); the 2nd-ed. year 2000 is not in DOI indexes. | CANNOT-ASSESS. "BR_eff = N/(1+(N-1)ρ̄)" is attributed to Grinold-Kahn. The fundamental law (IR = IC·√BR) is theirs, but whether the equicorrelation breadth formula appears in the book could not be checked. Consider citing the formula's actual source, or calling it "equicorrelation effective breadth". | https://doi.org/10.2307/2329407 |
| 21 | Meucci (2009), "Managing Diversification", *Risk* | P:1515; M:1820; Ref#18 | NOT FOUND in Crossref/OpenAlex (a trade magazine; the SSRN DOI 10.2139/ssrn.1358533 returned 404). Not a fabrication risk (a well-known paper); add vol./pages (*Risk* 22(5)) once confirmed. | FAITHFUL (ENB from the eigenvalue/PCA diversification distribution) | Crossref query, no match |
| 22 | Carver (2015), *Systematic Trading*, Harriman House | P:1516; Ref#18 | NOT FOUND in DOI indexes (book). Not a fabrication risk. | FAITHFUL (IDM = 1/√(w'Rw)) | Crossref query, no match |
| 23 | Ledoit & Wolf (2004), "Honey, I shrunk…", JPM 30(4) 110-119 | P:1505,2292; Ref#19 | CORRECT as a citation | **MISATTRIBUTED.** Ref#19 and P:1505 say the implementation is `sklearn.covariance.ledoit_wolf`. That function implements the *other* 2004 Ledoit-Wolf paper, "A well-conditioned estimator for large-dimensional covariance matrices", *J. Multivariate Analysis* 88(2) 365-411 (identity-type target). "Honey" uses a constant-correlation target. Verified in the installed sklearn source `_shrunk_covariance.py:546-547`. Cite the JMVA paper. | https://doi.org/10.1016/s0047-259x(03)00096-4 |
| 24 | Engle & Ng (1993), JF 48(5) 1749-1778 | P:2224; Ref#20 | CORRECT | **OVERSTATED.** The adaptation (widening vs. narrowing as a stand-in for bad/good news) is disclosed. But the conclusion that "`garch_stop`'s symmetric design is **validated**" rests on code whose "narrowing" definition (`dz_{t-1}<0`, not `sign(dz) = -sign(z)`) forces the ratio toward 1 (CODE_REVIEW R8.1, CONFIRMED). The null is produced by the method, so the paper cannot claim validation. | https://doi.org/10.1111/j.1540-6261.1993.tb05127.x |
| 25 | Reimers (1992), Statistical Papers 33(1) 335-359 | P:2238; Ref#22 | CORRECT: can drop [TBD] | FAITHFUL at the paper's level of description ("degrees-of-freedom-corrected Johansen trace statistic"; the paper gives no formula). **Known issue (c), implementation:** `research/reimers_trio_correction.py:13,52` uses (T − n·k)/T with k = VECM `k_ar_diff`. Reimers' k is the VAR lag order **in levels** (= k_ar_diff + 1), so the correction is under-applied. At T in the thousands the factor is ≈0.997 either way, so "0/502 flip" is guaranteed by T and is not evidence (R8.8). The paper's hedge ("corrections are expected to matter least") is appropriate. Fix the docstring/code k. | https://doi.org/10.1007/bf02925336 |
| 26 | Hansen (1999), REStat 81(4) 594-607 | P:2247; Ref#23 | CORRECT | **OVERSTATED.** The method is described correctly (abstract: grid of nulls, no-rejection principle, valid near unity). But the implementation's grid is capped at ±0.999 and ρ̂±0.15, so the set can never contain 1. "Every confirmed pair's CI sits comfortably below 1" is true by construction, and PNC/ZION [0.9990, 0.9990] is a grid-edge artifact (R6.5, CONFIRMED). This defeats the specific property the citation is invoked for. | https://doi.org/10.1162/003465399558463 |
| 27 | Bertram (2010), Physica A 389(11) 2234-2243 | P:1994-1998,2253; Ref#24 | CORRECT | FAITHFUL (threshold maximizing expected return per unit time net of cost; first-passage-time framing). The basis is prior knowledge of the abstract, which was not retrievable via API. | https://doi.org/10.1016/j.physa.2010.01.045 |
| 28 | Getmansky, Lo & Makarov (2004), JFE 74(3) 529-609 | P:2256; Ref#24 | CORRECT | FAITHFUL as a citation. The implementation caveat (irregular exit-date series is not GLM's regular MA(2); no significance test, R7.13) should be disclosed. | https://doi.org/10.1016/j.jfineco.2004.04.001 |
| 29 | Kritzman & Li (2010), FAJ 66(5) 30-41 | P:2292; Ref#25 | CORRECT | FAITHFUL (Mahalanobis turbulence; LW shrinkage disclosed as a deviation) | https://doi.org/10.2469/faj.v66.n5.3 |
| 30 | Kritzman, Li, Page & Rigobon (2011), JPM 37(4) 112-126 | P:1494,3598; R:364 | CORRECT. **no ref**: add an entry. | FAITHFUL (the abstract confirms a fixed number of eigenvectors; the 1/5 fraction is from the body, not re-read) | https://doi.org/10.3905/jpm.2011.37.4.112 |
| 31 | Engle & Manganelli (2004), JBES 22(4) 367-381 | P:2296; Ref#26 | CORRECT | **OVERSTATED (mild), known issue (f).** The paper asserts "real time-varying risk that a constant VaR misses". The abstract says CAViaR's adequacy criterion is the **Dynamic Quantile (DQ) test**, which the implementation never runs. The exceedance rate is measured on the fitting data (R7.6). Drop the adequacy implication or add the DQ test. | https://doi.org/10.1198/073500104000000370 |
| 32 | Meinshausen (2006), JMLR 7(35) 983-999 | P:2301; Ref#27 | CORRECT (JMLR page confirms 7(35):983-999, 2006) | FAITHFUL at paper level (the paper reports only a null). **Known issue (k), code level:** `quantile_regression_forest.py:84` pools raw leaf values (tree influence ∝ leaf size) instead of Meinshausen's per-observation 1/leaf-size weights, while its docstring claims the weighting (R4.5). | https://jmlr.org/papers/v7/meinshausen06a.html |
| 33 | Friedman, Hastie & Tibshirani (2008), Biostatistics 9(3) 432-441 | P:2305; Ref#28 | CORRECT (online 2007, issue 2008) | FAITHFUL | https://doi.org/10.1093/biostatistics/kxm045 |
| 34 | Costa, Goldberger & Peng (2002), PRL 89(6) 068102 | P:2309; Ref#29 | CORRECT | **MISATTRIBUTED, known issue (d).** Costa et al. fix the tolerance r once from the **original** series' SD and reuse it at every scale. `multiscale_entropy.py:96` recomputes r = 0.2·std on each coarse-grained series (R8.4, CONFIRMED). That cancels the variance shrinkage MSE is built to measure: under Costa's method white-noise entropy **falls** with scale. P:2309's "rising toward the white-noise level" profile is a product of this variant, so it should not carry Costa's name. | https://doi.org/10.1103/physrevlett.89.068102 |
| 35 | Richman & Moorman (2000), AJP-Heart 278(6) H2039-H2049 | P:3369 (in-text), inside Ref#29 | CORRECT. Nested inside the Costa entry: give it its own entry. | FAITHFUL (SampEn m=2, r=0.2·SD) | https://doi.org/10.1152/ajpheart.2000.278.6.h2039 |
| 36 | Maillard, Roncalli & Teiletche (2010), JPM 36(4) 60-70 | Ref#30 only | CORRECT | N/A: the ERC result at P:2325-2328 does not cite it. Add the in-text citation there. | https://doi.org/10.3905/jpm.2010.36.4.060 |
| 37 | Pu, Roberts, Dong & Zohren (2023), arXiv:2308.11294 | P:2340; Ref#31 | CORRECT | **MISATTRIBUTED (minor).** P:2340 and Ref#31 say CAMARF ran a simplification of "the paper's full graph neural network". The abstract describes "a linear and interpretable graph learning model"; there is no GNN. | https://arxiv.org/abs/2308.11294 (Semantic Scholar record) |
| 38 | Blitz, Hanauer, Honarvar, Huisman & van Vliet (2023), FAJ 79(4) | P:2346; Ref#32 | **MINOR ERROR: pages are 96-117, not 74-95.** | **MISATTRIBUTED.** Ref#32 and P:2346 frame the test as the paper's "reversal + **day-of-week** seasonality", "consistent with the literature's own characterization". The abstract's seasonality signal is **monthly** seasonality, not day-of-week. Separately, the code's Monday dummy is shifted one row and actually tests Tuesday (R8.6, UNVERIFIED). | https://doi.org/10.1080/0015198x.2023.2173492 |
| 39 | Clegg & Krauss (2018), Quant. Finance 18(1) 121-138 | P:282,455,467 | CORRECT. **no ref**: add an entry. | FAITHFUL (abstract: state space, MLE, S&P 500 1990-2015, "more than 12%" after costs) | https://doi.org/10.1080/14697688.2017.1370122 |
| 40 | Phillips & Ouliaris (1990), Econometrica 58(1) 165-193 | P:294 | CORRECT. **no ref**: add an entry. | **MISATTRIBUTED.** P:294-296 says PO's Z_α/Z_t use "FM-OLS residuals" and are "more powerful than EG in small samples". PO's tests are residual-based on **OLS** cointegrating residuals (FM-OLS is Phillips-Hansen 1990). The abstract makes no small-sample power claim over EG; it reports ADF and Z_t as asymptotically equivalent, and it is Z_α and the new tests, not Z_t, that diverge faster. | https://doi.org/10.2307/2938339 |
| 41 | Hakkio & Rush (1991), JIMF 10(4) 571-581 | P:300 | **MINOR ERROR: the title is "Cointegration: How Short Is the *Long* Run?"**, not "…the Short Run?". Add pages 571-581. **no ref**. | FAITHFUL (span, not frequency, drives power) | https://doi.org/10.1016/0261-5606(91)90008-8 |
| 42 | Hooker (1993) | P:306 | NOT FOUND. A Crossref bibliographic query for "Hooker 1993 testing for cointegration power versus frequency of observation" returned only Lahiri-Mamingi and Otero-Smith. Believed to be Economics Letters 1993 but unconfirmed. **no ref**. | CANNOT-ASSESS | Crossref query, no match |
| 43 | Lahiri & Mamingi (1995), Econ. Letters 49(2) 121-124 | P:306 | CORRECT. **no ref**. | FAITHFUL (title confirms the power-vs-frequency debate) | https://doi.org/10.1016/0165-1765(95)00668-6 |
| 44 | Otero & Smith (2000), Econ. Letters 67(1) 5-9 | P:306 | CORRECT. **no ref**. | FAITHFUL | https://doi.org/10.1016/s0165-1765(99)00245-1 |
| 45 | Do, Faff & Hamza (2006), "A New Approach to Modeling and Estimation for Pairs Trading" | P:328,451,1932 | MINOR ERROR: venue omitted. Exists as *Proceedings of the 2006 FMA European Conference* (confirmed in Krauss 2017's reference list); not in DOI indexes. **no ref**. | CANNOT-ASSESS, **high priority.** The full text could not be retrieved. Two claims look doubtful. (1) "Introduces the OU process model for the spread": Elliott et al. (2005) already modeled the spread as a mean-reverting Gaussian Markov chain (discrete OU). DFH's model is a "stochastic residual spread" state-space model. (2) "Cointegration + OU outperforms pure distance on a risk-adjusted basis" is used at P:1932 as external corroboration of CAMARF's result. Verify this against the paper; the proceedings version is not known to contain such a head-to-head comparison. | https://api.crossref.org/works/10.1111/joes.12153 (reference list) |
| 46 | Elliott, van der Hoek & Malcolm (2005), Quant. Finance 5(3) 271-276 | P:342,451 | CORRECT. **no ref**. | **MISATTRIBUTED.** P:342 says "Bayesian optimal stopping" and the table says "theoretically optimal stopping rule". The abstract describes a mean-reverting Gaussian Markov chain observed in Gaussian noise (Kalman/EM calibration), with trades set by comparing model predictions to later observations. It contains no Bayesian optimal-stopping derivation. | https://doi.org/10.1080/14697680500149370 |
| 47 | Do & Faff (2010), FAJ 66(4) 83-95 | P:352,2141 | CORRECT (add pages). **no ref**. | CANNOT-ASSESS for the specifics (0.86%→0.24%/month; "explicitly testing and rejecting capital-crowding"). The abstract confirms only the "continuing downward trend". It also says the strategy "performs strongly during periods of prolonged turbulence", which is relevant to §7.12 and not mentioned there. | https://doi.org/10.2469/faj.v66.n4.1 |
| 48 | Khandani & Lo (2007 WP / 2011 JFM 14(1) 1-46) | P:373 | MINOR ERROR: no year/venue given. **no ref**. | CANNOT-ASSESS. The abstract (JFM version) covers deleveraging and market-making withdrawal; the explicit 1998 parallel is in the body and was not re-read. | https://doi.org/10.1016/j.finmar.2010.07.005 |
| 49 | Kakushadze (2020), "Quant Bust 2020", SSRN 3570280 | P:374 | MINOR ERROR: no year/venue. **no ref**. | CANNOT-ASSESS. The abstract confirms dollar-neutral stat-arb "suffered substantial losses". The added claim that "other quant strategy categories were unaffected or profitable" is not in the abstract. | https://doi.org/10.2139/ssrn.3570280 |
| 50 | Krauss, Do & Huck (2017), EJOR 259(2) 689-702 | P:384,456 | CORRECT. **no ref**. | CANNOT-ASSESS for "0.45%/day" (no abstract via API; matches the commonly quoted figure, *prior to* transaction costs, which P:386 says as "raw"). | https://doi.org/10.1016/j.ejor.2016.10.031 |
| 51 | Bailey & López de Prado (2014), JPM 40(5) 94-107 | P:400,1301; M:1171; R:362 | CORRECT (add pages 94-107). **no ref** in PAPER.md, although it is the basis of §6.7. | FAITHFUL, known issue (g); the formula was verified correct per CODE_REVIEW Group 5. Minor: the name "False Strategy Theorem" comes from López de Prado's later work, not the 2014 paper, which states it as a proposition on the expected maximum Sharpe. | https://doi.org/10.3905/jpm.2014.40.5.094 |
| 52 | Bailey, Borwein, López de Prado & Zhu, "The Probability of Backtest Overfitting", J. Comput. Finance | M:270, M refs | MINOR ERROR: the year is given as "2014/2016" (SSRN 2013; journal online Sept 2016). The "20(4), 39-69" volume/pages could **not** be confirmed (the Crossref/OpenAlex records carry no volume/issue). Use a single year and confirm vol./pages. | FAITHFUL (PBO as a selection-induced overfitting probability; the abstract confirms the CSCV framework) | https://doi.org/10.21314/jcf.2016.322 |
| 53 | Harvey, Liu & Zhu (2016), RFS 29(1) 5-68 | P:311,413 | CORRECT. **no ref**. | FAITHFUL (abstract: t > 3.0; "most claimed research findings… likely false"). Minor: "factor zoo" is Cochrane's (2011) phrase, not HLZ's. | https://doi.org/10.1093/rfs/hhv059 |
| 54 | Engle (2002), "Dynamic Conditional Correlation…", JBES 20(3) 339-350 | P:425,1206,457,3541 | MINOR ERROR: title truncated (full: "Dynamic Conditional Correlation: A Simple Class of Multivariate Generalized Autoregressive Conditional Heteroskedasticity Models"). **no ref**, although Ref#14 claims it is "already cited above". | FAITHFUL | https://doi.org/10.1198/073500102288618487 |
| 55 | White (2000), Econometrica 68(5) 1097-1126 | P:431-440, 458, 497, 1236-1296 | CORRECT. **no ref**. | **MISATTRIBUTED, known issue (a).** White's Reality Check tests "the null hypothesis that the **best model** encountered in a specification search has no predictive superiority over a given benchmark" (abstract). It bootstraps the max over N models of a **null-centered (demeaned)** performance statistic. CAMARF's test is one series, has no benchmark, no max over models, and no demeaning, so its null is centered on the realized Sharpe and p≈0.5 whatever the skill (CODE_REVIEW S5, CONFIRMED: skill-less median p=0.503, Sharpe-6.1 data p=0.498). The §2.4 table's "Correct p-value under multiple testing" claims a property the implementation does not have. P:497 calls it "White's **permutation** test"; White's RC is not a permutation test. The reported p=0.559/0.546 values cannot be used as evidence either way. | https://doi.org/10.1111/1468-0262.00152 |
| 56 | Politis & Romano (1992), circular block bootstrap | P:435,1257 | MINOR ERROR: no year/source (Politis & Romano 1992, "A circular block-resampling procedure for stationary data", in *Exploring the Limits of Bootstrap*, Wiley, 263-270; not found in Crossref). **no ref**. | FAITHFUL (correct originator of the circular block bootstrap; the problem is in how it is used, see #55) | Crossref query, no match |
| 57 | Granger & Newbold (1974), J. Econometrics 2(2) 111-120 | P:727 | CORRECT. **no ref**. | FAITHFUL | https://doi.org/10.1016/0304-4076(74)90034-7 |
| 58 | Zivot & Andrews (1992), JBES 10(3) 251-270 | P:158,273,1855; R:100 | CORRECT. **no ref**. | FAITHFUL | https://doi.org/10.1080/07350015.1992.10509904 |
| 59 | Lou & Polk (2022), RFS 35(7) 3272-3302 | P:3401 | CORRECT (online 2021). **no ref**. | FAITHFUL as a disclosed adaptation (Lou-Polk's measure is abnormal return correlation among momentum stocks; CAMARF applies it to spread returns) | https://doi.org/10.1093/rfs/hhab117 |
| 60 | Brav & Lehavy (2003), JF 58(5) 1933-1967 | P:3228 | CORRECT. **no ref**. | FAITHFUL | https://doi.org/10.1111/1540-6261.00593 |
| 61 | Da & Schaumburg (2011), J. Fin. Markets 14(1) 161-192 | P:3228 | CORRECT. **no ref**. | CANNOT-ASSESS. The title ("**Relative valuation** and analyst target price forecasts") suggests a within-industry relative design, which would contradict P:3228's framing of it as a "STANDALONE single-name signal" unlike CAMARF's pairs-relative overlay. Check before relying on that contrast. | https://doi.org/10.1016/j.finmar.2010.09.001 |
| 62 | Lo (2002), FAJ 58(4) 36-52 | P:2979 | CORRECT. **no ref**. | FAITHFUL, known issue (h) (abstract: SE of the Sharpe ratio and serial-correlation adjustment) | https://doi.org/10.2469/faj.v58.n4.2453 |
| 63 | Schreiber (2000), PRL 85(2) 461-464 | P:2610 | CORRECT. **no ref**. | FAITHFUL | https://doi.org/10.1103/physrevlett.85.461 |
| 64 | Michaud (1989), FAJ 45(1) 31-42 | P:1503 | CORRECT. **no ref**, although P:1503 says "already cited above". | FAITHFUL | https://doi.org/10.2469/faj.v45.n1.31 |
| 65 | DeMiguel, Garlappi & Uppal (2009), RFS 22(5) 1915-1953 | P:1489,1503 | CORRECT. **no ref**. | FAITHFUL | https://doi.org/10.1093/rfs/hhm075 |
| 66 | López de Prado (2016), HRP, JPM 42(4) 59-69 | P:1484 | CORRECT. **no ref**. | FAITHFUL | https://doi.org/10.3905/jpm.2016.42.4.059 |
| 67 | Meinshausen & Bühlmann (2010), JRSS-B 72(4) 417-473 | P:3423 | MINOR ERROR: no year. **no ref**. | FAITHFUL | https://doi.org/10.1111/j.1467-9868.2010.00740.x |
| 68 | Akyildirim, Fabozzi, Goncu & Sensoy (2022), Ann. Oper. Res. 313(2) 1357-1371 | P:2271 | CORRECT (online 2021, issue 2022). **no ref**. | CANNOT-ASSESS (no abstract retrieved). The paper is about statistical arbitrage *in* jump-diffusion models; CAMARF uses it only as motivation for jump detection, which looks fine. | https://doi.org/10.1007/s10479-021-03965-w |
| 69 | Lee & Mykland (2008), RFS 21(6) 2535-2563 | M:1319,1820 | CORRECT. **Not in PAPER.md's reference list**, although M:1820 says it is shared. | FAITHFUL | https://doi.org/10.1093/rfs/hhm056 |
| 70 | Forbes & Rigobon (2002), JF 57(5) 2223-2261 | M:836,854,1603,1838 | CORRECT | **MISATTRIBUTED, known issue (m).** M:834-836 cites F&R for "crisis periods are exactly when idiosyncratic correlation structure collapses toward a single dominant systemic-risk factor". F&R's finding is the opposite: correlation coefficients are **biased upward by heteroskedasticity** in high-volatility periods, and once adjusted there is "virtually no increase" (no contagion, only constant high interdependence). Their confound is the **volatility-conditioning bias in correlation**, which the SPY-residual test (M:840-855) does not address. So "the Forbes-Rigobon confound is real, it just isn't the whole story" (M:854) names a confound that was not tested. A high-VIX discovery regime is exactly where F&R's bias would inflate a correlation prefilter. Re-cite F&R for that bias, and cite a factor-structure source for the market-factor confound. | https://doi.org/10.1111/0022-1082.00494 |
| 71 | Longin & Solnik (2001), JF 56(2) 649-676 | M:836,1604,1838 | CORRECT | FAITHFUL (loosely). The abstract says correlation rises in **bear** markets (tied to trend, not volatility per se). Precise wording would say "rises in bear markets" instead of attributing a single-factor collapse. | https://doi.org/10.1111/0022-1082.00340 |
| 72 | Rovelli (1996), IJTP 35(8) 1637-1678 | M refs (cut) | CORRECT | N/A: cut from the argument and kept for provenance. It should move out of the References heading (e.g. to Appendix A). | https://doi.org/10.1007/bf02302261 |
| 73 | French (1980), JFE 8(1) 55-69 | code: `research/short_term_factor_alpha.py:24,77` (not in paper files) | CORRECT at the code level | FAITHFUL as motivation (Monday/weekend effect), known issue (o). The implemented dummy is shifted one row and tests Tuesday (R8.6, UNVERIFIED). Not cited in the paper; the paper wrongly credits day-of-week seasonality to Blitz et al. (#38). | https://doi.org/10.1016/0304-405x(80)90021-5 |
| 74 | Kyle & Obizhaeva, "square-root law" | code: `backtest.py:202,2340`; Development.md:7981 (not in paper files) | MINOR ERROR: no year/work (candidates: *Econometrica* 84(4) 1345-1404, 2016; "The Market Impact Puzzle" WP). | CANNOT-ASSESS / loose, known issue (p). The implemented `slippage_bps·√(Q/ADV)` form is the empirical square-root law (Tóth et al. 2011; Bouchaud; Almgren et al. 2005). Kyle-Obizhaeva's invariance scales impact by trading activity (W^{1/3}), not simply √(Q/ADV). Attribute the formula to the square-root-law literature and cite K-O only as consistent with it. | https://doi.org/10.3982/ecta10486 |

## Structural findings

1. **The paper's sourcing statements contradict each other.** P:252 says "All citations were verified by
   direct source lookup", while Ref#15-#32 are marked **[TBD]** and 31 in-text works have no reference
   entry at all. Replace P:252 with an accurate statement. Several [TBD] entries are now bibliographically
   confirmed (see the table) and can be upgraded, except Ref#32 (pages wrong) and Ref#18/Meucci/Carver
   (not DOI-indexed).
2. **In-text citations with no reference-list entry (31):** Clegg & Krauss 2018; Phillips & Ouliaris
   1990; Hakkio & Rush 1991; Hooker 1993; Lahiri & Mamingi 1995; Otero & Smith 2000; Do, Faff & Hamza
   2006; Elliott et al. 2005; Do & Faff 2010; Khandani & Lo; Kakushadze 2020; Krauss, Do & Huck 2017;
   Bailey & López de Prado 2014; Harvey, Liu & Zhu 2016; Engle 2002; White 2000; Politis & Romano; Granger
   & Newbold 1974; Zivot & Andrews 1992; Kritzman, Li, Page & Rigobon 2011; DeMiguel, Garlappi & Uppal
   2009; Michaud 1989; López de Prado 2016; Akyildirim et al. 2022; Lo 2002; Schreiber 2000; Brav & Lehavy
   2003; Da & Schaumburg 2011; Lou & Polk 2022; Meinshausen & Bühlmann 2010; Benjamini & Yekutieli 2001.
   Also Lee & Mykland 2008, which is in PAPER_MAGNITUDE only but claimed as "shared".
3. **Reference entries never cited in the text (5):** Hamilton 1989 (#11), Durbin & Koopman (#12),
   Rabiner 1989 (#13), Engle 1982 (#14), Maillard et al. 2010 (#30; its ERC result is reported uncited).
   Rovelli 1996 sits under PAPER_MAGNITUDE's References heading although it was cut.
4. **Inconsistent formatting of the same work:** AFML appears twice (#7 "Lopez", #21 "López"); the
   in-text spelling alternates "Lopez de Prado" / "López de Prado"; Gatev et al. appear as "Gatev,
   Goetzmann & Rouwenhorst", "GGR" and "Gatev et al."; Costa et al. and Friedman et al. use slash-joined
   author lists; the Richman & Moorman entry is nested inside the Costa entry; PBO is dated "2014/2016".
   PAPER_MAGNITUDE:1819 says the shared bibliography includes BY 2001 and Lee & Mykland 2008; PAPER.md's
   list has neither. M:1824 says "A third citation added" when only one is listed there.
5. **Quoted passages:** P:221 "the most cited work on cointegration-based pairs trading" (no source,
   wording not verifiable). Named terms "False Strategy Theorem" (P:406,1305) and "factor zoo" (P:416) come
   from later or other authors (see #51, #53). No other quotation-marked passage attributed to a cited work
   was found.

## Required corrections (most severe first)

**Fabrication-risk: none found.** Every work was found to exist. The four NOT FOUND items (Meucci 2009,
Carver 2015, Hooker 1993, Grinold-Kahn 2nd ed. year) are non-DOI outlets or index gaps, not suspect works.

**Misattributions (fix before any external circulation):**
1. **White (2000)**, P:431-440, 458, 497, §6.6 (1236-1296). Stop calling the circular block bootstrap a
   Reality Check or a "permutation test". Retitle §6.6 as a block-bootstrap Sharpe test. Delete "Correct
   p-value under multiple testing" from the §2.4 table. State that the implemented null is not demeaned, so
   p≈0.5 by construction (S5), and withdraw p=0.559/0.546 as evidence. To make a real White RC claim,
   implement the demeaned best-of-N version over the trial registry.
2. **Forbes & Rigobon (2002)**, M:834-836, 854, 1603. Re-describe F&R as the heteroskedasticity bias in
   crisis-period correlation. Note that the SPY-residual test does not address that bias, and rename the
   tested confound "market-factor co-movement".
3. **Gatev, Goetzmann & Rouwenhorst (2006)**, M:95, 266-270, 1027. Remove "computed once over full
   available history". GGR's pair formation is rolling and point-in-time (12-month formation, 6-month
   trading). Reframe §4's contrast. Confirm against the RFS full text first.
4. **Costa, Goldberger & Peng (2002)**, P:2309. Either fix r to the original series' SD (Costa's method)
   and re-run, or label the result "per-scale-renormalized SampEn (not Costa MSE)" and drop the
   white-noise-level interpretation.
5. **Phillips & Ouliaris (1990)**, P:294-296. Change to "residual-based Z_α/Z_t tests on OLS cointegrating
   residuals" and drop "FM-OLS" and "more powerful than EG in small samples".
6. **Elliott, van der Hoek & Malcolm (2005)**, P:342, table P:451. Change to "mean-reverting Gaussian
   Markov chain observed in noise, Kalman-filter/EM calibration" and drop "Bayesian optimal stopping" and
   "theoretically optimal stopping rule".
7. **Ledoit & Wolf (2004)**, Ref#19, P:1505. Cite *J. Multivariate Analysis* 88(2) 365-411 (the estimator
   sklearn implements), not the JPM "Honey" paper.
8. **Blitz et al. (2023)**, Ref#32, P:2346. The seasonality signal is monthly, not day-of-week. Credit the
   day-of-week test to French (1980) and fix the Tuesday shift (R8.6). Pages → 96-117.
9. **Pu et al. (2023)**, P:2340, Ref#31. "graph neural network" → "linear graph-learning model".
10. **Benjamini-Hochberg PRDS (code)**, `research/bh_fdr_dependence_check.py:38-41`. Credit PRDS validity
    to Benjamini & Yekutieli (2001, Thm 1.2), not BH 1995. PAPER.md does not repeat the error.

**Overstatements:**
11. **Hansen (1999)**, P:2247-2254. Remove "every CI sits comfortably below 1" and the PNC/ZION bound until
    the grid can include/exceed 1 (R6.5).
12. **Engle & Ng (1993)**, P:2224-2229. Withdraw "`garch_stop`'s symmetric design is validated" (R8.1:
    null by construction).
13. **AFML Ch. 4 sequential bootstrap**, P:2583-2606. Confirm R4.6. If confirmed, relabel the arm
    "uniqueness-weighted resampling" and withdraw the "+3.1pp" comparison. Also make the "10 seeds" claim
    reproducible (R4.7).
14. **Engle & Manganelli (2004)**, P:2296-2299. Either add the DQ test or state that adequacy is untested.
15. **Gatev et al. "OOS decay"**, P:1430. Reword as a decline over time, not IS/OOS decay.
16. **Krauss (2017)**, P:350. "ML-based" → "other approaches (including ML)".
17. **Reimers (1992) implementation**, `research/reimers_trio_correction.py:13,52`. Use k = VAR lag in
    levels (k_ar_diff+1) and note that at large T the correction cannot flip results.

**Claims to verify (CANNOT-ASSESS, high priority because they carry argument weight):**
18. Do, Faff & Hamza (2006), P:328, 1932: the claims that it "introduces OU" and that "cointegration+OU
    outperforms distance". P:1932 uses the second as corroboration.
19. Da & Schaumburg (2011), P:3228: the "standalone single-name" framing versus the title's "relative
    valuation".
20. Do & Faff (2010) specific figures and the crowding-rejection claim (P:352-360); Avellaneda & Lee
    figures and the "IS" label (P:334); Krauss-Do-Huck 0.45%/day (P:386); Kakushadze's "others
    unaffected" (P:374-376); Khandani-Lo's 1998 parallel (P:373); the Grinold-Kahn BR_eff formula (P:1515);
    the Vidyamurthy quote's source (P:221).

**Bibliographic minor fixes:**
21. Hakkio & Rush title → "How Short Is the Long Run?", plus pages 571-581. Blitz pages → 96-117. PBO →
    single year, confirm 20(4) 39-69. Engle (2002) full title. Add years/venues for Khandani & Lo,
    Kakushadze, Politis & Romano, Meinshausen & Bühlmann, Do-Faff-Hamza (FMA European Conference 2006).
    Merge AFML #7/#21. Add the 31 missing reference entries. Replace the P:252 "all verified" sentence.
