# Pseudocode Documentation

This document provides pseudocode for the main algorithms in Researchmatch.

## 1. Researcher Matching Algorithm

```
FUNCTION match_researchers(query_text, corpus_embeddings, metadata, top_k):
    INPUT: query_text, corpus_embeddings, metadata, top_k
    OUTPUT: list of matched researchers
    
    STEP 1: Encode query text using sentence transformer
        query_embedding = model.encode(query_text)
        
    STEP 2: Compute cosine similarity with all corpus embeddings
        similarities = dot_product(corpus_embeddings, query_embedding)
        
    STEP 3: Get top-k most similar researchers
        top_indices = argsort(similarities, descending=True)[0:top_k]
        
    STEP 4: Retrieve metadata for top matches
        results = []
        FOR each index in top_indices:
            researcher_info = metadata[index]
            results.append(researcher_info)
            
    RETURN results
```

## 2. Document Clustering Algorithm

```
FUNCTION cluster_documents(document_texts, model, nlp):
    INPUT: list of document texts
    OUTPUT: list of themes with clustered documents
    
    STEP 1: Encode all documents to embeddings
        embeddings = model.encode(document_texts)
        
    STEP 2: Find optimal number of clusters using silhouette score
        best_k = 1
        best_score = -1
        FOR k FROM 2 TO min(10, num_documents):
            labels = KMeans(n_clusters=k).fit_predict(embeddings)
            score = silhouette_score(embeddings, labels)
            IF score > best_score:
                best_score = score
                best_k = k
                
    STEP 3: Perform clustering with optimal k
        IF best_k == 1:
            RETURN single theme with all documents
        ELSE:
            labels = AgglomerativeClustering(n_clusters=best_k).fit_predict(embeddings)
            
    STEP 4: Group documents by cluster label
        clusters = group_by_label(document_texts, labels)
        
    STEP 5: Extract keywords for each cluster
        themes = []
        FOR each cluster in clusters:
            combined_text = concatenate(cluster.documents)
            keywords = extract_keywords(combined_text, k=3)
            themes.append({
                theme_label: keywords,
                combined_text: combined_text,
                doc_indices: cluster.indices
            })
            
    RETURN themes
```

## 3. Keyword Extraction Algorithm

```
FUNCTION extract_keywords_hybrid(text, k, model, nlp):
    INPUT: text, number of keywords k, embedding model, NLP model
    OUTPUT: list of top-k keywords
    
    STEP 1: Extract candidate phrases using n-grams and noun chunks
        word_tokens = tokenize(text)
        ngram_candidates = generate_ngrams(word_tokens, max_len=2)
        noun_candidates = extract_noun_chunks(text, nlp)
        all_candidates = ngram_candidates + noun_candidates
        
    STEP 2: Filter noise patterns
        filtered = []
        FOR each candidate in all_candidates:
            IF not contains_noise(candidate) AND len(candidate) < 60:
                filtered.append(candidate)
                
    STEP 3: Rank candidates by semantic similarity to document
        doc_embedding = model.encode(text)
        candidate_embeddings = model.encode(filtered)
        similarities = cosine_similarity(doc_embedding, candidate_embeddings)
        
    STEP 4: Select top-k non-overlapping phrases
        ranked = []
        seen = set()
        FOR each index in argsort(similarities, descending=True):
            phrase = filtered[index]
            IF phrase not overlapping with seen:
                ranked.append(phrase)
                seen.add(phrase)
                IF len(ranked) == k:
                    BREAK
                    
    RETURN ranked
```

## 4. Corpus Building Algorithm

```
FUNCTION build_corpus_from_keywords(topic, pages, per_page):
    INPUT: research topic, number of pages, results per page
    OUTPUT: list of researcher profiles
    
    STEP 1: Query OpenAlex API
        works = []
        FOR page FROM 1 TO pages:
            response = query_openalex_api(topic, page, per_page)
            works.extend(response.results)
            
    STEP 2: Enrich with CrossRef metadata and PDFs
        FOR each work in works:
            crossref_data = query_crossref(work.title)
            work.metadata = crossref_data
            IF crossref_data.has_pdf_url:
                work.full_text = download_and_extract_pdf(crossref_data.pdf_url)
                
    STEP 3: Convert to researcher profiles
        profiles = {}
        FOR each work in works:
            FOR each author in work.authors:
                key = author.name + author.orcid
                IF key not in profiles:
                    profiles[key] = create_new_profile(author)
                profiles[key].publications.append(work)
                
    STEP 4: Tag publications with metadata
        FOR each profile in profiles:
            FOR each publication in profile.publications:
                publication.source = "OpenAlex"
                publication.topic = topic
                
    RETURN list(profiles.values())
```

## 5. Embedding Computation Algorithm

```
FUNCTION compute_embeddings(collection, model, batch_size):
    INPUT: MongoDB collection, embedding model, batch size
    OUTPUT: number of embeddings computed
    
    STEP 1: Fetch all documents without embeddings
        documents = collection.find({}, {publications, _id})
        
    STEP 2: Combine publication texts for each researcher
        payload = []
        FOR each doc in documents:
            combined_text = combine_researcher_text(doc.publications)
            IF combined_text is not empty:
                payload.append((doc._id, combined_text))
                
    STEP 3: Compute embeddings in batches
        FOR i FROM 0 TO len(payload) STEP batch_size:
            batch = payload[i:i+batch_size]
            texts = extract_texts(batch)
            embeddings = model.encode(texts, normalize=True)
            
            STEP 4: Store embeddings in database
            FOR each (doc_id, embedding) in zip(batch, embeddings):
                collection.update(
                    {_id: doc_id},
                    {embedding: embedding.tolist()}
                )
                
    RETURN len(payload)
```

## 6. Profile Deduplication Algorithm

```
FUNCTION insert_profiles_with_deduplication(collection, profiles):
    INPUT: MongoDB collection, list of new profiles
    OUTPUT: (inserted_count, skipped_count)
    
    STEP 1: Fetch existing profile keys from database
        existing = collection.find({}, {name, orcid})
        existing_keys = set()
        FOR each profile in existing:
            key = normalize(profile.name) + normalize(profile.orcid)
            existing_keys.add(key)
            
    STEP 2: Deduplicate within new batch
        deduped = []
        batch_keys = set()
        skipped = 0
        
        FOR each profile in profiles:
            key = normalize(profile.name) + normalize(profile.orcid)
            IF key in existing_keys OR key in batch_keys:
                skipped += 1
            ELSE:
                batch_keys.add(key)
                deduped.append(profile)
                
    STEP 3: Insert deduplicated profiles
        IF deduped is not empty:
            result = collection.insert_many(deduped)
            inserted = len(result.inserted_ids)
        ELSE:
            inserted = 0
            
    RETURN (inserted, skipped)
```
