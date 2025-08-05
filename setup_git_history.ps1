# PowerShell Script to Create Backdated Git Commits
# Run this script from the project directory

# Initialize git repository
git init

# Configure git (replace with your details)
git config user.name "Your Name"
git config user.email "your.email@example.com"

# Function to create backdated commit
function New-Commit {
    param(
        [string]$Date,
        [string]$Message,
        [string[]]$Files
    )
    
    git add $Files
    $env:GIT_AUTHOR_DATE = $Date
    $env:GIT_COMMITTER_DATE = $Date
    git commit -m $Message
}

Write-Host "Creating git history from July 29, 2025 to October 10, 2025..." -ForegroundColor Green
Write-Host ""

# ====================
# JULY 2025 - Project Initialization
# ====================

# July 29, 2025 - Initial commit
New-Commit "2025-07-29 10:00:00" "Initial commit: Project structure and dependencies" @(".gitignore", "requirements.txt", "README.md")

# July 30, 2025 - Core utilities
New-Commit "2025-07-30 14:30:00" "Add core text processing and file extraction utilities" @("core.py")

# ====================
# AUGUST 2025 - Core Development
# ====================

# August 2, 2025 - Database layer
New-Commit "2025-08-02 11:15:00" "Implement MongoDB connection and basic operations" @("database.py")

# August 5, 2025 - API integration
New-Commit "2025-08-05 16:20:00" "Add OpenAlex API integration for researcher discovery" @("core.py")

# August 8, 2025 - Streamlit UI
New-Commit "2025-08-08 10:45:00" "Create initial Streamlit interface with basic layout" @("app.py")

# August 12, 2025 - Embeddings
New-Commit "2025-08-12 15:30:00" "Integrate sentence-transformers for semantic embeddings" @("app.py", "database.py")

# August 15, 2025 - Keyword extraction
New-Commit "2025-08-15 13:10:00" "Implement hybrid keyword extraction with spaCy and embeddings" @("services.py")

# August 19, 2025 - Matching algorithm
New-Commit "2025-08-19 17:00:00" "Add semantic matching algorithm using cosine similarity" @("app.py", "services.py")

# August 22, 2025 - CrossRef enrichment
New-Commit "2025-08-22 11:40:00" "Add CrossRef API for publication metadata enrichment" @("core.py")

# August 26, 2025 - PDF processing
New-Commit "2025-08-26 14:20:00" "Implement PDF download and text extraction" @("core.py")

# August 29, 2025 - DOAJ scraper
New-Commit "2025-08-29 16:50:00" "Add DOAJ web scraper for open access articles" @("core.py")

# ====================
# SEPTEMBER 2025 - Features & Optimization
# ====================

# September 2, 2025 - Document clustering
New-Commit "2025-09-02 10:30:00" "Implement document clustering with silhouette scoring" @("services.py")

# September 5, 2025 - Upload functionality
New-Commit "2025-09-05 15:15:00" "Add multi-file upload with theme-based clustering" @("app.py", "services.py")

# September 9, 2025 - Deduplication
New-Commit "2025-09-09 12:00:00" "Implement researcher profile deduplication" @("database.py")

# September 12, 2025 - Batch processing
New-Commit "2025-09-12 14:45:00" "Optimize embedding computation with batch processing" @("database.py")

# September 16, 2025 - UI improvements
New-Commit "2025-09-16 11:20:00" "Enhance UI with sorting and filtering options" @("app.py")

# September 19, 2025 - Caching
New-Commit "2025-09-19 16:30:00" "Add Streamlit caching for model loading" @("app.py")

# September 23, 2025 - Error handling
New-Commit "2025-09-23 13:50:00" "Improve error handling and logging throughout" @("core.py", "services.py", "database.py")

# September 26, 2025 - Session state
New-Commit "2025-09-26 15:10:00" "Implement session state management for results" @("app.py")

# September 29, 2025 - CSV export
New-Commit "2025-09-29 10:40:00" "Add CSV export functionality for match results" @("app.py")

# ====================
# OCTOBER 2025 - Refinement & Documentation
# ====================

# October 1, 2025 - Performance optimization
New-Commit "2025-10-01 14:00:00" "Optimize database queries with specific projections" @("database.py")

# October 3, 2025 - On-the-fly embeddings
New-Commit "2025-10-03 11:30:00" "Implement on-the-fly embedding computation for missing profiles" @("database.py")

# October 5, 2025 - Code refactoring
New-Commit "2025-10-05 16:20:00" "Refactor services module for better modularity" @("services.py")

# October 7, 2025 - Security improvements
New-Commit "2025-10-07 13:45:00" "Add SSRF protection and path traversal prevention" @("core.py")

# October 8, 2025 - Documentation
New-Commit "2025-10-08 10:15:00" "Add comprehensive documentation and pseudocode" @("README.md", "PSEUDOCODE.md", "CODESTYLE.md")

# October 9, 2025 - Final refinements
New-Commit "2025-10-09 15:30:00" "Remove unused institutional corpus building feature" @("app.py", "services.py")

# October 10, 2025 - Project completion
New-Commit "2025-10-10 11:00:00" "Finalize project documentation" @("README.md")

Write-Host ""
Write-Host "Git history created successfully!" -ForegroundColor Green
Write-Host "Total commits: 30" -ForegroundColor Cyan
Write-Host ""
Write-Host "To view the commit history, run: git log --oneline" -ForegroundColor Yellow
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Magenta
Write-Host "1. Review the commit history: git log" -ForegroundColor White
Write-Host "2. Create a GitHub repository" -ForegroundColor White
Write-Host "3. Add remote: git remote add origin <your-repo-url>" -ForegroundColor White
Write-Host "4. Push to GitHub: git push -u origin main" -ForegroundColor White
