# Pseudocode Documentation

This document provides a pseudocode for the main algorithms in Researchmatch, reflecting the final cloud-native architecture with pre-computed publication embeddings and search result caching.

1. Researcher Matching Algorithm (using Vector Search with Caching)

This algorithm runs when a user performs a search. It is extremely fast for cached results and memory-efficient.

FUNCTION match_researchers_with_vector_search(query_text, database_collection, top_k, cache_enabled=True):
    INPUT: A string of text representing the user's query.
           A connection to the MongoDB collection.
           The number of top matches to return.
           Whether to use result caching.
    OUTPUT: A list of the top_k most similar researcher profiles.
    
    STEP 1: Encode the user's query into a vector embedding.
        query_embedding = model.encode(query_text)
        
    STEP 2: Construct a MongoDB Aggregation Pipeline using $vectorSearch.
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "default_vector_index", // The pre-built index in Atlas
                    "queryVector": query_embedding,
                    "path": "embedding",            // The field containing main profile embeddings
                    "limit": top_k,
                    "numCandidates": top_k * 15     // Search more to improve accuracy
                }
            },
            {
                "$project": { // Request the fields needed for display + the score
                    "name": 1, 
                    "institution": 1,
                    "orcid": 1, // Include ORCID
                    "publications": 1, // Include full publication list with pre-computed embeddings
                    "profile_keywords": 1,
                    "score": { "$meta": "vectorSearchScore" } // The main profile match score
                }
            }
        ]
        
    STEP 3: Execute the pipeline on the database.
        results = database_collection.aggregate(pipeline)
        
    STEP 4: Cache the results for future use (if caching enabled).
        IF cache_enabled:
            cache[cache_key] = results (with 24-hour expiration)
        
    STEP 5: Return the results provided by the database.
        RETURN list(results)


2. Document Clustering Algorithm

This algorithm is used to group multiple user-uploaded documents into themes before matching.

FUNCTION cluster_documents(document_texts, model):
    INPUT: A list of text content from uploaded documents.
           The sentence-transformer model.
    OUTPUT: A list of theme objects, each containing a label and combined text.
    
    STEP 1: Encode all documents into a matrix of embeddings.
        embeddings = model.encode(document_texts)
        
    STEP 2: Find the optimal number of clusters (k) using the silhouette score.
        best_k = determine_optimal_k_via_silhouette(embeddings)
                
    STEP 3: Perform clustering with the optimal k (e.g., Agglomerative Clustering).
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


3. Embedding Computation Algorithm (Precomputation)

This is the long-running administrative task used to process the corpus. It now computes embeddings for profiles AND individual publications.

FUNCTION compute_embeddings(collection, model, nlp):
    INPUT: The MongoDB collection, embedding model, and NLP model.
    OUTPUT: The total count of processed profiles.
    
    STEP 1: Define the query to find documents needing processing.
        query = find documents where profile embedding OR profile keywords OR any publication embedding is missing.
    
    STEP 2: Process documents in large, independent chunks (e.g., 500).
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


4. Match Explanation and Publication Sorting

This happens within the Streamlit app when a user expands a result.
