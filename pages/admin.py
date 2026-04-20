"""
Admin Page — ResearchMatch
Password-protected corpus management: build corpus and precompute embeddings.
Accessible at /admin in Streamlit multi-page mode.
"""
import os
import streamlit as st
from sentence_transformers import SentenceTransformer

from core import normalize_ws, extract_text, safe_file_upload, MAX_UPLOAD_MB
from services import build_corpus_from_keywords, discover_profiles_from_upload
from database import get_collection, insert_profiles, compute_embeddings

st.set_page_config(page_title="ResearchMatch — Admin", layout="wide")

# ── Password gate ─────────────────────────────────────────────────────────────
ADMIN_PASS = st.secrets.get("ADMIN_PASS", "")

if "admin_authenticated" not in st.session_state:
    st.session_state["admin_authenticated"] = False

if not st.session_state["admin_authenticated"]:
    st.title("🔐 Admin Login")
    st.info("This page is restricted to administrators only. Return to the [main app](/) to search researchers.")
    pwd = st.text_input("Admin password", type="password", key="admin_pwd_input")
    if st.button("Login", type="primary"):
        if pwd and ADMIN_PASS and pwd == ADMIN_PASS:
            st.session_state["admin_authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password. Access denied.")
    st.stop()

# ── Authenticated ─────────────────────────────────────────────────────────────
st.title("⚙️ ResearchMatch — Admin Panel")
st.caption("Manage the researcher database: build corpus and precompute embeddings.")

if st.button("🚪 Logout", key="logout_btn"):
    st.session_state["admin_authenticated"] = False
    st.rerun()

st.markdown("---")

# ── Secrets / config ──────────────────────────────────────────────────────────
mongo_uri   = st.secrets.get("MONGO_URI", "")
ncbi_api_key = st.secrets.get("NCBI_API_KEY", None)
model_name  = "sentence-transformers/all-MiniLM-L6-v2"

if not mongo_uri:
    st.error("⚠️ `MONGO_URI` is not set in Streamlit Secrets. Please configure it and redeploy.")
    st.stop()


@st.cache_resource(show_spinner="Loading semantic search model…")
def load_model_cached(name: str):
    return SentenceTransformer(name)


@st.cache_resource(show_spinner=False)
def load_spacy_cached():
    import spacy
    nlp = spacy.load("en_core_web_sm", disable=["ner"])
    nlp.max_length = 2_000_000
    return nlp


# ── Database config ───────────────────────────────────────────────────────────
col_db1, col_db2 = st.columns(2)
db_name   = col_db1.text_input("Database Name", "researchmatch")
coll_name = col_db2.text_input("Collection Name", "researchers")

# ══════════════════════════════════════════════════════════════════════════════
st.subheader("📚 Build Corpus")
st.markdown(
    "Query academic APIs to populate the researcher database. "
    "All enabled sources run **in parallel** for speed."
)

topic = st.text_input("Research Topic / Keywords", key="admin_topic",
                      placeholder="e.g. deep learning, climate change, CRISPR gene editing")

col1, col2, col3 = st.columns(3)
pages      = col1.number_input("Pages per API", 1, 20, 2)
per_page   = col2.number_input("Results per Page", 10, 200, 25)
doaj_pages = col3.number_input("DOAJ Pages (0 = skip)", 0, 5, 0)

st.markdown("##### 🔌 Enable Data Sources")
src1, src2, src3, src4 = st.columns(4)
use_openalex = src1.checkbox("OpenAlex",         value=True)
use_ss       = src2.checkbox("Semantic Scholar", value=True)
use_arxiv    = src3.checkbox("arXiv",            value=True)
use_pubmed   = src4.checkbox("PubMed",           value=True)

col_f1, col_f2 = st.columns(2)
upload_pages   = col_f1.number_input("Pages per Upload Doc", 1, 5, 1)
uploads_folder = col_f2.text_input("Local Uploads Folder (optional)", "uploads")

run_build = st.button("▶️ Build Corpus", key="run_build", type="primary")

if run_build:
    if not topic and not os.path.isdir(uploads_folder):
        st.error("Please enter a topic or point to a valid uploads folder.")
    else:
        model = load_model_cached(model_name)
        nlp   = load_spacy_cached()
        coll  = get_collection(mongo_uri, db_name, coll_name)

        if coll is not None:
            all_profiles: list = []
            source_counts: dict = {}

            if topic:
                with st.spinner("Querying academic APIs in parallel…"):
                    progress_ph = st.progress(0.0, text="Querying OpenAlex…")
                    profiles = build_corpus_from_keywords(
                        topic, pages, per_page, doaj_pages, progress_ph,
                        use_openalex=use_openalex,
                        use_semantic_scholar=use_ss,
                        use_arxiv=use_arxiv,
                        use_pubmed=use_pubmed,
                        ncbi_api_key=ncbi_api_key,
                    )
                    progress_ph.progress(1.0)
                    all_profiles.extend(profiles)

                    # Tally publications per source
                    for p in profiles:
                        for pub in p.get("publications", []):
                            src = pub.get("source", "Unknown")
                            source_counts[src] = source_counts.get(src, 0) + 1

            if os.path.isdir(uploads_folder):
                st.text(f"Scanning '{uploads_folder}'…")
                upload_count = 0
                for fname in os.listdir(uploads_folder):
                    fpath = os.path.join(uploads_folder, fname)
                    if not os.path.isfile(fpath):
                        continue
                    if text := extract_text(fpath):
                        up_profiles, _ = discover_profiles_from_upload(
                            text, upload_pages, per_page, fname, model, nlp
                        )
                        all_profiles.extend(up_profiles)
                        upload_count += len(up_profiles)
                if upload_count:
                    source_counts["Uploads"] = upload_count

            inserted, skipped = insert_profiles(coll, all_profiles)
            st.success(
                f"✅ Inserted **{inserted}** new profiles | Skipped (duplicates): **{skipped}**"
            )

            if source_counts:
                metric_cols = st.columns(len(source_counts))
                for col, (src, count) in zip(metric_cols, source_counts.items()):
                    col.metric(f"{src} (pubs)", count)

# ══════════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("🧠 Precompute Embeddings")
st.markdown(
    "Run this **after** building the corpus to generate AI embeddings for all "
    "researcher profiles and their publications. This enables fast semantic search."
)

run_precompute = st.button("▶️ Compute Embeddings", key="run_precompute", type="primary")

if run_precompute:
    model = load_model_cached(model_name)
    nlp   = load_spacy_cached()
    coll  = get_collection(mongo_uri, db_name, coll_name)
    if coll is not None:
        progress_bar = st.progress(0.0)
        status_text  = st.empty()

        def update_progress(p: float):
            progress_bar.progress(min(p, 1.0))
            status_text.info(f"Computing embeddings… {int(p * 100)}%")

        count = compute_embeddings(coll, model, nlp, progress_callback=update_progress)
        progress_bar.progress(1.0)
        status_text.success(f"✅ Processed **{count:,}** profiles.")
