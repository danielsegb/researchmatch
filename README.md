# Researchmatch - Identification of Active Researchers in Custom Academic Themes using Bibliometrics and NLP

An intelligent application that uses Natural Language Processing (NLP) and a cloud-based vector database to discover and match researchers based on the semantic content of their work.

## Overview

Researchmatch addresses the challenge of finding relevant academic collaborators by moving beyond simple keyword matching. It leverages transformer-based language models to understand the deep meaning of research topics and uses a high-speed vector search engine (MongoDB Atlas Vector Search) to find researchers with genuinely similar expertise. A key feature is Match Explanation, which provides clear justifications for each match by displaying the researcher's profile keywords and a full list of their publications, sorted by relevance to the query. The system pre-computes embeddings for both profiles and individual publications, ensuring instant search results and explainability.

## Features

Cloud-Based Vector Search: Delivers instant and scalable semantic matching using MongoDB Atlas Vector Search.

Instant Match Explanation: Justifies each recommendation by showing profile keywords and a relevance-sorted list of all publications (including DOIs), leveraging pre-computed embeddings for speed.

Multi-Source Corpus Building: Gathers and synthesizes data from academic databases like OpenAlex and CrossRef, as well as from user-provided seed documents (PDF/DOCX).

Smart Document Upload: Automatically discovers new, relevant researchers by analyzing the content of uploaded files to generate new search queries.

Thematic Clustering: Groups multiple query documents into distinct conceptual themes for organized searching.

Robust Data Ingestion: Intelligently attempts to download and extract text from full-text PDFs using browser headers, gracefully handling paywalls and inaccessible links.

Clean UI: User-friendly interface built with Streamlit, including ORCID links and CSV export.

## System Architecture

Frontend: Streamlit

NLP & Embeddings: sentence-transformers, spaCy

Database & Search Core: MongoDB Atlas with Atlas Vector Search

Data Sources: OpenAlex, CrossRef APIs

### Prerequisites

Python 3.9+

A free MongoDB Atlas account

An NVIDIA GPU with updated drivers (Recommended for speed)



## Usage

Run the application using the terminal with "streamlit run app.py" to access it on web browser. Use the sidebar to build your corpus or match researchers by entering keywords or uploading documents. After Corpus and vector search setup, the main section of the app can be used. Enter keywords, paste an abstract, or upload documents. Click "Search" for instant results. Click the expander on any result to see the detailed explanation, including ORCID, profile keywords, and the full list of publications sorted by relevance (with DOIs). Use the "Download CSV" button to export results.

## Project Structure

- app.py - Main Streamlit application
- core.py - Text processing, file I/O, and API calls
- services.py - Embeddings, keywords, clustering, and matching
- database.py - MongoDB operations
