"""
MongoDB Atlas operations: connections, profile insertion, and embedding computation.
"""
import logging
from typing import List, Dict, Tuple
from pymongo import MongoClient, UpdateOne
import streamlit as st
from services import derive_top_keywords_hybrid

logger = logging.getLogger(__name__)

@st.cache_resource
def get_mongo_client_singleton(uri):
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=10000)
        client.admin.command('ping')
        return client
    except Exception as e:
        st.error(f"MongoDB connection failed: {e}")
        return None

@st.cache_resource
def get_collection_with_indexes(uri, db, coll):
    client = get_mongo_client_singleton(uri)
    if client is None:
        return None
    collection = client[db][coll]
    try:
        collection.create_index([("name", 1), ("orcid", 1)], unique=True)
    except Exception as e:
        logger.warning(f"Index creation failed: {e}")
    return collection

get_collection = get_collection_with_indexes
profile_key = lambda p: (p.get("name", "").strip().lower(), (p.get("orcid") or "").strip().lower())

def insert_profiles(coll, profiles: List[Dict]) -> Tuple[int, int]:
    if not profiles or coll is None:
        return 0, 0
    
    deduped, skipped, batch_keys = [], 0, set()
    for p in profiles:
        if (k := profile_key(p)) in batch_keys:  # Deduplicate by name+ORCID before MongoDB unique constraint
            skipped += 1
        else:
            batch_keys.add(k)
            if "publications" not in p:
                p["publications"] = []
            deduped.append(p)
    
    if not deduped:
        return 0, skipped
    
    try:
        result = coll.insert_many(deduped, ordered=False)
        return len(result.inserted_ids), skipped
    except Exception as e:
        logger.warning(f"Bulk insertion error: {e}")
        if hasattr(e, 'details') and 'nInserted' in e.details:
            return e.details['nInserted'], skipped + (len(deduped) - e.details['nInserted'])
        return 0, skipped + len(deduped)

def compute_embeddings(coll, model, nlp, batch_size: int = 32, progress_callback=None) -> int:
    from core import combine_researcher_text
    
    if coll is None:
        return 0
    
    query = {"$or": [
        {"embedding": {"$exists": False}},
        {"profile_keywords": {"$exists": False}},
        {"publications.embedding": {"$exists": False}}
    ]}  # Process only profiles/publications missing embeddings
    
    total_docs_to_process = coll.count_documents(query)
    if total_docs_to_process == 0:
        logger.info("No documents require embedding computation.")
        return 0

    total_processed, chunk_size = 0, 200
    logger.info(f"Starting embedding computation for {total_docs_to_process} profiles...")

    while True:
        cursor = coll.find(query, {"_id": 1, "publications": 1}).limit(chunk_size)
        docs_in_chunk = list(cursor)
        
        if not docs_in_chunk:
            break

        updates = []
        for doc in docs_in_chunk:
            profile_id = doc["_id"]
            publications = doc.get("publications", [])
            
            profile_text = combine_researcher_text(doc)
            profile_embedding = None
            profile_keywords = []
            if profile_text:
                try:
                    profile_embedding = model.encode([profile_text], convert_to_tensor=False, normalize_embeddings=True)[0].tolist()
                    profile_keywords = derive_top_keywords_hybrid(profile_text, k=10, model=model, nlp=nlp)
                except Exception as e:
                    logger.error(f"Error processing profile {profile_id}: {e}")

            pub_texts, valid_pub_indices = [], []
            for i, p in enumerate(publications):
                if p.get("embedding"):
                    continue
                txt = f"{p.get('title', '')} {p.get('abstract', '')}".strip()
                if txt:
                    pub_texts.append(txt)
                    valid_pub_indices.append(i)
            
            pub_embeddings = {}
            if valid_pub_indices and pub_texts:
                try:
                    embeddings_list = model.encode(pub_texts, batch_size=batch_size,
                                                   convert_to_tensor=False, normalize_embeddings=True)
                    for list_idx, original_pub_idx in enumerate(valid_pub_indices):
                        pub_embeddings[original_pub_idx] = embeddings_list[list_idx].tolist()
                except Exception as e:
                    logger.error(f"Error encoding publications for profile {profile_id}: {e}")

            set_update = {}
            if profile_embedding is not None:
                set_update["embedding"] = profile_embedding
            if profile_keywords:
                set_update["profile_keywords"] = profile_keywords
            if profile_text:
                 set_update["text_len"] = len(profile_text)

            for idx, embedding in pub_embeddings.items():
                set_update[f"publications.{idx}.embedding"] = embedding
            
            if set_update:
                updates.append(UpdateOne({"_id": profile_id}, {"$set": set_update}, upsert=False))
        
        if updates:
            try:
                coll.bulk_write(updates, ordered=False)
            except Exception as e:
                logger.error(f"Bulk write error: {e}")
                try:
                    st.error(f"Database write failed: {str(e)[:200]}")
                except:
                    pass
        
        total_processed += len(docs_in_chunk)
        if progress_callback:
            progress_callback(min(1.0, total_processed / total_docs_to_process))
            
        if total_processed >= total_docs_to_process:
             break

    logger.info("Embedding computation complete.")
    return total_processed
