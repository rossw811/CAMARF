"""
Synthetic check for research/pit_index_membership.py's parsers (Ross 2026-10-03: verify the free point-in-time
S&P 400/600 membership source on more rebalances; docs/PIT_INDEX_MEMBERSHIP_SOURCES.md).
Checks:
  1. parse_nport: a 3-holding NPORT-P XML (incl. a cash sweep with no CUSIP and an "&amp;" name) -> 3 rows with the
     report date, names unescaped, CUSIP / value / pct / asset category as given;
  2. parse_n30d: a schedule-of-investments HTML fragment ("Common Stock Shares Value ... Totals") -> exactly the 5
     holdings in it (incl. one right after a full page break: footer, page number, page header, repeated column
     header -- 2009/2010 reports lost 10 holdings each to this) (a "*" non-income marker stripped; a name with "&" and a comma; nothing after "Totals"), and the
     "as of" date taken from the schedule heading;
  3. parse_n30d ignores numbers in narrative text outside the schedule;
  4. HTML page footers ("The accompanying notes ... Schedule of Investments (continued) September 30, 2017") are not
     read as holdings (real reports had 10 such rows each: shares=30, value=2017), nor the 2007-2010 page header
     variant "MidCap SPDR Trust, Series 1 Schedule of Investments September 30, 2008";
  5. plain-text reports (2001-2005): dot-leader lines and the "*"-column layout both parse, inside the schedule only,
     stopping at "TOTAL"; expense-table lines with dot leaders outside the schedule are ignored.
  6. members(): equity holdings worth >= 0.001 x the snapshot's median holding -- written-off / near-zero rows are not
     members, every normal-weight row is (2026-10-03: a fixed top-N cut dropped a real member when MDY held 401);
  7. name_match(): "R.R. Donnelley & Sons" ~ "R.R. Donnelley & Sons Co.", "Snyder's-Lance" ~ "Snyders-Lance, Inc.",
     but "Range Resources" !~ "Rayonier"; "Cars.com" ~ "Cars.com, Inc."; "Michaels Companies" ~ "Michaels Cos., Inc.";
     "Cadence Bancorporation" ~ "Cadence BanCorp";
  8. check_announcements(): add absent-before/present-after and delete present-before/absent-after agree; a delete
     still held as a leftover (below the top-N line) still agrees; a wrong expectation disagrees.
Run: python debug/_verify_pit_index_membership.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


NPORT = """<?xml version="1.0"?><edgarSubmission><formData><genInfo><repPdDate>2019-09-30</repPdDate></genInfo>
<invstOrSecs>
<invstOrSec><name>Etsy Inc</name><lei>X</lei><title>Etsy</title><cusip>29786A106</cusip><balance>1000.0</balance>
<valUSD>56500.00</valUSD><pctVal>0.4123</pctVal><assetCat>EC</assetCat></invstOrSec>
<invstOrSec><name>Johnson &amp; Johnson Services</name><cusip>478160104</cusip><balance>10.0</balance>
<valUSD>1300.00</valUSD><pctVal>0.0100</pctVal><assetCat>EC</assetCat></invstOrSec>
<invstOrSec><name>State Street Navigator Securities Lending</name><balance>5.0</balance>
<valUSD>500.00</valUSD><pctVal>0.0050</pctVal><assetCat>STIV</assetCat></invstOrSec>
</invstOrSecs></formData></edgarSubmission>"""

N30D = """<html><body><p>The Trust Agreement became effective on April 27, 1995 with 1,234,567 units.</p>
<p>SCHEDULE OF INVESTMENTS September 30, 2007</p>
<table><tr><td>Common Stock</td><td>Shares</td><td>Value</td></tr>
<tr><td>ADC Telecommunications Inc.*</td><td>983,301</td><td>$ 19,282,533</td></tr>
<tr><td>AGL Resources</td><td>650,212</td><td>25,761,399</td></tr>
<tr><td>Alexander &amp; Baldwin, Inc.</td><td>359,763</td><td>18,034,919</td></tr>
<tr><td>The accompanying notes are an integral part of these financial statements. 3 SPDR S&amp;P MidCap 400 ETF Trust
Schedule of Investments (continued) September 30, 2007</td></tr>
<tr><td>MidCap SPDR Trust, Series 1 Schedule of Investments September 30, 2007</td></tr>
<tr><td>Yahoo Inc.</td><td>1,000</td><td>25,000</td></tr>
<tr><td>The accompanying notes are an integral part of these financial statements. 4</td></tr>
<tr><td>MidCap SPDR Trust, Series 1 Schedule of Investments September 30, 2007</td></tr>
<tr><td>Common Stock</td><td>Shares</td><td>Value</td></tr>
<tr><td>Zebra Technologies Corp*</td><td>577,870</td><td>21,086,475</td></tr>
<tr><td>Totals</td><td></td><td>$ 84,165,326</td></tr></table>
<p>Average Annual Return since inception April 27, 1995: 12,345 percent</p></body></html>"""


TXT_DOTS = """                             SCHEDULE OF INVESTMENTS
                               SEPTEMBER 30, 2003

COMMON STOCK                                       SHARES             VALUE
------------                                       ------             -----
3Com Corp.* ....................................     2,273,182   $ 13,411,773.80
99 (Cents) Only Stores* ........................       440,180     14,235,421.20
A.G. Edwards ...................................       490,854     18,853,702.14
TOTAL INVESTMENTS ..............................                  $ 46,500,897.14
    Trustee fees and expenses...........................    6,746,430              5,245,862
"""

TXT_STAR = """                                  SCHEDULE OF INVESTMENTS
                                     SEPTEMBER 30, 2004
<TABLE>
COMMON STOCK                                                  SHARES             VALUE
------------                                                  ------             -----
<C>                                                <C>      <C>              <C>
3Com Corp.                                         *        2,652,426        $11,193,237.72
Abercrombie & Fitch Co.                            *          637,257        $20,073,595.50
Alexander & Baldwin                                           255,841         $7,184,015.28
</TABLE>
TOTAL                                                                       $38,450,848.50
"""


def main():
    try:
        from research.pit_index_membership import parse_nport, parse_n30d
    except ImportError as e:
        check("module_exists", False, str(e)); return finish()
    d = parse_nport(NPORT)
    check("1.nport_rows", len(d) == 3, f"n={len(d)}")
    if len(d) == 3:
        check("1.nport_fields", str(d["as_of"].iloc[0].date()) == "2019-09-30" and d["name"].iloc[1] ==
              "Johnson & Johnson Services" and d["cusip"].iloc[0] == "29786A106" and d["cusip"].isna().iloc[2]
              and abs(d["value_usd"].iloc[0] - 56500.0) < 1e-9 and abs(d["pct"].iloc[0] - 0.4123) < 1e-12
              and d["asset_cat"].iloc[2] == "STIV", d.to_string()[:300])
    h = parse_n30d(N30D)
    names = h["name"].tolist() if len(h) else []
    check("2.n30d_rows", names == ["ADC Telecommunications Inc.", "AGL Resources", "Alexander & Baldwin, Inc.",
                                   "Yahoo Inc.", "Zebra Technologies Corp"], str(names))
    check("2.n30d_values", len(h) == 5 and h["value_usd"].tolist() == [19282533.0, 25761399.0, 18034919.0, 25000.0,
                                                          21086475.0]
          and h["shares"].iloc[0] == 983301.0)
    check("2.n30d_as_of", len(h) and str(h["as_of"].iloc[0].date()) == "2007-09-30",
          str(h["as_of"].iloc[0]) if len(h) else "")
    check("3.narrative_ignored", not any("Trust" in n or "Return" in n for n in names))
    check("4.footer_not_a_holding", not any("accompanying" in n.lower() or "schedule of" in n.lower() for n in names), str(names))
    t1, t2 = parse_n30d(TXT_DOTS), parse_n30d(TXT_STAR)
    check("5a.text_dot_leaders", t1["name"].tolist() == ["3Com Corp.", "99 (Cents) Only Stores", "A.G. Edwards"]
          and t1["value_usd"].tolist() == [13411773.80, 14235421.20, 18853702.14]
          and str(t1["as_of"].iloc[0].date()) == "2003-09-30", t1.to_string()[:400])
    check("5b.text_star_column", t2["name"].tolist() == ["3Com Corp.", "Abercrombie & Fitch Co.", "Alexander & Baldwin"]
          and t2["shares"].tolist() == [2652426.0, 637257.0, 255841.0]
          and str(t2["as_of"].iloc[0].date()) == "2004-09-30", t2.to_string()[:400])
    import pandas as pd
    from research.pit_index_membership import members, name_match, check_announcements
    snap = pd.DataFrame({"name": ["Big Co", "Mid Co", "Small Co", "Tiny Co", "Leftover Inc"],
                         "value_usd": [300.0, 200.0, 100.0, 5.0, 0.05], "asset_cat": ["EC"] * 5})
    check("6.members_weight_rule", members(snap, 3)["name"].tolist() == ["Big Co", "Mid Co", "Small Co", "Tiny Co"],
          str(members(snap, 3)["name"].tolist()))
    check("7.name_match", name_match("R.R. Donnelley & Sons", "R.R. Donnelley & Sons Co.")
          and name_match("Snyder's-Lance", "Snyders-Lance, Inc.") and not name_match("Range Resources", "Rayonier Inc.")
          and name_match("Cars.com", "Cars.com, Inc.") and name_match("Michaels Companies", "Michaels Cos., Inc.")
          and name_match("Cadence Bancorporation", "Cadence BanCorp"))
    mk = lambda d, names, vals: pd.DataFrame({"index": "X", "as_of": pd.Timestamp(d), "form": "NPORT-P", "name": names,
                                              "value_usd": vals, "asset_cat": "EC"})
    hold = pd.concat([mk("2020-03-31", ["Alpha Corp", "Beta Inc", "Gamma Co"], [3.0, 2.0, 1.0]),
                      mk("2020-06-30", ["Alpha Corp", "Delta Inc", "Gamma Co", "Beta Inc"], [3.0, 2.0, 1.0, 0.0001])])
    ann = pd.DataFrame({"effective": ["2020-05-01"] * 3, "index": "X", "action": ["add", "delete", "add"],
                        "name": ["Delta", "Beta", "Alpha"], "ticker": ["D", "B", "A"]})
    r = check_announcements(hold, ann, {"X": 3})
    check("8.check_logic", r["agrees"].tolist() == [True, True, False], r[["name", "in_before", "in_after", "agrees"]].to_string())
    finish()


def finish():
    print(); print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL); sys.exit(1)


if __name__ == "__main__":
    main()
