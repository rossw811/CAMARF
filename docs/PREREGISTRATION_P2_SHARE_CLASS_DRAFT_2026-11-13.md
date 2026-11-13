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
- **Lag rule [OPEN]:** chosen BEFORE real data from the placebo comparison (research/p2_placebo_power.py, 5 E1 v2c seeds)
  by this rule, declared now: among {AIC (fixed_adf), Schwert fixed lag (fixed_adf_schwert), t-stat general-to-specific
  (fixed_adf_tstat)}, keep the arms whose pooled placebo size at p<0.05 is within 3 binomial SE of 0.05 AND whose share
  of family-years with >= 1 false BH discovery is <= 0.05 + 3 SE; among those, the highest one_true power for whole-year
  5-day and 20-day plants (5-day first). If no arm qualifies, P2 is not run as designed and comes back to Ross.
- Benjamini-Hochberg at 5% across the family's testable pairs in year y.
- A pair rejected in year y is CONFIRMED for year y + 1 only (decision date = last bar of y).

## Null benchmark (placebo, fixed)
The same procedure on the same family's legs rebuilt from each v2c seed (exact build() rebuild; legs keep same-day
co-movement, lose any long-run tie). Per family and seed: share of testable pair-years rejected by BH. Benchmark =
the LARGEST seed's rate (conservative; E1 showed large seed-to-seed variation).

## Success criterion (declared now)
For the gated family, and separately (descriptive) the ungated family: the real share of testable kept pair-years
confirmed exceeds the benchmark, one-sided exact binomial p < 0.05 with the benchmark as the null rate. Reported
regardless: confirmed share, benchmark per seed, and the placebo power table for the chosen arm (so a "no" can be read
as "the pipeline cannot see these" vs "the relation is not there": the placebo says only fast (~5-day) whole-year
relations are reliably detectable in one year).

## Reported regardless of outcome
Per pair-year: p-value, bars, confirmed y/n; per year: family size m and confirmations; per decade; per pair; the
other two lag-rule arms' results labelled as non-chosen comparison arms.

## Trading [OPEN -- Ross]
Whether P2 includes a next-year trading leg (and with which existing rules) is not part of this draft. If added, it is
an amendment committed before any trading result exists.

## Known limits (disclosed)
- Same-claim rows often rest on one year's charter, assumed for the pair's other years (noted per row).
- Unknowns cluster before 1996 (pre-EDGAR): the early family is thinner and larger-company-heavy.
- The CRSP name snapshot ends 2024-12-31 (no 2025 family).
- Class-specific dividends make a total-return spread drift by the dividend difference; charter dividend differences are
  excluded, realised timing differences are not.
- The ADF over-rejects when spread returns are negatively autocorrelated (found on the placebo 2026-11-13); the lag rule
  above is the response; the real data may differ from the placebo in that structure.
- Results are computed on CachyOS's cache only (the Surface cache differs, 2026-10-28).
