# Code Style Guide

This document outlines the coding standards and conventions used in the Researchmatch project.

## General Principles

- Write clean, readable, and maintainable code
- Follow PEP 8 Python style guidelines
- Use meaningful variable and function names
- Keep functions focused on a single responsibility
- Add docstrings to all functions
- Handle exceptions appropriately

## Naming Conventions

### Variables and Functions
- Use snake_case for variables and function names
- Use descriptive names that indicate purpose
- Avoid single-letter names except for loops

```python
# Good
researcher_count = 10
def extract_keywords(text):
    pass

# Avoid
rc = 10
def ext_kw(t):
    pass
```

### Constants
- Use UPPER_CASE for constants
- Define at module level

```python
MAX_CHARS = 60000
API_TIMEOUT = 30
```

### Classes
- Use PascalCase for class names
- Use descriptive names for class attributes

```python
class ResearchProfile:
    def __init__(self, name, orcid):
        self.name = name
        self.orcid = orcid
```

## Function Design

### Function Length
- Keep functions under 50 lines when possible
- Extract complex logic into helper functions
- Use early returns to reduce nesting

### Parameters
- Limit function parameters to 5 or fewer
- Use type hints for clarity
- Provide default values where appropriate

```python
def query_openalex(topic: str, pages: int = 2, per_page: int = 25) -> List[Dict]:
    pass
```

### Return Values
- Use type hints for return values
- Return None explicitly when no value
- Document return types in docstrings

## Documentation

### Module Docstrings
Every module should have a docstring explaining its purpose

```python
"""Core functions for text processing, file I/O, and API calls."""
```

### Function Docstrings
All functions should have docstrings describing purpose, parameters, and return values

```python
def extract_text(filepath: str) -> str:
    """Extract text from PDF or DOCX file.
    
    Args:
        filepath: Path to the document file
        
    Returns:
        Extracted text as string, empty string on failure
    """
```

## Code Organization

### File Structure
- Group related functions together
- Use comments to separate sections
- Order: imports, constants, functions, classes

```python
# Imports
import os
import re

# Constants
MAX_LENGTH = 1000

# Functions
def process_text(text):
    pass
```

### Import Organization
- Standard library imports first
- Third-party imports second
- Local imports third
- Use absolute imports

```python
import os
import re
from typing import List, Dict

import pandas as pd
import numpy as np

from core import normalize_ws
```

## Error Handling

### Exception Handling
- Catch specific exceptions, not bare except
- Log errors with context
- Return sensible defaults on failure

```python
try:
    result = risky_operation()
except FileNotFoundError as e:
    logger.error(f"File not found: {e}")
    return None
```

### Logging
- Use Python logging module
- Log at appropriate levels
- Include context in log messages

```python
logger.error(f"API query failed for topic '{topic}': {e}")
```

## Lambda Functions

### When to Use
- Simple one-line operations
- Functions used once as arguments
- Keep lambdas readable

```python
# Good - clear and concise
normalize_ws = lambda text: re.sub(r"\s+", " ", text or "").strip()

# Avoid - too complex
process = lambda x: x.lower().strip() if x else "" and len(x) > 5
```

## List Comprehensions

### Usage
- Prefer comprehensions for simple transformations
- Break complex logic into regular loops
- Keep comprehensions readable

```python
# Good
numbers = [x * 2 for x in range(10)]

# Avoid - too complex
result = [process(x) if condition(x) else transform(y) 
          for x in data for y in x.items() if valid(y)]
```

## MongoDB Operations

### Query Patterns
- Use specific field projections
- Handle None/missing values
- Use bulk operations for multiple updates

```python
# Good - specific projection
docs = collection.find({}, {"name": 1, "orcid": 1})

# Bulk updates
operations = [UpdateOne({"_id": id}, {"$set": {"field": value}}) 
              for id, value in updates]
collection.bulk_write(operations)
```

## Streamlit Conventions

### Session State
- Store results in session state
- Clear old results when rerunning
- Use descriptive keys

```python
st.session_state["match_results"] = df
st.session_state.pop("old_data", None)
```

### UI Organization
- Group related controls together
- Use expanders for optional settings
- Add helpful captions and labels

```python
with st.expander("Advanced Settings"):
    option = st.selectbox("Choose option", options)
```

## Performance Considerations

### Caching
- Use Streamlit caching for expensive operations
- Cache model loading
- Cache data transformations

```python
@st.cache_resource
def load_model_cached(model_name):
    return SentenceTransformer(model_name)
```

### Batch Processing
- Process data in batches for large datasets
- Use generators for memory efficiency
- Monitor progress with callbacks

```python
for i in range(0, len(data), batch_size):
    batch = data[i:i+batch_size]
    process_batch(batch)
    if progress_callback:
        progress_callback(i / len(data))
```

## Testing Considerations

### Function Design for Testing
- Write pure functions when possible
- Avoid global state
- Make dependencies injectable

```python
def process_data(data, processor=default_processor):
    return processor(data)
```

## Comments

### When to Comment
- Explain why, not what
- Document non-obvious behavior
- Add TODO for future improvements

```python
# Filter noise: URLs, common phrases, very long phrases
if any(noise in text for noise in noise_patterns):
    continue
    
# TODO: Add support for multiple languages
```

### When Not to Comment
- Avoid obvious comments
- Self-documenting code is better
- Remove commented-out code

```python
# Bad - obvious
x = x + 1  # increment x

# Good - clear variable name
total_count = previous_count + 1
```

## Version Control

### Commit Messages
- Use clear, descriptive commit messages
- Start with verb in present tense
- Reference issue numbers when applicable

```
Add clustering algorithm with silhouette scoring
Fix deduplication bug in profile insertion
Refactor keyword extraction for better performance
```

## Project-Specific Conventions

### Text Processing
- Always normalize whitespace
- Handle empty/None text gracefully
- Truncate long texts before processing

### API Calls
- Add delays between API requests
- Handle rate limits and timeouts
- Log failed requests with context

### Embeddings
- Always normalize embeddings
- Use consistent embedding dimensions
- Batch encode for efficiency
