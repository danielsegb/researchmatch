"""
Core utilities: file I/O, API interactions, and data transformation.
Supports OpenAlex, CrossRef, Semantic Scholar, arXiv, PubMed, and DOAJ.
"""
import os
import re
import time
import tempfile
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional

import requests
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse
from docx import Document  # python-docx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
CONTACT_EMAIL = "dnm24xdn@bangor.ac.uk"
STOPWORDS = set(
    "a an and are as at be but by for from has have if in into is it its of on or "
    "than that the their them then there these they this to was were will with within "
    "without using used based among between across under over via while due can could "
    "should would may might".split()
)
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
API_TIMEOUT, API_DELAY, MAX_CHARS = 30, 0.15, 60000
MAX_UPLOAD_MB = 50

HEADERS = {
    "User-Agent": f"ResearchMatch/1.0 (mailto:{CONTACT_EMAIL})",
    "mailto": CONTACT_EMAIL,
}

# ── Text helpers ──────────────────────────────────────────────────────────────
def normalize_ws(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def tokenize_words(text: str) -> List[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


# ── File I/O ──────────────────────────────────────────────────────────────────
def extract_text(filepath: str) -> str:
    try:
        if filepath.lower().endswith(".pdf"):
            with fitz.open(filepath) as doc:
                return " ".join([page.get_text() for page in doc]).strip()
        elif filepath.lower().endswith(".docx"):
            return " ".join([p.text for p in Document(filepath).paragraphs]).strip()
        logger.warning(f"Unsupported file type: {filepath}")
        return ""
    except Exception as e:
        logger.error(f"Text extraction failed: {e}")
        return ""


def safe_file_upload(uploaded_file) -> Optional[str]:
    """Save a Streamlit UploadedFile to a unique temp path. Caller must delete."""
    if not uploaded_file:
        return None
    if hasattr(uploaded_file, "size") and uploaded_file.size > MAX_UPLOAD_MB * 1024 * 1024:
        logger.warning(f"Rejected upload '{uploaded_file.name}': exceeds {MAX_UPLOAD_MB} MB.")
        return None
    suffix = os.path.splitext(uploaded_file.name)[1].lower() or ".tmp"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            for chunk in uploaded_file:
                tmp.write(chunk)
            return tmp.name
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        return None


def download_and_extract_pdf(pdf_url: str) -> str:
    """Download a PDF to a temp file, extract text, delete immediately."""
    try:
        parsed = urlparse(pdf_url)
        host = parsed.hostname or ""
        if host in ("localhost", "127.0.0.1") or host.startswith(("192.168.", "10.", "172.16.")):
            return ""
        r = requests.get(pdf_url, timeout=20, headers=HEADERS, stream=True)
        r.raise_for_status()
        if "application/pdf" not in r.headers.get("Content-Type", "").lower():
            return ""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            for chunk in r.iter_content(chunk_size=8192):
                tmp.write(chunk)
            tmp_path = tmp.name
        try:
            return extract_text(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    except Exception as e:
        logger.warning(f"PDF download failed: {e}")
        return ""


# ── OpenAlex ──────────────────────────────────────────────────────────────────
def query_openalex(
    topic: str, pages: int = 2, per_page: int = 25, progress=None, filters: Optional[str] = None
) -> List[Dict]:
    results = []
    base_url = "https://api.openalex.org/works"
    for page in range(1, pages + 1):
        params: Dict = {"per-page": per_page, "page": page, "mailto": CONTACT_EMAIL}
        if topic:
            params["search"] = topic
        if filters:
            params["filter"] = filters
        try:
            r = requests.get(base_url, params=params, timeout=API_TIMEOUT, headers=HEADERS)
            r.raise_for_status()
            page_results = r.json().get("results", [])
            results.extend(page_results)
            if len(page_results) < per_page:
                break
        except Exception as e:
            logger.error(f"OpenAlex query failed: {e}")
        if progress:
            progress.progress(min(1.0, page / pages))
        time.sleep(API_DELAY)
    return results


def crossref_by_title(title: str) -> Optional[Dict]:
    if not title:
        return None
    try:
        params = {"query.title": title, "mailto": CONTACT_EMAIL}
        r = requests.get("https://api.crossref.org/works", params=params, timeout=20, headers=HEADERS)
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])
        if items and title.lower() in items[0].get("title", [""])[0].lower():
            return items[0]
        return None
    except Exception as e:
        logger.warning(f"CrossRef query failed: {e}")
        return None


def enrich_with_crossref(publications: List[Dict], progress=None) -> List[Dict]:
    for i, pub in enumerate(publications):
        if title := pub.get("title"):
            if item := crossref_by_title(title):
                pub["crossref"] = item
                pdf_link = next(
                    (str(l.get("URL")) for l in item.get("link", [])
                     if l.get("URL") and l.get("content-type") == "application/pdf"),
                    None,
                )
                if pdf_link:
                    pub["pdf_url"] = pdf_link
                if not pub.get("doi") and item.get("DOI"):
                    pub["doi"] = item.get("DOI")
        if progress:
            progress.progress((i + 1) / len(publications))
        time.sleep(API_DELAY * 0.5)
    return publications


# ── Semantic Scholar ──────────────────────────────────────────────────────────
def query_semantic_scholar(
    topic: str, limit: int = 100, api_key: Optional[str] = None
) -> List[Dict]:
    """Query the Semantic Scholar Graph API for papers matching a topic.

    Args:
        topic:   Search query string.
        limit:   Maximum number of papers to return.
        api_key: Optional S2 API key sent as the ``x-api-key`` request header.
                 Authenticated requests must stay under 1 request/second.
    """
    base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "title,abstract,year,authors,externalIds,venue"
    results, offset, batch_size = [], 0, min(100, limit)

    # Build per-request headers: include the API key when provided.
    req_headers = dict(HEADERS)
    if api_key:
        req_headers["x-api-key"] = api_key

    # S2 enforces 1 req/s for authenticated keys; 1.1 s keeps us safely under.
    ss_delay = 1.1 if api_key else API_DELAY

    while offset < limit:
        params = {"query": topic, "offset": offset, "limit": batch_size, "fields": fields}
        try:
            r = requests.get(base_url, params=params, timeout=API_TIMEOUT, headers=req_headers)
            r.raise_for_status()
            batch = r.json().get("data", [])
            results.extend(batch)
            if len(batch) < batch_size:
                break
            offset += batch_size
        except Exception as e:
            logger.error(f"Semantic Scholar query failed: {e}")
            break
        time.sleep(ss_delay)
    return results


def semantic_scholar_to_profiles(results: List[Dict]) -> List[Dict]:
    """Convert Semantic Scholar paper records to the shared researcher profile schema."""
    profiles: Dict[str, Dict] = {}
    for record in results:
        title = record.get("title")
        if not title:
            continue
        abstract = record.get("abstract") or ""
        year = record.get("year")
        doi = (record.get("externalIds") or {}).get("DOI", "")
        for author in record.get("authors", []):
            name = author.get("name")
            if not name:
                continue
            key = name.lower()
            if key not in profiles:
                profiles[key] = {"name": name, "orcid": None, "institution": "Unknown", "publications": []}
            profiles[key]["publications"].append(
                {"title": title, "doi": doi, "abstract": abstract, "year": year}
            )
    return list(profiles.values())


# ── arXiv ─────────────────────────────────────────────────────────────────────
_ARXIV_NS = {"atom": "http://www.w3.org/2005/Atom"}


def query_arxiv(topic: str, max_results: int = 100) -> list:
    """Query the arXiv API; returns a list of XML <entry> Element objects."""
    base_url = "http://export.arxiv.org/api/query"
    entries, start, batch_size = [], 0, min(100, max_results)
    while start < max_results:
        params = {"search_query": f"all:{topic}", "start": start, "max_results": batch_size}
        try:
            r = requests.get(base_url, params=params, timeout=API_TIMEOUT, headers=HEADERS)
            r.raise_for_status()
            root = ET.fromstring(r.text)
            batch = root.findall("atom:entry", _ARXIV_NS)
            entries.extend(batch)
            if len(batch) < batch_size:
                break
            start += batch_size
        except Exception as e:
            logger.error(f"arXiv query failed: {e}")
            break
        time.sleep(3)  # arXiv Terms of Service: use a polite delay
    return entries


def arxiv_to_profiles(entries: list) -> List[Dict]:
    """Convert arXiv Atom XML entries to the shared researcher profile schema."""
    profiles: Dict[str, Dict] = {}
    for entry in entries:
        title_el = entry.find("atom:title", _ARXIV_NS)
        title = normalize_ws(title_el.text) if title_el is not None else None
        if not title:
            continue
        summary_el = entry.find("atom:summary", _ARXIV_NS)
        abstract = normalize_ws(summary_el.text) if summary_el is not None else ""
        year = None
        published_el = entry.find("atom:published", _ARXIV_NS)
        if published_el is not None and published_el.text:
            try:
                year = int(published_el.text[:4])
            except (ValueError, TypeError):
                pass
        doi = ""
        for link in entry.findall("atom:link", _ARXIV_NS):
            if link.get("title") == "doi":
                doi = link.get("href", "")
                break
        for author_el in entry.findall("atom:author", _ARXIV_NS):
            name_el = author_el.find("atom:name", _ARXIV_NS)
            if name_el is None or not name_el.text:
                continue
            name = normalize_ws(name_el.text)
            key = name.lower()
            if key not in profiles:
                profiles[key] = {"name": name, "orcid": None, "institution": "Unknown", "publications": []}
            profiles[key]["publications"].append(
                {"title": title, "doi": doi, "abstract": abstract, "year": year}
            )
    return list(profiles.values())


# ── PubMed (NCBI E-utilities) ─────────────────────────────────────────────────
def query_pubmed(topic: str, max_results: int = 100, api_key: Optional[str] = None) -> List[str]:
    """Return a list of PubMed IDs matching the topic via esearch."""
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    ids, retstart, batch_size = [], 0, min(100, max_results)
    while retstart < max_results:
        params: Dict = {
            "db": "pubmed", "term": topic, "retmax": batch_size,
            "retstart": retstart, "retmode": "json",
            "tool": "researchmatch", "email": CONTACT_EMAIL,
        }
        if api_key:
            params["api_key"] = api_key
        try:
            r = requests.get(base_url, params=params, timeout=API_TIMEOUT, headers=HEADERS)
            r.raise_for_status()
            batch_ids = r.json().get("esearchresult", {}).get("idlist", [])
            ids.extend(batch_ids)
            if len(batch_ids) < batch_size:
                break
            retstart += batch_size
        except Exception as e:
            logger.error(f"PubMed esearch failed: {e}")
            break
        time.sleep(API_DELAY)
    return ids


def fetch_pubmed_details(pmids: List[str], api_key: Optional[str] = None) -> list:
    """Fetch full PubMed XML article records for a list of PMIDs via efetch."""
    if not pmids:
        return []
    base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    articles, batch_size = [], 50
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i : i + batch_size]
        params: Dict = {
            "db": "pubmed", "id": ",".join(batch), "retmode": "xml",
            "rettype": "abstract", "tool": "researchmatch", "email": CONTACT_EMAIL,
        }
        if api_key:
            params["api_key"] = api_key
        try:
            r = requests.get(base_url, params=params, timeout=API_TIMEOUT, headers=HEADERS)
            r.raise_for_status()
            root = ET.fromstring(r.text)
            articles.extend(root.findall(".//PubmedArticle"))
        except Exception as e:
            logger.error(f"PubMed efetch failed: {e}")
        time.sleep(API_DELAY)
    return articles


def pubmed_to_profiles(articles: list) -> List[Dict]:
    """Convert PubMed XML article elements to the shared researcher profile schema."""
    profiles: Dict[str, Dict] = {}
    for article in articles:
        title_el = article.find(".//ArticleTitle")
        title = normalize_ws(title_el.text) if title_el is not None else None
        if not title:
            continue
        abstract = " ".join(
            normalize_ws(a.text or "") for a in article.findall(".//AbstractText")
        )
        year = None
        year_el = article.find(".//PubDate/Year")
        if year_el is not None and year_el.text:
            try:
                year = int(year_el.text)
            except (ValueError, TypeError):
                pass
        doi = ""
        for id_el in article.findall(".//ArticleId"):
            if id_el.get("IdType") == "doi":
                doi = id_el.text or ""
                break
        for author_el in article.findall(".//Author"):
            last = author_el.findtext("LastName", "")
            fore = author_el.findtext("ForeName", "")
            name = normalize_ws(f"{fore} {last}").strip()
            if not name:
                continue
            affil_el = author_el.find(".//AffiliationInfo/Affiliation")
            institution = (
                normalize_ws(affil_el.text)[:200]
                if affil_el is not None and affil_el.text
                else "Unknown"
            )
            key = name.lower()
            if key not in profiles:
                profiles[key] = {"name": name, "orcid": None, "institution": institution, "publications": []}
            profiles[key]["publications"].append(
                {"title": title, "doi": doi, "abstract": abstract, "year": year}
            )
    return list(profiles.values())


# ── DOAJ ──────────────────────────────────────────────────────────────────────
def scrape_doaj(topic: str, pages: int = 1) -> List[Dict]:
    """Query the DOAJ REST API for open-access articles on a topic."""
    results = []
    base_url = "https://doaj.org/api/search/articles"
    for page in range(1, pages + 1):
        params = {"q": topic, "page": page, "pageSize": 50}
        try:
            r = requests.get(base_url, params=params, timeout=API_TIMEOUT, headers=HEADERS)
            r.raise_for_status()
            for item in r.json().get("results", []):
                bib = item.get("bibjson", {})
                title = bib.get("title", "")
                abstract = bib.get("abstract", "")
                year = None
                if yr := bib.get("year"):
                    try:
                        year = int(yr)
                    except (ValueError, TypeError):
                        pass
                doi = next(
                    (i["id"] for i in bib.get("identifier", []) if i.get("type") == "doi"), ""
                )
                if title:
                    results.append({"title": title, "abstract": abstract, "year": year, "doi": doi})
        except Exception as e:
            logger.warning(f"DOAJ query failed on page {page}: {e}")
        time.sleep(API_DELAY)
    return results


# ── Shared pipeline helpers ───────────────────────────────────────────────────
def reconstruct_openalex_abstract(abstract_raw) -> str:
    if isinstance(abstract_raw, dict):
        try:
            word_map: Dict[int, str] = {}
            for word, indices in abstract_raw.items():
                for index in indices:
                    word_map[index] = word
            if not word_map:
                return ""
            return " ".join(word_map.get(i, "") for i in range(max(word_map.keys()) + 1))
        except Exception as e:
            logger.error(f"Abstract reconstruction failed: {e}")
            return ""
    return str(abstract_raw) if abstract_raw else ""


def openalex_to_profiles(openalex_results: List[Dict]) -> List[Dict]:
    profiles: Dict[str, Dict] = {}
    for record in openalex_results:
        if not (title := record.get("title")):
            continue
        abstract_text = reconstruct_openalex_abstract(record.get("abstract_inverted_index"))
        doi = record.get("doi") or ""
        try:
            pub_year = int(record.get("publication_year")) if record.get("publication_year") else None
        except (ValueError, TypeError):
            pub_year = None
        for authorship in record.get("authorships", []):
            author_info = authorship.get("author")
            if not author_info or not author_info.get("display_name"):
                continue
            name = author_info["display_name"]
            orcid = author_info.get("orcid")
            inst_list = authorship.get("institutions", [])
            institution = (
                inst_list[0].get("display_name")
                if inst_list and inst_list[0].get("display_name")
                else "Unknown"
            )
            key = f"{name}|{orcid or ''}"
            if key not in profiles:
                profiles[key] = {"name": name, "orcid": orcid, "institution": institution, "publications": []}
            profiles[key]["publications"].append(
                {"title": title, "doi": doi, "abstract": abstract_text, "year": pub_year}
            )
    return list(profiles.values())


def tag_publications(profiles: List[Dict], source: str, **kwargs):
    for p in profiles:
        for pub in p.get("publications", []):
            pub["source"] = source
            for k, v in kwargs.items():
                if v:
                    pub[k] = v


def combine_researcher_text(researcher: dict, max_chars: int = MAX_CHARS) -> str:
    texts = [
        text.strip()
        for p in researcher.get("publications", [])
        if (text := p.get("full_text") or p.get("abstract") or p.get("title"))
    ]
    combined = " ".join(texts)
    if len(combined) <= max_chars:
        return combined
    truncated = combined[:max_chars]
    last_period = truncated.rfind(". ")
    return truncated[: last_period + 1] if last_period > max_chars * 0.8 else truncated


def fetch_and_enrich_openalex(results: List[Dict], progress=None) -> List[Dict]:
    enriched = enrich_with_crossref(results, progress=progress)
    for rec in enriched:
        if pdf_url := rec.get("pdf_url"):
            if full_text := download_and_extract_pdf(pdf_url):
                rec["full_text"] = full_text
    return enriched
