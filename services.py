"""Core services: embeddings, keywords, clustering, matching."""
import numpy as np
import logging
from typing import List, Dict, Tuple
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.metrics import silhouette_score
from core import (tokenize_words, normalize_ws, query_openalex, fetch_and_enrich_openalex, 
                  openalex_to_profiles, tag_publications, STOPWORDS)

logger = logging.getLogger(__name__)

# Keyword extraction
cand_ngrams = lambda words, max_len=2: [phrase for L in range(1, max_len+1) 
                                        for i in range(len(words)-L+1) 
                                        if len(phrase := " ".join(words[i:i+L])) >= 4 
                                        and not all(w in STOPWORDS for w in phrase.split())]

def cand_noun_chunks(text: str, nlp) -> List[str]:
    """Extract noun chunks from text using spaCy. Truncates long text to prevent memory errors."""
    if len(text) > 1000000: text = text[:1000000]  # Stay under spaCy limit
    return [normalize_ws(ch.text.lower()) for ch in nlp(text).noun_chunks 
            if len(s := normalize_ws(ch.text.lower())) >= 4 
            and not all(w in STOPWORDS for w in s.split())]

def derive_top_keywords_hybrid(text: str, k: int, model, nlp) -> List[str]:
    """Extract top-k keywords using hybrid spaCy + embedding re-ranking."""
    if not (text := normalize_ws(text)): return []
    base_cands = list(set(cand_ngrams(tokenize_words(text)) + cand_noun_chunks(text, nlp)))
    if not base_cands: return []
    
    # Filter noise: URLs, common phrases, very long phrases, proper names
    noise_patterns = ["author's personal copy", "http://", "https://", "www.", ".com", ".org", ".edu", 
                     "copy fusion", "personal copy"]
    filtered_cands = [c for c in base_cands 
                     if not any(noise in c.lower() for noise in noise_patterns)
                     and len(c) < 60  # Max 60 chars
                     and (not c[0].isupper() or len(c.split()) <= 2)]  # Allow short proper nouns, filter long ones
    
    if not filtered_cands: return []
    
    doc_vec = model.encode([text], convert_to_tensor=False, normalize_embeddings=True)
    cand_vecs = model.encode(filtered_cands, convert_to_tensor=False, normalize_embeddings=True)
    sims = (np.array(doc_vec) @ np.array(cand_vecs).T).ravel()
    
    ranked, seen = [], set()
    for idx in np.argsort(-sims):
        c = filtered_cands[idx]
        if not any(c in p or p in c for p in seen):
            ranked.append(c)
            seen.add(c)
            if len(ranked) >= k: break
    return ranked

# Clustering
def auto_k_by_silhouette(X: np.ndarray, k_min: int = 2, k_max: int = 10) -> int:
    """Find optimal k using silhouette score (uses euclidean for normalized embeddings)."""
    if len(X) < k_min: return 1
    best_k, best_score = None, -1.0
    for k in range(k_min, min(k_max, len(X)) + 1):
        try:
            labels = KMeans(n_clusters=k, n_init="auto", random_state=42).fit_predict(X)
            if len(set(labels)) > 1 and (s := silhouette_score(X, labels, metric="euclidean")) > best_score:
                best_score, best_k = s, k
        except Exception as e:
            logger.error(f"Clustering failed for k={k}: {e}")
    # Return best k found, or default to 2 clusters if score is poor but documents differ
    if best_k:
        return best_k
    # Fallback: try 2 clusters if no good score found
    return min(2, len(X))

def cluster_upload_docs(upload_texts: List[str], model, nlp) -> List[Dict]:
    """Cluster uploaded documents into themes."""
    if len(upload_texts) == 1:
        return [{"theme_label": ", ".join(derive_top_keywords_hybrid(upload_texts[0], k=3, model=model, nlp=nlp)) or "Theme 1",
                "doc_indices": [0], "combined_text": upload_texts[0]}]
    
    X = np.array(model.encode(upload_texts, convert_to_tensor=False, normalize_embeddings=True))
    k = auto_k_by_silhouette(X, 2, min(10, len(upload_texts)))
    logger.info(f"Clustering {len(upload_texts)} documents into {k} themes")
    
    if k == 1:
        combined = " ".join(upload_texts)
        return [{"theme_label": ", ".join(derive_top_keywords_hybrid(combined, k=3, model=model, nlp=nlp)) or "Theme 1",
                "doc_indices": list(range(len(upload_texts))), "combined_text": combined}]
    
    # Use AgglomerativeClustering with cosine distance for better text clustering
    try:
        labels = AgglomerativeClustering(n_clusters=k, metric="cosine", linkage="average").fit_predict(X)
    except Exception:
        # Fallback to KMeans if AgglomerativeClustering fails
        labels = KMeans(n_clusters=k, n_init="auto", random_state=42).fit_predict(X)
    
    clusters = {lab: [i for i, l in enumerate(labels) if l == lab] for lab in set(labels)}
    
    results = []
    for lab, idxs in clusters.items():
        combined = " ".join(upload_texts[i] for i in idxs)
        results.append({"theme_label": ", ".join(derive_top_keywords_hybrid(combined, k=3, model=model, nlp=nlp)) or f"Theme {lab+1}",
                       "doc_indices": idxs, "combined_text": combined})
    return results

# Corpus building
def discover_profiles_from_upload(text: str, pages: int, per_page: int, seed_label: str, model, nlp) -> Tuple[List[Dict], Dict]:
    """Discover profiles from uploaded text using hybrid keywords with fallback."""
    stats = {"primary": 0, "fallback": 0, "fallback_used": False}
    if not (kws := derive_top_keywords_hybrid(text, k=8, model=model, nlp=nlp)):
        return [], stats
    
    # Primary query
    ox = fetch_and_enrich_openalex(query_openalex((query := " ".join(kws)), pages=pages, per_page=per_page))
    profiles = openalex_to_profiles(ox)
    tag_publications(profiles, source="OpenAlex", topic=query, seed=f"upload:{seed_label}")
    stats["primary"] = len(profiles)
    
    # Fallback with fewer keywords
    if not profiles and len(kws) >= 2:
        stats["fallback_used"] = True
        kws_fb = kws[:min(3, max(2, len(kws)//3))]
        ox2 = fetch_and_enrich_openalex(query_openalex((query_fb := " ".join(kws_fb)), pages=pages, per_page=per_page))
        profiles = openalex_to_profiles(ox2)
        tag_publications(profiles, source="OpenAlex", topic=query_fb, seed=f"upload:{seed_label}")
        stats["fallback"] = len(profiles)
    
    return profiles, stats

def build_corpus_from_keywords(topic: str, pages: int, per_page: int, doaj_pages: int, progress_callback) -> List[Dict]:
    """Build corpus from keyword-based queries."""
    if not topic: return []
    
    ox = fetch_and_enrich_openalex(query_openalex(topic, pages=pages, per_page=per_page, progress=progress_callback), 
                                   progress=progress_callback)
    profiles = openalex_to_profiles(ox)
    tag_publications(profiles, source="OpenAlex", topic=topic)
    
    if doaj_pages > 0:
        from core import scrape_doaj
        if doaj_records := scrape_doaj(topic, pages=doaj_pages, progress=progress_callback):
            profiles.append({"name": "DOAJ Records", "orcid": None, "institution": "Open Access", "publications": doaj_records})
    return profiles
