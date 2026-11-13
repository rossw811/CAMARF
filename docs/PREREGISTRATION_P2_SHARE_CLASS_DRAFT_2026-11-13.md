# Pre-registration — P2 share-class positive control (DRAFT, 2026-11-13)

**Status: DRAFT. Not a pre-registration until (1) Ross signs it off and (2) the open items marked [OPEN] are filled and
the file is committed under its final name BEFORE any real P2 test statistic is computed.** No real P2 test has been run;
real prices have entered P2 only through coverage counts and the placebo rebuild (their reshuffled returns).

## Question
Two share classes of one company with the same per-share claim on dividends and liquidation (stated in the charter or
filings) should have a stationary log-price difference. Does the yearly fixed-hedge test, with a family small enough
for one year of data to matter, confirm such pairs at a rate clearly above what the same procedure gives on pairs with
no long-run relation? This is a POSITIVE CONTROL of the testing pipeline, not a trading headline: if it cannot find
these, a null elsewhere says little; if it can, nulls elsewhere mean more.

## Family (fixed; research/p2_share_class_family.py)
- At each Dec 31 T, 1990-2024: both securities common shares (CRSP SHRCD 10/11) on a name row covering T, same PERMCO,
  each first listed >= 2 years before T, each with a content-verified WRDS daily file (data_wrds.label_permno_map via
  permno_labels / leg_label; never full_us_market_label_map -- BUG of 2026-11-13).
- Kept only if declared same-claim from that year (research/p2_share_class_classification.csv, filings only,
  fail-closed; tracking stocks, charter dividend differences and unknowns excluded).
- Two families, never pooled, each with its own BH:
  - **Gated (headline):** both legs pass the discovery ADV gate on T (rolling_adv / adv_at >= Config.STATS.ADV_FILTER_USD,
    $25M nominal). As of 2026-11-13: 69 pair-years, 11 pairs, first kept year 2004 [update if the eight missing legs,
    incl. Berkshire A, are installed before sign-off].
  - **Ungated (descriptive power check):** no ADV gate. 868 kept pair-years of 1,905.
- Membership reads no price, return or test result.

## Test (fixed except the lag rule)
- Year y's bars only (common dates; both legs on >= 80% of the year's calendar days, >= 30 bars), log total-return
  prices, spread = log a - log b, ADF with a constant (slope fixed at 1; any constant price ratio is in the intercept).
- Benjamini-Hochberg at 5% across the family's testable pairs in year y. A pair rejected in year y is CONFIRMED for
  year y + 1 only (decision date = last bar of y).
- **Lag rule [OPEN]:** chosen BEFORE real data from the placebo comparison on the **gated (headline) family**
  (research/p2_placebo_power.py; arms AIC = fixed_adf, Schwert fixed lag = fixed_adf_schwert, t-stat general-to-specific
  = fixed_adf_tstat; a heteroskedasticity-robust arm may be added -- see Known limits). Rule: an arm qualifies if, on the
  gated family pooled over the E1 v2c seeds, its pair-year rejection rate at p<0.05 is within 3 binomial SE of 0.05;
  among qualifying arms, the highest one_true power for whole-year 5-day plants, ties by 20-day. If none qualifies,
  P2 is not run as designed and comes back to Ross. **Disclosed:** this rule was written after the AIC and seed-1
  Schwert placebo sizes were known (placebo only; no real P2 statistic exists).

## Null benchmark and success criterion (declared now)
- Statistic: C = number of confirmed pair-years in the gated family, 1990-2024 (and, descriptive, the same for the
  ungated kept family).
- Null distribution: the IDENTICAL procedure (same family, same years, same coverage rule, chosen arm, BH per year) on
  S = 199 placebo rebuilds of the family's legs (build()'s v2c sampler, seeds 20261024 + k, pinned file list). Each draw
  replicates the whole structure -- the same pairs repeating across years and same-year clustering -- so no
  independence assumption is needed (review 2026-11-13: an exact binomial over pair-years was anti-conservative).
- Monte Carlo p = (1 + #{draws with C_null >= C_real}) / (S + 1). Success: p < 0.05 for the gated family. Reported
  regardless: C_real, the null distribution's quantiles, per-seed counts, and the placebo power table for the chosen arm
  (only fast, ~5-day, whole-year relations are reliably detectable in one year, so a "no" may mean "cannot see" rather
  than "not there").
- Caveat carried with the result: the placebo keeps market-level volatility clustering but less than real data
  (mean ACF of |r|, lags 1-20: v2b 0.165 vs real 0.190 on 150 US series; v2c not measured separately), and unit-root tests over-reject under volatility clustering, so the null distribution may
  be too narrow -- it favours a "yes". Stated next to any positive result.

## Reported regardless of outcome
Per pair-year: p-value, bars, confirmed y/n; per year: family size m and confirmations; per decade; per pair; the
other two lag-rule arms' results labelled as non-chosen comparison arms.

## Trading [OPEN -- Ross]
Whether P2 includes a next-year trading leg (and with which existing rules) is not part of this draft. If added, it is
an amendment committed before any trading result exists.

## Known limits (disclosed)
- Size of the ADF on these nulls (2026-11-13, placebo + synthetic; debug/_tmp_p2_size_garch_check_20261113.py): the
  over-rejection comes mostly from volatility clustering with fat tails (GARCH t4, 252 bars: AIC 0.082, Schwert 0.055,
  t-stat 0.071) and less from the spreads' negative autocorrelation (MA -0.13: 0.061 / 0.047 / 0.060); both together
  0.085 / 0.065 / 0.072. No lag rule is robust to heteroskedasticity; a wild-bootstrap ADF (Cavaliere-Taylor) is the
  standard robust option -- proposed to Ross as a further arm, not built.
- Same-claim rows often rest on one year's charter, assumed for the pair's other years (noted per row).
- Unknowns cluster before 1996 (pre-EDGAR): the early family is thinner and larger-company-heavy.
- The CRSP name snapshot ends 2024-12-31 (no 2025 family).
- Class-specific dividends make a total-return spread drift by the dividend difference; charter dividend differences are
  excluded, realised timing differences are not.
- The ADF over-rejects when spread returns are negatively autocorrelated (found on the placebo 2026-11-13); the lag rule
  above is the response; the real data may differ from the placebo in that structure.
- Results are computed on CachyOS's cache only (the Surface cache differs, 2026-10-28).
