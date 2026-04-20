# ResearchMatch

An intelligent application that uses Natural Language Processing (NLP) and a cloud-based vector database to discover and match researchers based on the semantic content of their work.

## Overview

Finding the right academic collaborators goes beyond simple keyword matching. **ResearchMatch** leverages transformer-based language models to understand the deep meaning of research topics. Utilizing a high-speed vector search engine (MongoDB Atlas Vector Search), it matches you with researchers with genuinely similar expertise. 

The system queries multiple prestigious academic databases in parallel, pre-computes semantic embeddings for both profiles and individual publications, and provides **Match Explanations**—clear justifications for each match by displaying the researcher's keywords and a sorted list of their publications (ranked by relevance).

## ✨ Features

- **Multi-Source Parallel Ingestion**: Simultaneously gathers and synthesizes data directly from five major academic APIS: **OpenAlex, Semantic Scholar, arXiv, PubMed (NCBI), and DOAJ**.
- **Cloud-Based Vector Search**: Delivers instant semantic matching using MongoDB Atlas Vector Search.
- **Instant Match Explanation**: Justifies each recommendation by showing profile keywords and a relevance-sorted list of all publications (including DOIs).
- **Secure Admin Panel**: A dedicated, password-gated Admin Panel `/admin` keeps database-building and embedding controls isolated from public users. 
- **Streamlit Community Cloud Ready**: Completely refactored for cloud safety, using Python's `tempfile` architecture for robust file processing, size-guarded uploads, and hidden SECRETS management.
- **Smart Document Upload**: Discovers new, relevant researchers by analyzing the content of uploaded PDFs or Word documents.

## 🏗️ System Architecture

* **Frontend**: Streamlit (Multipage UI)
* **NLP & Embeddings**: `sentence-transformers`, `spacy`
* **Database & Search**: MongoDB Atlas (Vector Search required)
* **Data Sources**: OpenAlex, Semantic Scholar, arXiv, PubMed, DOAJ, CrossRef

## ⚙️ Prerequisites & Setup

1. **Python 3.9+**
2. A free **MongoDB Atlas** account (M0 Sandbox is fine).
3. **API Keys (Optional but recommended)**: An NCBI API key placed in your configuration allows for higher rate limits.

### Configuration
Never commit your credentials. Create a `.streamlit/secrets.toml` file in the root of the project with the following:

```toml
MONGO_URI = "mongodb+srv://<USER>:<PASS>@cluster0..."
ADMIN_PASS = "your_secure_password"
CONTACT_EMAIL = "your@email.com" # For API Polite Pools
NCBI_API_KEY = "your_ncbi_key"   # Optional
```

### MongoDB Setup
You must create a Vector Search Index in your MongoDB Atlas Dashboard for the application to perform matching.
Go to Atlas Search → Create Search Index → **Atlas Vector Search** → JSON Editor and paste:

```json
{
  "fields": [
    {
      "type": "vector",
      "path": "embedding",
      "numDimensions": 384,
      "similarity": "cosine"
    }
  ]
}
```

## 🚀 Usage

Run the application locally:
```bash
python -m streamlit run app.py
```

* **Public Interface (`http://localhost:8501`)**: The clean GUI is dedicated entirely to searching. Enter keywords or upload documents and hit "Search". Expand matched researchers to see DOIs and relevant publications.
* **Admin Interface (`http://localhost:8501/admin`)**: A hidden password-gated page exclusively for the app administrators to fetch new publications (toggling which APIs are enabled) and compute new NLP embeddings.

## 📂 Project Structure

* `app.py` - Main Streamlit application and Search interface
* `pages/admin.py` - Password-protected Admin Panel for DB management
* `core.py` - Robust temporary file handling, rate limiting, and core API request logic
* `services.py` - Multi-threaded NLP tasks, keywords, clustering, and parallel fetching
* `database.py` - MongoDB Atlas connection and embedding computations
