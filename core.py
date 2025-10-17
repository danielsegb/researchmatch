"""Core functions for text processing, file I/O, and API calls."""
import os
import re
import time
import logging
from typing import List, Dict, Optional
import requests
import fitz
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse
from docx import Document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
STOPWORDS = set("a an and are as at be but by for from has have if in into is it its of on or than that the their them then there these they this to was were will with within without using used based among between across under over via while due can could should would may might".split())
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
API_TIMEOUT, API_DELAY, MAX_CHARS = 30, 0.25, 60000

# Text processing
normalize_ws = lambda text: re.sub(r"\s+", " ", (text or "")).strip()
tokenize_words = lambda text: [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]

# File I/O - Merged extract functions
def extract_text(filepath: str) -> str:
    """Extract text from PDF or DOCX file."""
    try:
        if filepath.endswith('.pdf'):
            doc = fitz.open(filepath)
            text = " ".join([page.get_text() for page in doc])
            doc.close()
            return text.strip()
        else:  # .docx
            return " ".join([p.text for p in Document(filepath).paragraphs]).strip()
    except Exception as e:
        logger.error(f"Text extraction failed for {filepath}: {e}")
        return ""

def safe_file_upload(uploaded_file, tmp_dir: str = "tmp") -> Optional[str]:
    """Safely handle file upload with path traversal protection."""
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, os.path.basename(uploaded_file.name))
    try:
        with open(tmp_path, "wb") as f:
            f.write(uploaded_file.read())
        return tmp_path
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        return None

# API calls
def query_openalex(topic: str, pages: int = 2, per_page: int = 25, progress=None, filters: Optional[str] = None) -> List[Dict]:
    """Query OpenAlex API with optional filters."""
    results = []
    for page in range(1, pages + 1):
        params = {"per-page": per_page, "page": page}
        if topic: params["search"] = topic
        if filters: params["filter"] = filters
        try:
            r = requests.get("https://api.openalex.org/works", params=params, timeout=API_TIMEOUT)
            if r.status_code == 200:
                results.extend(r.json().get("results", []))
        except Exception as e:
            logger.error(f"OpenAlex query failed: {e}")
        if progress: progress.progress(page / pages)
        time.sleep(API_DELAY)
    return results

def crossref_by_title(title: str) -> Optional[Dict]:
    """Query CrossRef for publication metadata by title."""
    try:
        return requests.get(f"https://api.crossref.org/works?query.title={quote(title)}", 
                          timeout=20).json().get("message", {}).get("items", [None])[0]
    except Exception as e:
        logger.error(f"CrossRef query failed for '{title}': {e}")
        return None

def enrich_with_crossref(publications: List[Dict], progress=None) -> List[Dict]:
    """Enrich publications with CrossRef metadata and PDF links."""
    for i, pub in enumerate(publications, start=1):
        if title := pub.get("title"):
            if item := crossref_by_title(title):
                pub["crossref"] = item
                if link := next((l.get("URL") for l in item.get("link", []) 
                               if l.get("content-type") == "application/pdf"), None):
                    pub["pdf_url"] = link
        if progress: progress.progress(i / (len(publications) or 1))
        time.sleep(0.12)
    return publications

def download_and_extract_pdf(pdf_url: str, save_dir: str = "pdfs") -> str:
    """Download PDF and extract text with SSRF (Server Side Request Forgery) protection."""
    parsed = urlparse(pdf_url)
    if parsed.hostname in ["localhost", "127.0.0.1"] or (parsed.hostname or "").startswith("192.168."):
        logger.warning(f"Blocked internal URL: {pdf_url}")
        return ""
    
    os.makedirs(save_dir, exist_ok=True)
    try:
        filename = os.path.join(save_dir, pdf_url.split("?")[0].split("/")[-1] or "paper.pdf")
        r = requests.get(pdf_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and r.content:
            with open(filename, "wb") as f:
                f.write(r.content)
            return extract_text(filename)
    except Exception as e:
        logger.error(f"PDF download failed for {pdf_url}: {e}")
    return ""

def scrape_doaj(topic: str, pages: int = 1, progress=None) -> List[Dict]:
    """Scrape DOAJ for open access articles."""
    scraped = []
    for page in range(1, pages + 1):
        try:
            soup = BeautifulSoup(requests.get(
                f"https://www.doaj.org/search/articles?ref=homepage&q={quote(topic)}&page={page}", 
                timeout=20, headers={"User-Agent": "Mozilla/5.0"}).content, "html.parser")
            for c in soup.select("div.search-result"):
                if t := c.select_one("h3 a"):
                    abstract = c.select_one("div.abstract")
                    scraped.append({"source": "DOAJ", "title": t.get_text(strip=True),
                                  "link": "https://www.doaj.org" + t.get("href", ""),
                                  "abstract": abstract.get_text(strip=True) if abstract else "", 
                                  "topic": topic})
        except Exception as e:
            logger.error(f"DOAJ scrape failed: {e}")
        if progress: progress.progress(page / pages)
        time.sleep(API_DELAY)
    return scraped

# Profile processing
def reconstruct_openalex_abstract(abstract_raw) -> str:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if isinstance(abstract_raw, dict):
        positions = [(i, word) for word, idxs in abstract_raw.items() for i in idxs]
        return " ".join([w for _, w in sorted(positions)])
    return str(abstract_raw) if abstract_raw else ""

def openalex_to_profiles(openalex_results: List[Dict]) -> List[Dict]:
    """Convert OpenAlex results to researcher profiles."""
    profiles = {}
    for record in openalex_results:
        title, doi = record.get("title"), record.get("doi", "")
        year = record.get("publication_year")
        if not year and (pub_date := record.get("publication_date")):
            year = int(m.group(1)) if (m := re.match(r"(\d{4})", str(pub_date))) else None
        
        abstract_text = reconstruct_openalex_abstract(
            record.get("abstract_inverted_index") or record.get("abstract"))
        
        for author in record.get("authorships", []):
            aobj = author.get("author") or {}
            name, orcid = aobj.get("display_name", "Unknown"), aobj.get("orcid")
            inst_list = author.get("institutions", [])
            institution = inst_list[0].get("display_name", "Unknown Institution") if inst_list else "Unknown Institution"
            
            key = f"{name}|{orcid or ''}"
            if key not in profiles:
                profiles[key] = {"name": name, "orcid": orcid, "institution": institution, "publications": []}
            profiles[key]["publications"].append({"title": title, "doi": doi, "abstract": abstract_text, "year": year})
    return list(profiles.values())

def tag_publications(profiles: List[Dict], source: str, topic: Optional[str] = None, 
                    seed: Optional[str] = None, enrich_note: Optional[str] = None):
    """Mutates profiles in-place by adding tags to publications."""
    for p in profiles:
        for pub in p.get("publications", []):
            pub.update({"source": source} | 
                      ({k: v for k, v in [("topic", topic), ("seed_source", seed), 
                                         ("enrichment", enrich_note)] if v}))

def combine_researcher_text(researcher: dict, max_chars: int = MAX_CHARS) -> str:
    """Combine all publication texts for a researcher with smart truncation."""
    combined = " ".join(filter(None, [(p.get("full_text") or p.get("abstract") or "").strip() 
                                      for p in researcher.get("publications", [])]))
    if len(combined) > max_chars:
        combined = combined[:max_chars]
        if (last_period := combined.rfind(". ")) > max_chars * 0.8:
            combined = combined[:last_period + 1]
    return combined.strip()

def fetch_and_enrich_openalex(results: List[Dict], progress=None) -> List[Dict]:
    """Function to enrich OpenAlex results with CrossRef and full-text."""
    enriched = enrich_with_crossref(results, progress=progress)
    for rec in enriched:
        if rec.get("pdf_url") and (ft := download_and_extract_pdf(rec["pdf_url"])):
            rec["full_text"] = ft
    return enriched
