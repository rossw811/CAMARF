"""
Synthetic verification for research/lit_search_tools.py, per this project's
verify-before-trusting convention. Mocks all HTTP calls (via
unittest.mock.patch on requests.get) so this test never depends on live
network access -- run debug/_smoke_lit_search_tools.py separately for a
real, live-network sanity check against the actual APIs.

Run: python debug/_verify_lit_search_tools.py
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research import lit_search_tools as lst

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


# --- Fixture: a real arXiv Atom response shape (trimmed to one entry) ---
ARXIV_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2401.01234v1</id>
    <title>A Test Paper on Causal Pair Discovery</title>
    <summary>
      We test whether causal discovery timing matters.
    </summary>
    <published>2024-01-15T00:00:00Z</published>
    <updated>2024-01-16T00:00:00Z</updated>
    <author><name>Jane Q. Researcher</name></author>
    <author><name>John Doe</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/2401.01234v1" rel="related" type="application/pdf"/>
    <arxiv:category term="q-fin.ST"/>
    <arxiv:category term="stat.ME"/>
  </entry>
</feed>
"""

OPENALEX_WORK_FIXTURE = {
    "id": "https://openalex.org/W1234567890",
    "doi": "https://doi.org/10.1000/testdoi",
    "title": "The Probability of Backtest Overfitting",
    "display_name": "The Probability of Backtest Overfitting",
    "publication_year": 2016,
    "cited_by_count": 512,
    "authorships": [
        {"author": {"display_name": "David H. Bailey"}},
        {"author": {"display_name": "Marcos Lopez de Prado"}},
    ],
    "primary_location": {"source": {"display_name": "Journal of Computational Finance"}},
    "open_access": {"oa_url": None},
    "referenced_works": ["https://api.openalex.org/W1111111111"],
}

OPENALEX_CITED_BY_PAGE = {
    "meta": {"next_cursor": None},
    "results": [
        {
            "id": "https://openalex.org/W2222222222",
            "doi": "https://doi.org/10.1000/citing1",
            "title": "A Paper That Cites PBO",
            "publication_year": 2023,
            "cited_by_count": 4,
            "authorships": [{"author": {"display_name": "Someone Else"}}],
            "primary_location": {"source": {"display_name": "Some Journal"}},
            "open_access": {"oa_url": "https://example.com/oa.pdf"},
        }
    ],
}


def test_arxiv_feed_parsing():
    entries = lst._parse_arxiv_feed(ARXIV_FIXTURE)
    check("arxiv_parse.count", len(entries) == 1, f"got {len(entries)}")
    e = entries[0]
    check("arxiv_parse.title", e["title"] == "A Test Paper on Causal Pair Discovery", e["title"])
    check("arxiv_parse.authors", e["authors"] == ["Jane Q. Researcher", "John Doe"], e["authors"])
    check("arxiv_parse.categories", set(e["categories"]) == {"q-fin.ST", "stat.ME"}, e["categories"])
    check("arxiv_parse.pdf_url", e["pdf_url"] == "http://arxiv.org/pdf/2401.01234v1", e["pdf_url"])
    check("arxiv_parse.summary_stripped", "\n" not in e["summary"], repr(e["summary"]))


def test_arxiv_search_builds_correct_query():
    with patch.object(lst, "requests") as mock_requests:
        mock_resp = MagicMock()
        mock_resp.text = ARXIV_FIXTURE
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp
        lst.arxiv_search("cointegration", categories=["q-fin.ST", "q-fin.TR"],
                          start_date="20230101", end_date="20261231", max_results=10)
        called_params = mock_requests.get.call_args.kwargs["params"]
        q = called_params["search_query"]
        check("arxiv_search.query_has_abs", "abs:cointegration" in q, q)
        check("arxiv_search.query_has_categories", "cat:q-fin.ST" in q and "cat:q-fin.TR" in q, q)
        check("arxiv_search.query_has_date_range", "submittedDate:[20230101 TO 20261231]" in q, q)


def test_openalex_resolve_by_doi():
    with patch.object(lst, "requests") as mock_requests:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = OPENALEX_WORK_FIXTURE
        mock_requests.get.return_value = mock_resp
        result = lst.openalex_resolve_work(doi="10.1000/testdoi")
        check("openalex_resolve.title", result["title"] == "The Probability of Backtest Overfitting", result["title"])
        check("openalex_resolve.authors", result["authors"] == ["David H. Bailey", "Marcos Lopez de Prado"], result["authors"])
        check("openalex_resolve.venue", result["venue"] == "Journal of Computational Finance", result["venue"])
        check("openalex_resolve.year", result["publication_year"] == 2016, result["publication_year"])


def test_openalex_resolve_by_title_uses_search_endpoint():
    with patch.object(lst, "requests") as mock_requests:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"results": [OPENALEX_WORK_FIXTURE]}
        mock_requests.get.return_value = mock_resp
        result = lst.openalex_resolve_work(title="Probability of Backtest Overfitting")
        called_params = mock_requests.get.call_args.kwargs["params"]
        check("openalex_resolve_title.uses_search_param", called_params.get("search") is not None)
        check("openalex_resolve_title.result", result is not None and result["title"].startswith("The Probability"))


def test_openalex_resolve_returns_none_on_404():
    with patch.object(lst, "requests") as mock_requests:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_requests.get.return_value = mock_resp
        result = lst.openalex_resolve_work(doi="10.1000/doesnotexist")
        check("openalex_resolve.none_on_missing", result is None)


def test_openalex_citations_cited_by_filter_and_pagination():
    with patch.object(lst, "requests") as mock_requests:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = OPENALEX_CITED_BY_PAGE
        mock_requests.get.return_value = mock_resp
        results = lst.openalex_citations("https://openalex.org/W1234567890", direction="cited_by", year_min=2022)
        called_params = mock_requests.get.call_args.kwargs["params"]
        check("openalex_citations.filter_has_cites", "cites:W1234567890" in called_params["filter"], called_params["filter"])
        check("openalex_citations.filter_has_year", "publication_year:>2021" in called_params["filter"], called_params["filter"])
        check("openalex_citations.results_count", len(results) == 1, len(results))
        check("openalex_citations.stops_on_no_cursor", mock_requests.get.call_count == 1, mock_requests.get.call_count)


def test_openalex_citations_references_uses_api_endpoint_not_landing_page():
    # BUG-2026-09-13: openalex_citations(direction="references") used to GET
    # the bare https://openalex.org/W... landing-page URL for each referenced
    # work (Cloudflare-gated, returns a 403 HTML challenge page, not JSON).
    # The `if r.status_code == 200` check silently swallowed the failure, so
    # every backward-reference call returned an empty list with no error --
    # found live during the 2026-09-13 literature sweep's pass 1. Fixed to
    # rewrite each referenced-work id to the api.openalex.org/works/<id>
    # endpoint before fetching. This test would have failed against the
    # pre-fix code: it asserts the actual URL requested for each reference.
    with patch.object(lst, "requests") as mock_requests:
        work_resp = MagicMock()
        work_resp.raise_for_status = MagicMock()
        work_resp.json.return_value = OPENALEX_WORK_FIXTURE  # referenced_works: ["https://api.openalex.org/W1111111111"]

        ref_resp = MagicMock()
        ref_resp.status_code = 200
        ref_resp.json.return_value = {
            "id": "https://openalex.org/W1111111111",
            "title": "A Referenced Foundational Paper",
            "display_name": "A Referenced Foundational Paper",
            "publication_year": 2010,
            "cited_by_count": 999,
        }
        mock_requests.get.side_effect = [work_resp, ref_resp]

        results = lst.openalex_citations("https://openalex.org/W1234567890", direction="references")

        ref_call_url = mock_requests.get.call_args_list[1].args[0]
        check("openalex_citations.references_uses_api_host",
              ref_call_url.startswith("https://api.openalex.org/works/"), ref_call_url)
        check("openalex_citations.references_no_bare_landing_page",
              ref_call_url != "https://api.openalex.org/W1111111111", ref_call_url)
        check("openalex_citations.references_returns_result",
              len(results) == 1 and results[0]["title"] == "A Referenced Foundational Paper", results)


def test_openalex_citations_rejects_bad_direction():
    try:
        lst.openalex_citations("W123", direction="sideways")
        check("openalex_citations.rejects_bad_direction", False, "did not raise")
    except ValueError:
        check("openalex_citations.rejects_bad_direction", True)


def test_short_id_extraction():
    check("short_id.strips_url", lst._short_id("https://openalex.org/W1234567890") == "W1234567890")
    check("short_id.passthrough_bare_id", lst._short_id("W1234567890") == "W1234567890")


def test_dedup_registry_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "registry.json"
        reg = lst.DedupRegistry(path)
        paper_a = {"doi": "10.1/AAA", "title": "Paper A"}
        paper_b_no_doi = {"title": "Paper B, A Study"}
        check("dedup.starts_empty", reg.is_new(paper_a))
        reg.add(paper_a, found_via="test")
        check("dedup.detects_duplicate_by_doi", not reg.is_new(paper_a))
        check("dedup.doi_case_insensitive", not reg.is_new({"doi": "10.1/aaa", "title": "different title"}))
        check("dedup.new_paper_by_title", reg.is_new(paper_b_no_doi))
        reg.add(paper_b_no_doi, found_via="test2")
        reg.save()

        reg2 = lst.DedupRegistry(path)
        check("dedup.persists_across_instances", not reg2.is_new(paper_a) and not reg2.is_new(paper_b_no_doi))
        on_disk = json.loads(path.read_text())
        check("dedup.records_found_via", on_disk[reg.key_for(paper_a)]["found_via"] == "test", on_disk)


if __name__ == "__main__":
    test_arxiv_feed_parsing()
    test_arxiv_search_builds_correct_query()
    test_openalex_resolve_by_doi()
    test_openalex_resolve_by_title_uses_search_endpoint()
    test_openalex_resolve_returns_none_on_404()
    test_openalex_citations_cited_by_filter_and_pagination()
    test_openalex_citations_references_uses_api_endpoint_not_landing_page()
    test_openalex_citations_rejects_bad_direction()
    test_short_id_extraction()
    test_dedup_registry_roundtrip()

    print()
    print(f"{len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    sys.exit(0)
