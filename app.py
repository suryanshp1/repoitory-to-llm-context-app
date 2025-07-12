import streamlit as st
import requests
import base64
import os
import fnmatch
from typing import List, Dict, Optional, Tuple
from datetime import datetime
import re

from dotenv import load_dotenv

load_dotenv()

class GitHubRepoAnalyzer:
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv('GITHUB_TOKEN')
        self.headers = {
            'Authorization': f'token {self.token}' if self.token else None,
            'Accept': 'application/vnd.github.v3+json'
        }
        if not self.token:
            # Remove None authorization header for public repos
            self.headers = {'Accept': 'application/vnd.github.v3+json'}
    
    def get_repo_info(self, repo_url: str) -> Tuple[str, str]:
        """Extract owner and repo name from GitHub URL"""
        patterns = [
            r'github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$',
            r'github\.com/([^/]+)/([^/]+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, repo_url)
            if match:
                return match.group(1), match.group(2)
        
        raise ValueError("Invalid GitHub repository URL")
    
    def get_repo_contents(self, owner: str, repo: str, path: str = "") -> List[Dict]:
        """Get repository contents recursively"""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            raise Exception(f"Failed to fetch repo contents: {response.status_code} - {response.text}")
        
        return response.json()
    
    def get_file_content(self, owner: str, repo: str, path: str) -> str:
        """Get file content from GitHub"""
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        response = requests.get(url, headers=self.headers)
        
        if response.status_code != 200:
            return f"Error fetching file: {response.status_code}"
        
        content = response.json()
        if content.get('encoding') == 'base64':
            try:
                return base64.b64decode(content['content']).decode('utf-8')
            except UnicodeDecodeError:
                return f"[Binary file - {content.get('size', 0)} bytes]"
        
        return content.get('content', '')
    
    def should_exclude_file(self, file_path: str, exclude_patterns: List[str]) -> bool:
        """Check if file should be excluded based on patterns"""
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(os.path.basename(file_path), pattern):
                return True
        return False
    
    def get_all_files(self, owner: str, repo: str, path: str = "", exclude_patterns: List[str] = None) -> List[Dict]:
        """Recursively get all files in repository"""
        if exclude_patterns is None:
            exclude_patterns = []
        
        all_files = []
        try:
            contents = self.get_repo_contents(owner, repo, path)
            
            for item in contents:
                item_path = item['path']
                
                if self.should_exclude_file(item_path, exclude_patterns):
                    continue
                
                if item['type'] == 'file':
                    all_files.append(item)
                elif item['type'] == 'dir':
                    all_files.extend(self.get_all_files(owner, repo, item_path, exclude_patterns))
        except Exception as e:
            st.error(f"Error fetching contents for {path}: {str(e)}")
        
        return all_files

def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"

def estimate_file_size(content: str) -> int:
    """Estimate file size in bytes"""
    return len(content.encode('utf-8'))

def create_context_document(
    analyzer: GitHubRepoAnalyzer,
    owner: str,
    repo: str,
    max_size_bytes: int,
    exclude_patterns: List[str],
    feature_request: Optional[str] = None
) -> str:
    """Create the context document"""
    
    # Get repository information
    repo_info_url = f"https://api.github.com/repos/{owner}/{repo}"
    repo_response = requests.get(repo_info_url, headers=analyzer.headers)
    repo_data = repo_response.json() if repo_response.status_code == 200 else {}
    
    # Start building the context document
    context = []
    
    # Header
    context.append(f"# Repository Context: {owner}/{repo}")
    context.append(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    context.append("")
    
    # Repository information
    if repo_data:
        context.append("## Repository Information")
        context.append(f"- **Description**: {repo_data.get('description', 'No description')}")
        context.append(f"- **Language**: {repo_data.get('language', 'Not specified')}")
        context.append(f"- **Stars**: {repo_data.get('stargazers_count', 0)}")
        context.append(f"- **Forks**: {repo_data.get('forks_count', 0)}")
        context.append(f"- **Created**: {repo_data.get('created_at', 'Unknown')}")
        context.append(f"- **Updated**: {repo_data.get('updated_at', 'Unknown')}")
        context.append("")
    
    # Feature request section
    if feature_request:
        context.append("## Feature Request / Bug Fix Details")
        context.append(feature_request)
        context.append("")
    
    # File structure
    context.append("## Repository Structure")
    
    # Get all files
    with st.spinner("Fetching repository files..."):
        all_files = analyzer.get_all_files(owner, repo, exclude_patterns=exclude_patterns)
    
    # Sort files by path
    all_files.sort(key=lambda x: x['path'])
    
    # Add file tree
    context.append("```")
    prev_dirs = []
    for file_info in all_files:
        path_parts = file_info['path'].split('/')
        
        # Add directory structure
        for i, part in enumerate(path_parts[:-1]):
            current_dir = '/'.join(path_parts[:i+1])
            if current_dir not in prev_dirs:
                indent = "  " * i
                context.append(f"{indent}{part}/")
                prev_dirs.append(current_dir)
        
        # Add file
        indent = "  " * (len(path_parts) - 1)
        context.append(f"{indent}{path_parts[-1]}")
    
    context.append("```")
    context.append("")
    
    # File contents
    context.append("## File Contents")
    context.append("")
    
    current_size = estimate_file_size('\n'.join(context))
    files_added = 0
    files_skipped = 0
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, file_info in enumerate(all_files):
        progress_bar.progress((i + 1) / len(all_files))
        status_text.text(f"Processing: {file_info['path']}")
        
        # Check if adding this file would exceed size limit
        try:
            file_content = analyzer.get_file_content(owner, repo, file_info['path'])
            file_section = f"### {file_info['path']}\n\n```\n{file_content}\n```\n\n"
            file_size = estimate_file_size(file_section)
            
            if current_size + file_size > max_size_bytes:
                files_skipped += 1
                continue
            
            context.append(f"### {file_info['path']}")
            context.append("")
            context.append("```")
            context.append(file_content)
            context.append("```")
            context.append("")
            
            current_size += file_size
            files_added += 1
            
        except Exception as e:
            st.warning(f"Could not process file {file_info['path']}: {str(e)}")
    
    # Summary
    context.insert(-1, "## Summary")
    context.insert(-1, f"- Total files processed: {files_added}")
    context.insert(-1, f"- Files skipped due to size limit: {files_skipped}")
    context.insert(-1, f"- Final document size: {format_file_size(current_size)}")
    context.insert(-1, "")
    
    progress_bar.empty()
    status_text.empty()
    
    return '\n'.join(context)

def main():
    st.set_page_config(
        page_title="GitHub Repository to LLM Context Converter",
        page_icon="📁",
        layout="wide"
    )
    
    st.title("📁 GitHub Repository to LLM Context Converter")
    st.markdown("Convert any GitHub repository into a comprehensive context document for LLM analysis")
    
    # Sidebar for configuration
    st.sidebar.header("Configuration")
    
    # GitHub Token
    default_token = os.getenv('GITHUB_TOKEN', '')
    github_token = st.sidebar.text_input(
        "GitHub Token (optional for public repos)",
        value=None,
        type="password",
        help="Required for private repositories and to avoid rate limits"
    )
    
    # Repository URL
    repo_url = st.text_input(
        "GitHub Repository URL",
        placeholder="https://github.com/owner/repository",
        help="Enter the full GitHub repository URL"
    )
    
    # File size limit
    col1, col2 = st.columns(2)
    with col1:
        size_unit = st.selectbox("Size Unit", ["KB", "MB"])
    with col2:
        size_value = st.number_input(
            f"Maximum File Size ({size_unit})",
            min_value=1,
            max_value=100 if size_unit == "MB" else 10000,
            value=5 if size_unit == "MB" else 500,
            help="Maximum size of the generated context document"
        )
    
    max_size_bytes = size_value * (1024 * 1024 if size_unit == "MB" else 1024)
    
    # Exclude patterns
    st.subheader("File Exclusion Patterns")
    exclude_input = st.text_area(
        "Exclude Patterns (one per line)",
        value="*.md\n*.txt\n*.log\n*.pyc\n__pycache__\n.git\n.gitignore\nnode_modules\n.DS_Store",
        help="Enter file patterns to exclude (supports wildcards like *.md)"
    )
    
    exclude_patterns = [pattern.strip() for pattern in exclude_input.split('\n') if pattern.strip()]
    
    # Feature request
    st.subheader("Feature Request / Bug Fix Details (Optional)")
    feature_request = st.text_area(
        "Describe the feature or bug fix",
        placeholder="Describe what you want to implement or fix in this repository...",
        help="This will be included in the context to help the LLM understand your specific needs"
    )
    
    # Generate button
    if st.button("🚀 Generate Context Document", type="primary"):
        if not repo_url:
            st.error("Please enter a GitHub repository URL")
            return
        
        try:
            # Initialize analyzer
            analyzer = GitHubRepoAnalyzer(github_token if github_token else default_token)
            
            # Extract repo info
            owner, repo = analyzer.get_repo_info(repo_url)
            
            st.info(f"Processing repository: {owner}/{repo}")
            
            # Generate context document
            context_doc = create_context_document(
                analyzer=analyzer,
                owner=owner,
                repo=repo,
                max_size_bytes=max_size_bytes,
                exclude_patterns=exclude_patterns,
                feature_request=feature_request if feature_request else None
            )
            
            # Display results
            st.success("Context document generated successfully!")
            
            # Show document stats
            doc_size = estimate_file_size(context_doc)
            st.info(f"Document size: {format_file_size(doc_size)}")
            
            # Download button
            st.download_button(
                label="📥 Download Context Document",
                data=context_doc,
                file_name=f"{owner}_{repo}_context_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                mime="text/markdown"
            )
            
            # Preview
            with st.expander("📖 Preview Context Document"):
                st.markdown(context_doc)
            
        except Exception as e:
            st.error(f"Error processing repository: {str(e)}")
            st.error("Please check your repository URL and token (if required)")

if __name__ == "__main__":
    main()