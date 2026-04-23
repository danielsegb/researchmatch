"""
ResearchMatch: Intelligent semantic search App for discovering researchers and academic collaborators.
"""
import os
import base64
import streamlit as st
import pandas as pd
import numpy as np
from sentence_transformers import SentenceTransformer
import io

from core import normalize_ws, extract_text, safe_file_upload
from services import derive_top_keywords_hybrid, cluster_upload_docs, discover_profiles_from_upload
from services import build_corpus_from_keywords
from database import get_collection, insert_profiles, compute_embeddings

st.set_page_config(page_title="ResearchMatch", layout="wide", initial_sidebar_state="collapsed")

# ── Config from Streamlit Secrets ─────────────────────────────────────────────
mongo_uri    = st.secrets.get("MONGO_URI", "")
db_name      = st.secrets.get("DB_NAME",   "researchmatch")
coll_name    = st.secrets.get("COLL_NAME", "researchers")
s2_api_key   = st.secrets.get("S2_API_KEY", None)
model_name   = "sentence-transformers/all-MiniLM-L6-v2"

LOGO_SVG = """
<svg width="100" height="100" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M14 2H6C4.9 2 4 2.9 4 4V20C4 21.1 4.9 22 6 22H18C19.1 22 20 21.1 20 20V8L14 2ZM18 20H6V4H13V9H18V20Z" fill="#cccccc"/>
<path d="M10.29 17.71L12 16L13.71 17.71L15.12 16.29L13.41 14.58L15.12 12.87L13.71 11.46L12 13.17L10.29 11.46L8.88 12.87L10.59 14.58L8.88 16.29L10.29 17.71Z" fill="#4A90E2"/>
<path d="M15 13H20V15H15V13Z" fill="#4A90E2"/>
<path d="M15 16H20V18H15V16Z" fill="#4A90E2"/>
<path d="M8 10H12V12H8V10Z" fill="#4A90E2"/>
</svg>
"""
col1, col2 = st.columns([1, 10])
with col1:
    b64_logo = base64.b64encode(LOGO_SVG.encode()).decode()
    st.markdown(f'<img src="data:image/svg+xml;base64,{b64_logo}" width="80">', unsafe_allow_html=True)
with col2:
    st.title("ResearchMatch")
    st.caption("Semantic Discovery App for Academic Collaboration")

st.markdown("""
**ResearchMatch** uses semantic search to discover researchers whose work aligns with your research interests.

**User Guide:**
1. Upload papers or enter research topic or abstract to get started
2. Click Search to find matching researchers
3. Explore profile keywords and publications ranked by relevance
""")
st.markdown("---")

@st.cache_resource(show_spinner="Loading semantic search models...")
def load_model_cached(model_name):
    return SentenceTransformer(model_name)

@st.cache_resource(show_spinner=False)
def load_spacy_cached():
    import spacy
    nlp = spacy.load("en_core_web_sm", disable=["ner"])
    nlp.max_length = 2000000
    return nlp

@st.cache_data(show_spinner=False, max_entries=50)
def process_upload_bytes(file_bytes: bytes, file_name: str) -> str:
    import tempfile
    import os
    ext = ".pdf" if file_name.lower().endswith(".pdf") else ".docx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        from core import extract_text, normalize_ws
        return normalize_ws(extract_text(tmp_path))
    finally:
        try:
            os.remove(tmp_path)
        except:
            pass


if not mongo_uri:
    st.error(
        "⚠️ Database connection is not configured. "
        "Please contact the administrator or set `MONGO_URI` in Streamlit Secrets."
    )
    st.stop()

st.subheader("Match Researchers")
ups = st.file_uploader("Upload PDF/DOCX", type=["pdf", "docx"], accept_multiple_files=True)
kw_text = st.text_area("Keywords / Abstract", "")
col_a, col_b, col_c = st.columns([1, 1, 1])
top_k = col_a.slider("Number of Results", 5, 50, 15)
sort_opt = col_b.selectbox("Sort Results By", ["Match Score (desc)", "Last Publication Year (desc)", "Publication Count (desc)", "Name (A→Z)"])
deep_live_search = col_c.checkbox("Deep Live Search", value=False, help="Dynamically searches real-time data (this may take a while).")
run_match = st.button("Search")

if run_match:
    st.session_state.pop("match_results", None)
    st.session_state.pop("match_themes", None)
    
    raw_texts = []
    if ups:
        for up in ups:
            text = process_upload_bytes(up.getvalue(), up.name)
            if text:
                raw_texts.append(text)
    
    model, nlp, coll = load_model_cached(model_name), load_spacy_cached(), get_collection(mongo_uri, db_name, coll_name)
    
    if coll is None:
        st.error("Database connection failed.")
        st.stop()
        
    with st.spinner("Analysing query and searching database..."):
        if raw_texts and len(raw_texts) >= 2:
            themes = cluster_upload_docs(raw_texts, model, nlp)  # Cluster multiple documents into themes
            if kw_text.strip():
                for th in themes:
                    th["combined_text"] = normalize_ws(kw_text) + " " + th["combined_text"]
        else:
            combined_text = (normalize_ws(kw_text) + " " + " ".join(raw_texts)).strip()  # Single theme from keywords + single doc
            if not combined_text:
                st.warning("Please enter keywords or upload files to start a search.")
                st.stop()
            extracted_kws = derive_top_keywords_hybrid(combined_text, k=3, model=model, nlp=nlp)
            if not extracted_kws and not raw_texts:
                st.warning(
                    "⚠️ No recognisable research terms found in your query. "
                    "Please use real keywords, a research abstract, or upload a paper."
                )
                st.stop()
            themes = [{"theme_label": ", ".join(extracted_kws) or "Primary Theme",
                      "doc_indices": [], "combined_text": combined_text}]
        
        # --- Live Hybrid Retrieval (Dynamic Ingestion) ---
        if deep_live_search:
            # Pick the primary search topic
            search_topic = kw_text.strip() if kw_text.strip() else themes[0]["theme_label"]
            if search_topic and search_topic != "Primary Theme":
                with st.spinner(f"Searching live internet data for '{search_topic}'... (this may take a while)"):
                    try:
                        live_profiles = build_corpus_from_keywords(
                            topic=search_topic, pages=1, per_page=15, doaj_pages=0,
                            progress_callback=None, use_openalex=True, use_semantic_scholar=True,
                            use_arxiv=True, use_pubmed=True, s2_api_key=s2_api_key
                        )
                        if live_profiles:
                            # Tag them logically and inject into the DB dynamically
                            inserted, _ = insert_profiles(coll, live_profiles)
                            if inserted > 0:
                                # Process the embedded math so they organically pop up in Vector Search instantly
                                compute_embeddings(coll, model, nlp, batch_size=32)
                    except Exception as e:
                        st.sidebar.error(f"Live Auto-learn failed: {e}")
        # -------------------------------------------------
        
        all_rows = []
        for th in themes:
            query_embedding = model.encode([th["combined_text"]], convert_to_tensor=False, normalize_embeddings=True)[0].tolist()
            
            try:
                # Perform vector search
                MIN_SCORE_THRESHOLD = 0.40  # filter out truly unrelated profiles
                aggregation_pipeline = [
                    {"$vectorSearch": {
                        "index": "default_vector_index", "queryVector": query_embedding,
                        "path": "embedding", "numCandidates": top_k * 15, "limit": top_k * 3}},  # fetch extra so threshold can trim
                    {"$project": {
                        "_id": 1, "name": 1, "institution": 1, "orcid": 1,
                        "profile_keywords": 1, "score": {"$meta": "vectorSearchScore"}}},
                    {"$match": {"score": {"$gte": MIN_SCORE_THRESHOLD}}},
                    {"$limit": top_k},
                ]
                results = list(coll.aggregate(aggregation_pipeline))
            except Exception as e:
                st.error(f"Vector search failed: {e}")
                st.stop()

            for m in results:
                try:
                    full_doc = coll.find_one({"_id": m.get("_id")}, {
                        "publications.title": 1, "publications.doi": 1,
                        "publications.year": 1, "publications.embedding": 1
                    })
                    pub_list = full_doc.get("publications", []) if full_doc else []
                except Exception:
                    pub_list = []
                
                years = [p.get("year") for p in pub_list if p.get("year") and isinstance(p.get("year"), int)]
                
                all_rows.append({
                    "Theme": th["theme_label"], "Name": m.get("name", "Unknown"),
                    "Institution": m.get("institution", ""), "ORCID": m.get("orcid", ""),
                    "Score": m.get("score", 0), "Publication Count": len(pub_list),
                    "Last Publication Year": max(years) if years else None,
                    "Profile_Keywords": m.get("profile_keywords", []), "Publications": pub_list})
        
        if all_rows:
            st.session_state["match_results"] = pd.DataFrame(all_rows)
            st.session_state["match_themes"] = themes
            st.success("Search complete. See results below.")
        else:
            st.warning("No matches found for your query.")

if "match_results" in st.session_state:
    df = st.session_state["match_results"].copy()
    themes = st.session_state.get("match_themes", [])
    theme_labels = sorted([th["theme_label"] for th in themes])
    choice = st.selectbox("Filter by Theme", ["All themes"] + theme_labels)
    filtered = df if choice == "All themes" else df[df["Theme"] == choice]
    
    sort_map = {"Match Score (desc)": ("Score", False), "Last Publication Year (desc)": ("Last Publication Year", False),
                "Publication Count (desc)": ("Publication Count", False), "Name (A→Z)": ("Name", True)}
    sort_col, sort_asc = sort_map[sort_opt]
    filtered["Last Publication Year"] = pd.to_numeric(filtered["Last Publication Year"], errors='coerce')
    filtered = filtered.sort_values(sort_col, ascending=sort_asc, na_position="last").reset_index(drop=True)
    
    csv_df = filtered.drop(columns=["Score", "Publications", "Profile_Keywords"])
    csv_output = io.StringIO()
    csv_df.to_csv(csv_output, index=False)
    
    st.download_button("Download Results as CSV", data=csv_output.getvalue(),
                      file_name="researchmatch_results.csv", mime="text/csv")

    model = load_model_cached(model_name)

    for i, row in enumerate(filtered.itertuples()):
        st.markdown("---")
        col1, col2 = st.columns([4, 1])
        with col1:
            st.subheader(f"{i + 1}. {row.Name}")
            st.markdown(f"**Institution:** {row.Institution or 'N/A'}")
            if row.ORCID:
                 st.markdown(f"**ORCID:** [{row.ORCID}](https://orcid.org/{row.ORCID})")
            if row.Theme and len(theme_labels) > 1:
                st.caption(f"Theme: {row.Theme}")
        with col2:
            st.metric("Match Score", f"{row.Score:.2%}")

        with st.expander("Match Explanation (Click to see details)"):
            
            theme = next((th for th in themes if th["theme_label"] == row.Theme), None)
            if not theme:
                continue

            query_emb = np.array(model.encode([theme["combined_text"]], normalize_embeddings=True)[0])
            
            st.markdown("**Researcher's Profile Keywords:**")
            profile_keywords = getattr(row, 'Profile_Keywords', [])
            if profile_keywords:
                st.write(f"_{', '.join(profile_keywords)}_")
            else:
                st.write("_No keywords computed for this profile._")

            researcher_pubs = row.Publications if hasattr(row, 'Publications') else []
            if not researcher_pubs:
                st.write("**Publications:** _No publications found._")
                continue
            
            pub_count = len(researcher_pubs)
            st.markdown(f"**Publications ({pub_count} total, sorted by relevance to query):**")

            pubs_with_embeddings = []
            for pub in researcher_pubs:
                if pub.get("embedding"):
                    pubs_with_embeddings.append(pub)

            if not pubs_with_embeddings:
                 researcher_pubs.sort(key=lambda x: x.get('year') or 0, reverse=True)
                 for pub in researcher_pubs:
                     doi_text = f" (DOI: {pub.get('doi')})" if pub.get('doi') else ""
                     st.markdown(f"– {pub.get('title', 'No Title')} ({pub.get('year', 'N/A')}){doi_text}")
                 continue

            pub_embeddings = np.array([p["embedding"] for p in pubs_with_embeddings])
            sims = np.dot(pub_embeddings, query_emb.T).ravel()
            
            for i, pub in enumerate(pubs_with_embeddings):
                 pub['similarity_score'] = sims[i]

            pubs_with_embeddings.sort(key=lambda x: x['similarity_score'], reverse=True)

            for pub in pubs_with_embeddings:
                doi_text = f" (DOI: {pub.get('doi')})" if pub.get('doi') else ""
                st.markdown(f"– {pub.get('title', 'No Title')} ({pub.get('year', 'N/A')}){doi_text}")

else:
    st.info("Enter your request and click **Search** to discover researchers.")

st.markdown("<br><br><br>", unsafe_allow_html=True)
st.markdown(
    "<div style='text-align: center; color: gray; font-size: 0.8em;'>"
    "&copy; 2026 <a href='https://danielse.com' target='_blank' style='text-decoration: none; color: inherit;'>"
    "DANIELSE</a>. All rights reserved."
    "</div>", 
    unsafe_allow_html=True
)
