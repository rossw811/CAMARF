"""
research/lit_search_tools.py -- Reusable literature-search library for the
Scope 2 citation-graph-driven research methodology (see docs/HANDOFF.md's
2026-09-10 entry for the design rationale and Development.md Session 26,
2026-07-02, for the original web-search-only methodology this replaces).

Provides structured, auditable access to two free, no-API-key academic
sources:

- arXiv (export.arxiv.org/api/query): category- and date-scoped preprint
  search, so a pass can query "everything in q-fin.ST/q-fin.TR/stat.ME
  since 2023" directly instead of hoping general web search surfaces it.
- OpenAlex (api.openalex.org): citation-graph traversal -- forward
  ("who cites this paper") and backward ("what does this paper cite").
  This is the actual structural upgrade over keyword search: it finds the
  literature that built on what CAMARF already cites, or that CAMARF's
  own citations built on, neither of which a keyword search reliably
  surfaces.

Every function returns plain JSON-serializable dicts/lists and logs the
exact query issued (via the `logging` module), so a research pass built on
this library is auditable -- the API call that produced a given result can
be reproduced later, matching this project's reproducibility discipline
applied to research itself, not just code.

Both APIs are free and require no key. OpenAlex asks callers to identify
themselves via a `mailto` parameter for its "polite pool" (higher rate
limits, more reliable service) -- POLITE_EMAIL below supplies that.

KNOWN GOTCHAS, confirmed via live testing 2026-09-10, not theoretical:
1. arXiv's `abs:` field does loose per-word matching, not phrase matching,
   even when the query string is quoted. A natural-language topic phrase
   (e.g. "point-in-time bias discovery") returns largely off-topic results
   ranked by arXiv's own relevance score. Build queries from a small number
   of tightly-necessary terms instead, and treat the category filter
   (`categories=`) as doing more of the real narrowing than the text query.
   Always relevance-filter results by reading title+summary before citing
   one, never trust arXiv's ranking alone.
2. OpenAlex DOI resolution can land on the WRONG one of two duplicate
   records for finance/econ papers with an SSRN-preprint-then-journal
   lifecycle -- confirmed directly on Bailey/Borwein/Lopez de Prado/Zhu's
   PBO paper (DOI record: cited_by_count=0; title-search record, the SSRN
   preprint: cited_by_count=25 -- same paper). Use `openalex_resolve_best`
   below, not `openalex_resolve_work` with only a DOI, for anything whose
   citation graph you intend to traverse.
"""
import json
import logging
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger("lit_search_tools")

ARXIV_API = "http://export.arxiv.org/api/query"
OPENALEX_API = "https://api.openalex.org/works"
POLITE_EMAIL = "ross.winnemore@icloud.com"
USER_AGENT = f"CAMARF-research/1.0 (mailto:{POLITE_EMAIL})"

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_ARXIV_CAT_NS = {"arxiv": "http://arxiv.org/schemas/atom"}


def arxiv_search(query, categories=None, start_date=None, end_date=None,
                  max_results=50, sort_by="relevance"):
    """
    Query the arXiv API.

    query: free-text string searched against title+abstract. Pass "" (or
        None) to search by category/date alone.
    categories: list of arXiv category codes, e.g. ["q-fin.ST", "q-fin.TR",
        "q-fin.PM", "stat.ME"]. ORed together, ANDed with `query`.
    start_date/end_date: "YYYYMMDD" strings (arXiv's submittedDate range
        syntax). Either may be omitted for an open-ended range.
    max_results: capped by arXiv at 2000 per call; this library does not
        paginate beyond a single call -- call again with a narrower query
        if you need more.
    sort_by: "relevance" or "date" (submittedDate descending).

    Returns a list of dicts: {id, title, authors, summary, published,
    updated, pdf_url, categories}.

    Courtesy note: arXiv asks for at least a ~3s gap between calls in a
    loop. This function does not sleep for you -- a caller issuing many
    calls must add its own delay.
    """
    search_terms = []
    if query:
        search_terms.append(f"abs:{query}")
    if categories:
        cat_clause = " OR ".join(f"cat:{c}" for c in categories)
        search_terms.append(f"({cat_clause})")
    if start_date or end_date:
        sd = start_date or "19910101"
        ed = end_date or "99991231"
        search_terms.append(f"submittedDate:[{sd} TO {ed}]")
    search_query = " AND ".join(search_terms) if search_terms else "all:*"

    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "relevance" if sort_by == "relevance" else "submittedDate",
        "sortOrder": "descending",
    }
    logger.info("arxiv_search query=%r params=%r", search_query, params)
    resp = requests.get(ARXIV_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return _parse_arxiv_feed(resp.text)


def _parse_arxiv_feed(xml_text):
    root = ET.fromstring(xml_text)
    results = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        cats = [c.get("term") for c in entry.findall("arxiv:category", _ARXIV_CAT_NS)]
        if not cats:
            cats = [c.get("term") for c in entry.findall("atom:category", _ATOM_NS)]
        pdf_url = None
        for link in entry.findall("atom:link", _ATOM_NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")
                break
        results.append({
            "id": (entry.findtext("atom:id", default="", namespaces=_ATOM_NS) or "").strip(),
            "title": (entry.findtext("atom:title", default="", namespaces=_ATOM_NS) or "").strip().replace("\n", " "),
            "authors": [a.findtext("atom:name", default="", namespaces=_ATOM_NS)
                        for a in entry.findall("atom:author", _ATOM_NS)],
            "summary": (entry.findtext("atom:summary", default="", namespaces=_ATOM_NS) or "").strip().replace("\n", " "),
            "published": entry.findtext("atom:published", default="", namespaces=_ATOM_NS),
            "updated": entry.findtext("atom:updated", default="", namespaces=_ATOM_NS),
            "pdf_url": pdf_url,
            "categories": cats,
        })
    return results


def openalex_resolve_work(title=None, doi=None):
    """
    Resolve a paper to its OpenAlex Work record by DOI (exact) or title
    (fuzzy search, best match only). Prefer DOI when known.

    Returns a slim work dict (see _slim_work) or None if nothing found.
    """
    if doi:
        url = f"{OPENALEX_API}/doi:{doi}"
        resp = requests.get(url, params={"mailto": POLITE_EMAIL}, headers={"User-Agent": USER_AGENT}, timeout=30)
        if resp.status_code == 200:
            return _slim_work(resp.json())
        return None
    if title:
        resp = requests.get(OPENALEX_API, params={"search": title, "per_page": 1, "mailto": POLITE_EMAIL},
                             headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return _slim_work(results[0]) if results else None
    raise ValueError("openalex_resolve_work requires title or doi")


def openalex_resolve_best(title, doi=None):
    """
    Resolve a paper robustly, working around a real, confirmed OpenAlex
    data-quality issue: finance/econ papers with an SSRN-preprint-then-
    journal-publication lifecycle often have TWO separate, un-merged
    OpenAlex Work records (the preprint and the published version), and
    the one a DOI lookup lands on is not reliably the one with the
    citation history actually aggregated onto it. Confirmed directly:
    Bailey/Borwein/Lopez de Prado/Zhu's "Probability of Backtest
    Overfitting" resolves via its journal DOI to a record with
    cited_by_count=0, but resolves via title search to its SSRN-preprint
    record with cited_by_count=25 -- same paper, same authors, the DOI
    record is real but citation-empty.

    Tries both DOI (if given) and title search, returns whichever
    resolved record has the higher cited_by_count (ties go to the DOI
    match). Returns None only if neither resolves.
    """
    candidates = []
    if doi:
        by_doi = openalex_resolve_work(doi=doi)
        if by_doi:
            candidates.append(by_doi)
    by_title = openalex_resolve_work(title=title)
    if by_title:
        candidates.append(by_title)
    if not candidates:
        return None
    return max(candidates, key=lambda w: w.get("cited_by_count") or 0)


def openalex_citations(work_id, direction="cited_by", year_min=None, per_page=50, max_pages=3):
    """
    Traverse the OpenAlex citation graph from a resolved work.

    direction="cited_by": works that cite `work_id` -- forward, "what
        built on this," the main tool for finding recent literature that
        extends something CAMARF already cites.
    direction="references": works `work_id` itself cites -- backward,
        "what this built on," useful for catching foundational papers
        CAMARF cites secondhand but has never sourced directly.
    year_min: only return works published in/after this year.
    per_page/max_pages: pagination bounds; "cited_by" paginates via
        OpenAlex's cursor, "references" fetches each referenced work
        individually (OpenAlex stores a work's own reference list inline,
        capped by what OpenAlex itself indexes).

    Returns a list of slim work dicts.
    """
    work_id = _short_id(work_id)
    if direction == "references":
        w_resp = requests.get(f"{OPENALEX_API}/{work_id}", params={"mailto": POLITE_EMAIL},
                               headers={"User-Agent": USER_AGENT}, timeout=30)
        w_resp.raise_for_status()
        ref_ids = w_resp.json().get("referenced_works", [])
        out = []
        for rid in ref_ids:
            r = requests.get(f"{OPENALEX_API}/{_short_id(rid)}", params={"mailto": POLITE_EMAIL},
                              headers={"User-Agent": USER_AGENT}, timeout=30)
            if r.status_code == 200:
                out.append(_slim_work(r.json()))
            time.sleep(0.15)
        if year_min:
            out = [w for w in out if (w.get("publication_year") or 0) >= year_min]
        return out

    if direction != "cited_by":
        raise ValueError("direction must be 'cited_by' or 'references'")

    filt = f"cites:{work_id}"
    if year_min:
        filt += f",publication_year:>{year_min - 1}"

    results, cursor = [], "*"
    for _ in range(max_pages):
        params = {"filter": filt, "per_page": per_page, "cursor": cursor, "mailto": POLITE_EMAIL}
        logger.info("openalex_citations filter=%r cursor=%r", filt, cursor)
        resp = requests.get(OPENALEX_API, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(_slim_work(w) for w in data.get("results", []))
        cursor = data.get("meta", {}).get("next_cursor")
        if not cursor:
            break
        time.sleep(0.2)
    return results


def _slim_work(w):
    authorships = w.get("authorships")
    primary_loc = w.get("primary_location") or {}
    oa = w.get("open_access") or {}
    return {
        "id": w.get("id"),
        "doi": w.get("doi"),
        "title": w.get("title") or w.get("display_name"),
        "publication_year": w.get("publication_year"),
        "cited_by_count": w.get("cited_by_count"),
        "authors": [a.get("author", {}).get("display_name") for a in authorships] if authorships else None,
        "venue": (primary_loc.get("source") or {}).get("display_name") if primary_loc else None,
        "oa_url": oa.get("oa_url"),
    }


def _short_id(work_id):
    if work_id and str(work_id).startswith("http"):
        return work_id.rstrip("/").split("/")[-1]
    return work_id


class DedupRegistry:
    """
    A persisted, dedup-by-key registry for papers surfaced across a
    multi-pass, multi-agent literature sweep, so continuing or re-running
    the sweep doesn't re-surface the same paper under a different agent's
    output. Keyed by DOI when available, else by normalized title.

    Usage:
        reg = DedupRegistry("output/research/lit_search_registry.json")
        for paper in candidates:
            if reg.is_new(paper):
                reg.add(paper, found_via="openalex_citations(Gatev2006)")
        reg.save()
    """
    def __init__(self, path):
        self.path = Path(path)
        self._seen = {}
        if self.path.exists():
            self._seen = json.loads(self.path.read_text(encoding="utf-8"))

    def key_for(self, paper):
        doi = paper.get("doi")
        if doi:
            return str(doi).lower().strip()
        title = (paper.get("title") or "").lower().strip()
        return "title:" + " ".join(title.split())

    def is_new(self, paper):
        return self.key_for(paper) not in self._seen

    def add(self, paper, found_via):
        self._seen[self.key_for(paper)] = {"title": paper.get("title"), "found_via": found_via}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._seen, indent=2), encoding="utf-8")
