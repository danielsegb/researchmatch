"""
NLP tasks: keyword extraction, document clustering, and multi-source corpus building.
Sources: OpenAlex, CrossRef, Semantic Scholar, arXiv, PubMed, DOAJ.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Optional

import numpy as np
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.metrics import silhouette_score

from core import (
    tokenize_words, normalize_ws, STOPWORDS,
    query_openalex, fetch_and_enrich_openalex, openalex_to_profiles,
    tag_publications, scrape_doaj,
    query_semantic_scholar, semantic_scholar_to_profiles,
    query_arxiv, arxiv_to_profiles,
    query_pubmed, fetch_pubmed_details, pubmed_to_profiles,
)

logger = logging.getLogger(__name__)


# ── Keyword extraction ────────────────────────────────────────────────────────
def cand_ngrams(words: List[str], max_len: int = 2) -> List[str]:
    phrases = set()
    for L in range(1, max_len + 1):
        for i in range(len(words) - L + 1):
            phrase = " ".join(words[i : i + L])
            if len(phrase) >= 4 and not all(w in STOPWORDS for w in phrase.split()):
                phrases.add(phrase)
    return list(phrases)


def cand_noun_chunks(text: str, nlp) -> List[str]:
    if len(text) > nlp.max_length:
        text = text[: nlp.max_length]
    chunks = set()
    try:
        for chunk in nlp(text).noun_chunks:
            normalized = normalize_ws(chunk.text.lower())
            if len(normalized) >= 4 and not all(w in STOPWORDS for w in normalized.split()):
                chunks.add(normalized)
    except Exception as e:
        logger.error(f"Noun chunk extraction failed: {e}")
    return list(chunks)


def derive_top_keywords_hybrid(text: str, k: int, model, nlp) -> List[str]:
    if not (text := normalize_ws(text)):
        return []
    word_tokens = tokenize_words(text)
    base_cands = list(set(cand_ngrams(word_tokens) + cand_noun_chunks(text, nlp)))
    if not base_cands:
        return []
    noise = ["author's personal copy", "http", "www.", ".com", ".org", ".edu", "et al"]
    filtered_cands = [
        c for c in base_cands
        if not any(n in c.lower() for n in noise) and len(c) < 60
    ]
    if not filtered_cands:
        return []
    try:
        doc_vec = model.encode([text], convert_to_tensor=False, normalize_embeddings=True)
        cand_vecs = model.encode(filtered_cands, convert_to_tensor=False, normalize_embeddings=True)
        sims = (np.array(doc_vec) @ np.array(cand_vecs).T).ravel()
    except Exception as e:
        logger.error(f"Keyword similarity computation failed: {e}")
        return []
    ranked_keywords, seen_tokens = [], set()
    for idx in np.argsort(-sims):
        current_tokens = set(filtered_cands[idx].split())
        if not current_tokens & seen_tokens:
            ranked_keywords.append(filtered_cands[idx])
            seen_tokens.update(current_tokens)
            if len(ranked_keywords) >= k:
                break
    return ranked_keywords


# ── Document clustering ───────────────────────────────────────────────────────
def auto_k_by_silhouette(X: np.ndarray, k_min: int = 2, k_max: int = 10) -> int:
    if X.shape[0] <= k_min:
        return 1
    best_k, best_score = 1, -1.0
    for k in range(k_min, min(k_max, X.shape[0])):
        try:
            labels = KMeans(n_clusters=k, n_init="auto", random_state=42).fit_predict(X)
            if len(set(labels)) > 1:
                score = silhouette_score(X, labels, metric="euclidean")
                if score > best_score:
                    best_score, best_k = score, k
        except Exception as e:
            logger.error(f"KMeans failed for k={k}: {e}")
    return best_k


def cluster_upload_docs(upload_texts: List[str], model, nlp) -> List[Dict]:
    if not upload_texts:
        return []
    if len(upload_texts) == 1:
        kw = ", ".join(derive_top_keywords_hybrid(upload_texts[0], k=3, model=model, nlp=nlp)) or "Primary Theme"
        return [{"theme_label": kw, "doc_indices": [0], "combined_text": upload_texts[0]}]
    try:
        X = np.array(model.encode(upload_texts, convert_to_tensor=False, normalize_embeddings=True))
    except Exception as e:
        logger.error(f"Encoding failed: {e}")
        combined = " ".join(upload_texts)
        kw = ", ".join(derive_top_keywords_hybrid(combined, k=3, model=model, nlp=nlp)) or "Primary Theme"
        return [{"theme_label": kw, "doc_indices": list(range(len(upload_texts))), "combined_text": combined}]

    k = auto_k_by_silhouette(X, 2, min(10, len(upload_texts)))
    if k == 1:
        combined = " ".join(upload_texts)
        kw = ", ".join(derive_top_keywords_hybrid(combined, k=3, model=model, nlp=nlp)) or "Primary Theme"
        return [{"theme_label": kw, "doc_indices": list(range(len(upload_texts))), "combined_text": combined}]

    try:
        labels = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(X)
    except Exception:
        try:
            labels = KMeans(n_clusters=k, n_init="auto", random_state=42).fit_predict(X)
        except Exception as e:
            logger.error(f"Clustering failed: {e}")
            combined = " ".join(upload_texts)
            kw = ", ".join(derive_top_keywords_hybrid(combined, k=3, model=model, nlp=nlp)) or "Primary Theme"
            return [{"theme_label": kw, "doc_indices": list(range(len(upload_texts))), "combined_text": combined}]

    clusters: Dict[int, List[int]] = {}
    for i, label in enumerate(labels):
        clusters.setdefault(int(label), []).append(i)

    results = []
    for label, indices in clusters.items():
        combined = " ".join(upload_texts[i] for i in indices)
        kw = ", ".join(derive_top_keywords_hybrid(combined, k=3, model=model, nlp=nlp)) or f"Theme {label + 1}"
        results.append({"theme_label": kw, "doc_indices": indices, "combined_text": combined})
    return results


# ── Upload-driven discovery ───────────────────────────────────────────────────
def discover_profiles_from_upload(
    text: str, pages: int, per_page: int, seed_label: str, model, nlp
) -> Tuple[List[Dict], Dict]:
    stats = {"primary": 0, "fallback": 0, "fallback_used": False}
    keywords = derive_top_keywords_hybrid(text, k=8, model=model, nlp=nlp)
    if not keywords:
        return [], stats

    query = " ".join(keywords)
    results = fetch_and_enrich_openalex(query_openalex(query, pages=pages, per_page=per_page))
    profiles = openalex_to_profiles(results)
    tag_publications(profiles, source="UploadSeed", topic=query, seed_source=seed_label)
    stats["primary"] = len(profiles)

    if not profiles and len(keywords) >= 2:
        stats["fallback_used"] = True
        fallback_kws = keywords[: min(3, max(2, len(keywords) // 3))]
        fallback_query = " ".join(fallback_kws)
        fallback_results = fetch_and_enrich_openalex(
            query_openalex(fallback_query, pages=pages, per_page=per_page)
        )
        profiles = openalex_to_profiles(fallback_results)
        tag_publications(profiles, source="UploadSeed", topic=fallback_query, seed_source=seed_label)
        stats["fallback"] = len(profiles)

    return profiles, stats


# ── Multi-source corpus building ──────────────────────────────────────────────
def build_corpus_from_keywords(
    topic: str,
    pages: int,
    per_page: int,
    doaj_pages: int,
    progress_callback,
    use_openalex: bool = True,
    use_semantic_scholar: bool = True,
    use_arxiv: bool = True,
    use_pubmed: bool = True,
    ncbi_api_key: Optional[str] = None,
) -> List[Dict]:
    """Query all enabled academic APIs in parallel, tag and merge results."""
    if not topic:
        return []

    limit = pages * per_page

    def fetch_openalex() -> List[Dict]:
        r = fetch_and_enrich_openalex(
            query_openalex(topic, pages=pages, per_page=per_page, progress=progress_callback)
        )
        p = openalex_to_profiles(r)
        tag_publications(p, source="OpenAlex", topic=topic)
        return p

    def fetch_ss() -> List[Dict]:
        r = query_semantic_scholar(topic, limit=limit)
        p = semantic_scholar_to_profiles(r)
        tag_publications(p, source="Semantic Scholar", topic=topic)
        return p

    def fetch_arxiv() -> List[Dict]:
        r = query_arxiv(topic, max_results=limit)
        p = arxiv_to_profiles(r)
        tag_publications(p, source="arXiv", topic=topic)
        return p

    def fetch_pubmed() -> List[Dict]:
        ids = query_pubmed(topic, max_results=limit, api_key=ncbi_api_key)
        articles = fetch_pubmed_details(ids, api_key=ncbi_api_key)
        p = pubmed_to_profiles(articles)
        tag_publications(p, source="PubMed", topic=topic)
        return p

    source_funcs: Dict[str, callable] = {}
    if use_openalex:
        source_funcs["OpenAlex"] = fetch_openalex
    if use_semantic_scholar:
        source_funcs["Semantic Scholar"] = fetch_ss
    if use_arxiv:
        source_funcs["arXiv"] = fetch_arxiv
    if use_pubmed:
        source_funcs["PubMed"] = fetch_pubmed

    all_profiles: List[Dict] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fn): name for name, fn in source_funcs.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                all_profiles.extend(future.result())
                logger.info(f"{name}: fetch completed.")
            except Exception as e:
                logger.error(f"{name} corpus fetch failed: {e}")

    if doaj_pages > 0:
        if doaj_records := scrape_doaj(topic, pages=doaj_pages):
            doaj_profile = {
                "name": f"DOAJ Open Access ({topic})",
                "orcid": None,
                "institution": "Directory of Open Access Journals",
                "publications": doaj_records,
            }
            tag_publications([doaj_profile], source="DOAJ", topic=topic)
            all_profiles.append(doaj_profile)

    return all_profiles
