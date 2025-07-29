# Researchmatch - Academic Researcher Matching System

An intelligent research collaboration platform that uses advanced NLP and machine learning to match researchers based on their publications, expertise, and research interests.

## Overview

Researchmatch solves the challenge of finding relevant researchers and collaborators in academia by analyzing publication data from multiple academic sources, using semantic embeddings to understand research content, and matching researchers based on semantic similarity.

## Features

- Multi-Source Corpus Building from OpenAlex and DOAJ
- Smart Document Upload with automatic researcher discovery
- Theme Clustering for multiple documents
- Semantic Matching using transformer-based embeddings
- Real-time Results with precomputed embeddings
- Export Capabilities to CSV

## Installation

### Prerequisites
- Python 3.8 or higher
- MongoDB 4.0 or higher

### Steps

1. Clone the repository
2. Install dependencies
3. Download spaCy model
4. Start MongoDB
5. Run the application

## Project Structure

- app.py - Main Streamlit application
- core.py - Text processing, file I/O, and API calls
- services.py - Embeddings, keywords, clustering, and matching
- database.py - MongoDB operations
- uploads/ - Folder for uploaded documents
- tmp/ - Temporary file storage

## Technologies Used

- Streamlit for web interface
- Sentence Transformers for semantic embeddings
- spaCy for NLP processing
- MongoDB for data storage
- scikit-learn for clustering
- OpenAlex and DOAJ APIs for research data

## Usage

Run the application and access it in your browser. Use the sidebar to build your corpus or match researchers by entering keywords or uploading documents.

## License

Academic Project - MSc Research
