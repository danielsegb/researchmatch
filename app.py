"""Researchmatch App built with Streamlit for graphical interface.
This application helps users find relevant researchers by analysing text from keywords 
or uploaded documents. It classifies papers or keywords into themes and retrieves matching profiles 
from the database of preprocessed research data and metadata."""
import os
import streamlit as st
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer

from core import normalize_ws, extract_text, safe_file_upload
from services import derive_top_keywords_hybrid, cluster_upload_docs, discover_profiles_from_upload
from services import build_corpus_from_keywords
from database import get_collection, insert_profiles, compute_embeddings, load_corpus

st.set_page_config(page_title="Researchmatch", layout="wide", initial_sidebar_state="collapsed")

# Model cache
@st.cache_resource
def load_model_cached(model_name):
    return SentenceTransformer(model_name)

@st.cache_resource
def load_spacy_cached():
    import spacy
    nlp = spacy.load("en_core_web_sm", disable=["ner"])
    nlp.max_length = 2000000
    return nlp

# Sidebar
st.title("Researchmatch APP")

with st.sidebar:
    st.header("⚙️ Settings")
    mongo_uri = st.text_input("MongoDB URI", "mongodb://localhost:27017")
    db_name, coll_name = st.text_input("Database", "researchmatch"), st.text_input("Collection", "researchers")
    uploads_folder = st.text_input("Uploads folder", "uploads")
    model_name = st.text_input("Embedding model", "sentence-transformers/all-MiniLM-L6-v2")
    
    st.markdown("---")
    with st.expander("Build Corpus", expanded=False):
        topic = st.text_input("Topic", key="topic")
        col1, col2 = st.columns(2)
        with col1:
            pages, doaj_pages = st.number_input("OpenAlex pages", 1, 20, 2, key="pages"), st.number_input("DOAJ pages", 0, 5, 0, key="doaj")
        with col2:
            per_page, upload_pages = st.number_input("Per page", 10, 200, 25, key="per_page"), st.number_input("Upload pages", 1, 5, 1, key="up_pages")
        
        run_build = st.button("Run Build", key="run_build")
    
    st.markdown("---")
    with st.expander("Precompute", expanded=False):
        run_precompute = st.button("Compute Embeddings", key="run_precompute")

# Admin: Build corpus
if run_build:
    model, nlp = load_model_cached(model_name), load_spacy_cached()
    coll = get_collection(mongo_uri, db_name, coll_name)
    all_profiles, stats = [], {"openalex": 0, "doaj": 0, "uploads": 0}
    
    # Keywords
    if topic:
        profiles = build_corpus_from_keywords(topic, pages, per_page, doaj_pages, 
                                             st.sidebar.progress(0.0, text="OpenAlex..."))
        all_profiles.extend(profiles)
        stats["openalex"] = len(profiles)
    
    # Uploads
    if os.path.exists(uploads_folder):
        for fname in os.listdir(uploads_folder):
            if not os.path.isfile(fpath := os.path.join(uploads_folder, fname)): continue
            if text := extract_text(fpath):
                profiles, _ = discover_profiles_from_upload(text, upload_pages, per_page, fname, model, nlp)
                all_profiles.extend(profiles)
                stats["uploads"] += len(profiles)
    
    # Insert
    inserted, skipped = insert_profiles(coll, all_profiles)
    st.sidebar.success(f"Inserted: {inserted}, Skipped: {skipped}")
    for k, v in stats.items(): st.sidebar.metric(k.title(), v)

# Admin: Precompute
if run_precompute:
    count = compute_embeddings(get_collection(mongo_uri, db_name, coll_name), load_model_cached(model_name), 
                               progress_callback=lambda x: st.sidebar.progress(x))
    st.sidebar.success(f"Computed {count} embeddings")

# Main: Match
st.subheader("Match Researchers")
st.caption("Enter keywords or upload files to get started.")

kw_text = st.text_area("Keywords / abstract", "")
ups = st.file_uploader("Upload PDF/DOCX", type=["pdf", "docx"], accept_multiple_files=True)

col_a, col_b = st.columns(2)
top_k = col_a.slider("Top matches per theme", 5, 50, 15)
sort_opt = col_b.selectbox("Sort", ["Last Publication Year (desc)", "Publication Count (desc)", "Name (A→Z)"])
run_match = st.button("Search ")

# Matching
if run_match:
    st.session_state.pop("match_results", None)
    st.session_state.pop("match_themes", None)
    
    # Extract uploads
    raw_texts = []
    if ups:
        for up in ups:
            if tmp_path := safe_file_upload(up):
                raw_texts.append(normalize_ws(extract_text(tmp_path)))
                try: os.remove(tmp_path)
                except: pass
    
    # Load corpus
    with st.spinner("⚙️ Loading models and corpus..."):
        model, nlp = load_model_cached(model_name), load_spacy_cached()
        coll = get_collection(mongo_uri, db_name, coll_name)
        corpus_embs, meta = load_corpus(coll, model)
    
    if not corpus_embs:
        st.warning("No corpus available")
    else:
        with st.spinner("Building themes and matching researchers..."):
            # Build themes
            if raw_texts and len(raw_texts) >= 2:
                themes = cluster_upload_docs(raw_texts, model, nlp)
                if kw_text.strip():
                    for th in themes:
                        th["combined_text"] = normalize_ws(kw_text) + " " + th["combined_text"]
            else:
                if not (combined := (normalize_ws(kw_text) + " " + " ".join(raw_texts)).strip()):
                    st.warning("Enter keywords or upload files")
                    st.stop()
                themes = [{"theme_label": ", ".join(derive_top_keywords_hybrid(combined, k=3, model=model, nlp=nlp)) or "Theme 1",
                          "doc_indices": [], "combined_text": combined}]
            
            # Match (Fast mode)
            corpus = np.array(corpus_embs)
            all_rows = []
            for th in themes:
                sims = np.dot(corpus, model.encode([th["combined_text"]], convert_to_tensor=False, normalize_embeddings=True)[0])
                for idx in np.argsort(-sims)[:top_k]:
                    m = meta[idx]
                    all_rows.append({"Theme": th["theme_label"], "Name": m["name"], 
                                    "Institution": m["institution"], "ORCID": m["orcid"],
                                    "Publication Count": m["publication_count"], 
                                    "Last Publication Year": m["last_publication_year"]})
        
        if all_rows:
            df = pd.DataFrame(all_rows)
            st.session_state["match_results"] = df
            st.session_state["match_themes"] = list(df["Theme"].unique())
            st.success("Matching complete")
        else:
            st.warning("No matches found")

# Render results
if "match_results" in st.session_state:
    df, themes = st.session_state["match_results"].copy(), st.session_state.get("match_themes", [])
    choice = st.selectbox("Theme", ["All themes"] + sorted(themes))
    filtered = df if choice == "All themes" else df[df["Theme"] == choice]
    
    # Sort
    sort_map = {
        "Last Publication Year (desc)": (["Theme", "Last Publication Year", "Publication Count", "Name"], [True, False, False, True]),
        "Publication Count (desc)": (["Theme", "Publication Count", "Last Publication Year", "Name"], [True, False, False, True]),
        "Name (A→Z)": (["Theme", "Name"], [True, True])
    }
    cols, asc = sort_map[sort_opt]
    filtered = filtered.sort_values(cols, ascending=asc, na_position="last")
    
    show_df = filtered.drop(columns=["Theme"], errors="ignore").reset_index(drop=True)
    show_df.index = show_df.index + 1  # Start serial numbers from 1
    
    st.dataframe(show_df, use_container_width=True)
    st.download_button("Download CSV", show_df.to_csv(index=True).encode("utf-8"), "matches.csv", "text/csv")
else:
    st.info("Set query and click **Search to find matches**")
