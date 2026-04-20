# Pseudocode Documentation

This document provides a pseudocode for the main algorithms in ResearchMatch, reflecting the final cloud-native architecture with multi-source parallel API ingestion, safe `tempfile` processing, pre-computed publication embeddings, and search result caching.

## 1. Multi-Source Parallel Corpus Ingestion

This algorithm speeds up database building by querying multiple academic APIs simultaneously (OpenAlex, Semantic Scholar, arXiv, PubMed) and mapping their distinct schemas into a unified Profile structure.

```text
FUNCTION build_corpus_from_keywords(topic, API_flags):
    INPUT: A search topic (e.g. 'machine learning').
           Toggles indicating which APIs to query (OpenAlex, Semantic Scholar, etc.).
    OUTPUT: A merged, standardized list of researcher profiles.
    
    STEP 1: Define API adapter functions for each target source.
        FUNCTION fetch_openalex():
            - Query OpenAlex works endpoint.
            - Enrich matching DOIs with CrossRef data.
            - Transform into standardized dict.
            - Return profiles.
            
        FUNCTION fetch_semantic_scholar():
            - Query Semantic Scholar Graph API.
            - Transform into standardized dict.
            - Return profiles.
            
        (Repeat adapter logic for arXiv and PubMed depending on flags)

    STEP 2: Initialize a parallel ThreadPoolExecutor.
        pool = ThreadPoolExecutor(max_workers=4)
        active_fetchers = Set of enabled adapter functions based on API_flags
        
    STEP 3: Execute in parallel.
        futures = map(pool.submit, active_fetchers)
        
    STEP 4: Await completion and merge profiles into a global list.
        all_profiles = []
        FOR future IN futures (as completed):
            all_profiles.extend(future.result())
            
    STEP 5: Add DOAJ open-access records (synchronously if requested).
        IF doaj_enabled:
            all_profiles.extend(scrape_doaj(topic))
            
    RETURN all_profiles
```

## 2. Cloud-Safe Document Processing Algorithm

This protects the Streamlit Community Cloud server from crashing during concurrent file uploads.

```text
FUNCTION safe_file_upload(uploaded_file):
    INPUT: A binary file stream uploaded via Streamlit.
    OUTPUT: A safe, uniquely named temporary file path, securely handled.
    
    STEP 1: Check file size against cloud limits.
        IF file.size > 50MB:
            Reject upload to prevent Out-Of-Memory (OOM) errors.
            
    STEP 2: Generate a secure, randomized temporary file path.
        temp_path = create_named_temp_file(suffix=file_extension, delete=False)
        
    STEP 3: Write chunks to disk securely.
        stream chunks to temp_path
        
    STEP 4: Return path to the text extraction pipeline.
        RETURN temp_path
```

## 3. Researcher Matching Algorithm (using Vector Search)

This algorithm runs when a user performs a search. It leverages MongoDB Atlas Vector Search for instant semantic matching.

```text
FUNCTION match_researchers_with_vector_search(query_text, top_k):
    INPUT: A string of text representing the user's query.
           The number of top matches to return.
    OUTPUT: A list of the top_k most similar researcher profiles.
    
    STEP 1: Encode the user's query into a vector embedding.
        query_embedding = model.encode(query_text)
        
    STEP 2: Construct a MongoDB Aggregation Pipeline using $vectorSearch.
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "default_vector_index", 
                    "queryVector": query_embedding,
                    "path": "embedding",            
                    "limit": top_k,
                    "numCandidates": top_k * 15     // Search more to improve accuracy
                }
            },
            {
                "$project": { 
                    "name": 1, 
                    "institution": 1,
                    "orcid": 1, 
                    "publications": 1, 
                    "profile_keywords": 1,
                    "score": { "$meta": "vectorSearchScore" } 
                }
            }
        ]
        
    STEP 3: Execute the pipeline on the database.
        results = database_collection.aggregate(pipeline)
        
    RETURN list(results)
```

## 4. Document Clustering Algorithm

This algorithm is used to group multiple user-uploaded documents into themes before matching them semantically against the database.

```text
FUNCTION cluster_documents(document_texts, model):
    INPUT: A list of text content from uploaded documents.
           The sentence-transformer model.
    OUTPUT: A list of theme objects, each containing a label and combined text.
    
    STEP 1: Encode all documents into a matrix of embeddings.
        embeddings = model.encode(document_texts)
        
    STEP 2: Find the optimal number of clusters (k) using the silhouette score.
        best_k = determine_optimal_k_via_silhouette(embeddings)
                
    STEP 3: Perform clustering with the optimal k.
        IF best_k == 1:
            RETURN a single theme containing all documents.
        ELSE:
            labels = AgglomerativeClustering(n_clusters=best_k).fit_predict(embeddings)
            
    STEP 4: Group documents by their assigned cluster label.
        clusters = group_documents_by_label(document_texts, labels)
        
    STEP 5: For each cluster, combine its text and generate a theme label from keywords.
        themes = []
        FOR each cluster in clusters:
            combined_text = concatenate(cluster.documents)
            keywords = extract_keywords(combined_text, k=3)
            themes.append({ theme_label: keywords, combined_text: combined_text })
            
    RETURN themes
```

## 5. Embedding Computation Algorithm (Precomputation)

This is the long-running administrative task used to process the corpus in the Admin UI.

```text
FUNCTION compute_embeddings(collection, model, nlp):
    INPUT: The MongoDB collection, embedding model, and NLP model.
    OUTPUT: The total count of processed profiles.
    
    STEP 1: Define the query to find documents needing processing.
        query = find documents where profile embedding OR profile keywords OR any publication embedding is missing.
    
    STEP 2: Process documents in independent chunks (e.g., 200).
        WHILE more documents match the query:
            
            STEP 2a: Fetch a new chunk of documents using .limit().
                chunk_docs = collection.find(query).limit(chunk_size)
            
            STEP 2b: Prepare update operations for this chunk.
                updates = []
                FOR each doc in chunk_docs:
                    - Combine profile texts.
                    - IF profile text exists AND needs embedding/keywords:
                        - Compute profile embedding.
                        - Compute profile keywords.
                    
                    - Prepare list of publication texts needing embeddings.
                    - IF any publication needs embedding:
                        - Compute publication embeddings in a batch.
                    
                    - Construct the $set operation including profile embedding, 
                      keywords, and individual publication embeddings.
                    - Add UpdateOne operation to the `updates` list.

            STEP 2c: Execute a single bulk_write for the entire chunk.
                collection.bulk_write(updates)

    RETURN total_processed_count
```
