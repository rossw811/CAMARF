# Literature novelty check, 2026-10-25 (two Sonnet web-search passes; abstracts and snippets, no full texts)

Verdicts mean "not found in the formal literature by ~20 targeted searches", not proof of absence. Full texts still to
read before any novelty sentence is written: Farago & Hjalmarsson (2019), Clegg (2014), Rad, Low & Faff (2016),
Huck & Afawubo (2015), Chen et al. (2019) (library access: Ross's librarian email).

| Contribution | Verdict | Closest prior work and the difference |
|---|---|---|
| A. End-to-end placebo of the whole discovery pipeline (E1) | not found | Practitioner repos only: manvendrasinghS/pairs-trading-project (60 simulated walks as a size check on one gate; no bootstrap universe, no planted pairs). |
| B. EG screen size under a correlation-matched null at scale (N14) | partial | Clegg (2014), SSRN 2491201: ~5% of S&P 500 pairs "cointegrated" per year and ~5% persistence, against the NOMINAL level, 500 names (figures via CXO Advisory summary; primary unread). Farago & Hjalmarsson (2019, JFQA 54(2) 629-665): little pairwise cointegration (abstract). Neither builds a correlation-matched null. |
| C. Pre-registered, sealed-holdout, PIT test with DSR over all trials | no peer-reviewed prior; close non-peer-reviewed | kakhramonovsh-prog/stat-arb-pairs-trading (2026, pseudonymous): 184 US large caps, one-shot OOS 2022-2026, PREREGISTRATION.md for two extensions, BH-FDR, no net profit; no DSR over all trials, no placebo. manvendrasinghS: DSR over 195,750 trials (0.0%), no preregistration. Must be cited. |
| D. Edge accounting (attribution to specific errors) | not found as a set | kakhramonovsh quantifies one look-ahead (spread standardised with trading-window moments, ~+9.7 pp/yr). Docs/blogs note full-sample hedge-ratio leakage. No decomposition across selection, P&L basis, executability. |

Counter-evidence the paper must engage: Rad, Low & Faff (2016, Quant. Finance, doi 10.1080/14697688.2016.1164337;
1962-2014, cointegration ~33 bp/month net, fewer opportunities after 2009); Do & Faff (2010, FAJ 66(4) 83-95; 2012,
J. Financial Research 35(2) 261-287: largely unprofitable after 2002); Huck & Afawubo (2015, Applied Economics 47(6)
599-613: cointegration selection robust on S&P 500); Chen, Chen, Chen & Li (2019, Management Science 65(1) 370-389;
correlation-based, large abnormal returns); Krauss (2017, J. Economic Surveys survey). Supporting: Fil (2020,
arXiv:2010.01157). Methods: Bailey & López de Prado (2014, DSR); Harvey, Liu & Zhu (2016); Sullivan, Timmermann &
White (1999); Gatev, Goetzmann & Rouwenhorst (2006, RFS 19(3) 797-827).

Unverified / not found: Harlacher (2016) thesis; Kellard (2006); a Brazilian study reporting OOS Sharpe 1.34; Reality
Check / SPA applied to pairs.

Wording rule for the paper: A may be claimed as new; B as "the first correlation-matched null at this scale" (with
Clegg and Farago-Hjalmarsson as the nearest results); C and D as "not in the formal literature", citing the 2026
repositories.
