"""
Core utilities: file I/O, API interactions, and data transformation.
"""
import os
import re
import time
import logging
from typing import List, Dict, Optional
import requests
import fitz # PyMuPDF
from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse
from docx import Document # python-docx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

STOPWORDS = set("a an and are as at be but by for from has have if in into is it its of on or than that the their them then there these they this to was were will with within without using used based among between across under over via while due can could should would may might".split())
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{2,}")
API_TIMEOUT, API_DELAY, MAX_CHARS = 30, 0.15, 60000
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def normalize_ws(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()

def tokenize_words(text: str) -> List[str]:
    return [t for t in TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]

def extract_text(filepath: str) -> str:
    try:
        if filepath.lower().endswith('.pdf'):
            with fitz.open(filepath) as doc:
                return " ".join([page.get_text() for page in doc]).strip()
        elif filepath.lower().endswith('.docx'):
            return " ".join([p.text for p in Document(filepath).paragraphs]).strip()
        logger.warning(f"Unsupported file type: {filepath}")
        return ""
    except Exception as e:
        logger.error(f"Text extraction failed: {e}")
        return ""

def safe_file_upload(uploaded_file, tmp_dir: str = "tmp") -> Optional[str]:
    if not uploaded_file:
        return None
    os.makedirs(tmp_dir, exist_ok=True)
    safe_filename = re.sub(r'[\\/*?:"<>|]', "", os.path.basename(uploaded_file.name))
    tmp_path = os.path.join(tmp_dir, safe_filename)
    try:
        with open(tmp_path, "wb") as f:
            for chunk in uploaded_file:
                f.write(chunk)
        return tmp_path
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        return None

def query_openalex(topic: str, pages: int = 2, per_page: int = 25, progress=None, filters: Optional[str] = None) -> List[Dict]:
    results = []
    base_url = "https://api.openalex.org/works"
    
    for page in range(1, pages + 1):
        params = {"per-page": per_page, "page": page}
        if topic: params["search"] = topic
        if filters: params["filter"] = filters
        
        try:
            r = requests.get(base_url, params=params, timeout=API_TIMEOUT, headers=HEADERS)
            r.raise_for_status()
            data = r.json()
            page_results = data.get("results", [])
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
        params = {'query.title': title, 'mailto': 'research@example.com'}
        response = requests.get("https://api.crossref.org/works", params=params, timeout=20, headers=HEADERS)
        response.raise_for_status()
        items = response.json().get("message", {}).get("items", [])
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
                pdf_link = next((str(l.get("URL")) for l in item.get("link", []) 
                                if l.get("URL") and l.get("content-type") == "application/pdf"), None)  # Extract PDF URL from CrossRef metadata
                if pdf_link:
                    pub["pdf_url"] = pdf_link
                if not pub.get("doi") and item.get("DOI"):
                     pub["doi"] = item.get("DOI")
        if progress:
             progress.progress((i + 1) / len(publications))
        time.sleep(API_DELAY * 0.5)
    return publications

def download_and_extract_pdf(pdf_url: str, save_dir: str = "pdfs") -> str:
    try:
        parsed = urlparse(pdf_url)
        if parsed.hostname in ["localhost", "127.0.0.1"] or (parsed.hostname or "").startswith(("192.168.", "10.", "172.16.")):  # Block local/private IPs for security
            return ""
        
        os.makedirs(save_dir, exist_ok=True)
        base_name = os.path.basename(parsed.path) if parsed.path else "paper"
        sanitized_name = re.sub(r'[\\/*?:"<>|]', "_", base_name)
        if not sanitized_name.lower().endswith('.pdf'):
             sanitized_name = os.path.splitext(sanitized_name)[0] + ".pdf"
        if len(sanitized_name) > 100:
             name_part, ext = os.path.splitext(sanitized_name)
             sanitized_name = name_part[:100 - len(ext)] + ext

        filename = os.path.join(save_dir, sanitized_name)
        r = requests.get(pdf_url, timeout=20, headers=HEADERS, stream=True)
        r.raise_for_status()

        if "application/pdf" in r.headers.get("Content-Type", "").lower():
            with open(filename, "wb") as f:
                 for chunk in r.iter_content(chunk_size=8192):
                      f.write(chunk)
            return extract_text(filename)
        return ""
    except Exception as e:
        logger.warning(f"PDF download failed: {e}")
        return ""


def reconstruct_openalex_abstract(abstract_raw) -> str:
    if isinstance(abstract_raw, dict):
        try:
            word_map = {}  # Reconstruct abstract from OpenAlex's inverted index format
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
    profiles = {}
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
            institution = inst_list[0].get("display_name") if inst_list and inst_list[0].get("display_name") else "Unknown"
            
            key = f"{name}|{orcid or ''}"
            if key not in profiles:
                profiles[key] = {"name": name, "orcid": orcid, "institution": institution, "publications": []}
            
            profiles[key]["publications"].append({
                "title": title, "doi": doi, "abstract": abstract_text, "year": pub_year
            })
            
    return list(profiles.values())

def tag_publications(profiles: List[Dict], source: str, **kwargs):
    for p in profiles:
        for pub in p.get("publications", []):
            pub["source"] = source
            for k, v in kwargs.items():
                if v:
                    pub[k] = v

def combine_researcher_text(researcher: dict, max_chars: int = MAX_CHARS) -> str:
    texts = [text.strip() for p in researcher.get("publications", []) 
             if (text := p.get("full_text") or p.get("abstract") or p.get("title"))]  # Prioritize full_text > abstract > title
    combined = " ".join(texts)
    if len(combined) <= max_chars:
        return combined
    truncated = combined[:max_chars]
    last_period = truncated.rfind(". ")
    return truncated[:last_period + 1] if last_period > max_chars * 0.8 else truncated

def fetch_and_enrich_openalex(results: List[Dict], progress=None) -> List[Dict]:
    enriched_results = enrich_with_crossref(results, progress=progress)
    for rec in enriched_results:
        if pdf_url := rec.get("pdf_url"):
            if full_text := download_and_extract_pdf(pdf_url):
                rec["full_text"] = full_text
    return enriched_results
