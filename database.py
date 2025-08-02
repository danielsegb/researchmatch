"""MongoDB operations with connection pooling."""
import logging
from typing import List, Dict, Tuple
from pymongo import MongoClient, UpdateOne
import streamlit as st

logger = logging.getLogger(__name__)

# Singleton client (fixes connection leak)
get_mongo_client = lambda uri: st.session_state.setdefault("mongo_client", MongoClient(uri))
get_collection = lambda uri, db, coll: get_mongo_client(uri)[db][coll]
profile_key = lambda p: (p.get("name", "").strip().lower(), (p.get("orcid") or "").strip().lower())

def insert_profiles(coll, profiles: List[Dict]) -> Tuple[int, int]:
    """Insert profiles with deduplication. Returns (inserted, skipped)."""
    if not profiles: return 0, 0
    
    existing_keys = {profile_key(doc) for doc in coll.find({}, {"name": 1, "orcid": 1})}
    deduped, skipped = [], 0
    batch_keys = set()
    
    for p in profiles:
        if (k := profile_key(p)) in existing_keys or k in batch_keys:
            skipped += 1
        else:
            batch_keys.add(k)
            deduped.append(p)
    
    if not deduped: return 0, skipped
    
    try:
        try: coll.create_index([("name", 1), ("orcid", 1)], unique=True)
        except: pass
        return len(coll.insert_many(deduped, ordered=False).inserted_ids), skipped
    except Exception as e:
        logger.error(f"MongoDB insertion failed: {e}")
        inserted = sum(1 for p in deduped if coll.find_one({"name": p["name"], "orcid": p.get("orcid")}))
        return inserted, skipped + len(deduped) - inserted

def compute_embeddings(coll, model, batch_size: int = 64, progress_callback=None) -> int:
    """Compute and store embeddings for all profiles. Returns count processed."""
    from core import combine_researcher_text
    
    docs = list(coll.find({}, {"_id": 1, "publications": 1}))
    payload = [(d["_id"], txt) for d in docs if (txt := combine_researcher_text(d))]
    if not payload: return 0
    
    for i in range(0, len(payload), batch_size):
        chunk = payload[i:i+batch_size]
        embs = model.encode([t for _, t in chunk], convert_to_tensor=False, normalize_embeddings=True)
        coll.bulk_write([UpdateOne({"_id": obj_id}, {"$set": {"embedding": emb.tolist(), "text_len": len(txt)}})
                        for (obj_id, txt), emb in zip(chunk, embs)])
        if progress_callback: progress_callback(min(1.0, (i + batch_size) / len(payload)))
    
    return len(payload)

def load_corpus(coll, model) -> Tuple[List[List[float]], List[Dict]]:
    """Load corpus embeddings and metadata. Compute missing embeddings on-the-fly."""
    from core import combine_researcher_text
    
    cursor = coll.find({}, {"name": 1, "institution": 1, "orcid": 1, "publications": 1, "embedding": 1})
    with_emb, to_compute = [], []
    
    for doc in cursor:
        (with_emb if isinstance(doc.get("embedding"), list) and doc["embedding"] else to_compute).append(doc)
    
    def extract_meta(r):
        pub_list = r.get("publications", []) or []
        years = [p.get("year") for p in pub_list if p.get("year")]
        return {"name": r.get("name", "Unknown"), "institution": r.get("institution", ""),
                "orcid": r.get("orcid", ""), "publication_count": len(pub_list),
                "last_publication_year": max(years) if years else None}
    
    corpus_embs = [r["embedding"] for r in with_emb]
    meta = [extract_meta(r) for r in with_emb]
    
    # Compute and save missing embeddings
    if keep := [(r, txt) for r in to_compute if (txt := combine_researcher_text(r))]:
        embs = model.encode([t for _, t in keep], convert_to_tensor=False, normalize_embeddings=True)
        coll.bulk_write([UpdateOne({"_id": r["_id"]}, {"$set": {"embedding": emb.tolist()}})
                        for (r, _), emb in zip(keep, embs)])
        corpus_embs.extend([emb.tolist() for emb in embs])
        meta.extend([extract_meta(r) for r, _ in keep])
    
    return corpus_embs, meta
