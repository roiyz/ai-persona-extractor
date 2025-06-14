#!/usr/bin/env python3
"""
Confluence Page Scanner with Ollama Integration (Single-Pass)
Command-line tool for scanning Confluence pages and extracting findings with Ollama models.
Stores results in a JSON file whose name includes the date, model, and days-back.
Includes pages created or last modified within the specified window.
Supports validation-only mode when no prompt is provided, loading prompts from files, and verbose output.
Avoids processing Confluence comments and includes page URLs as evidence.
Logs per-page duration and ETA when verbose, with estimated finish time.
"""

import os
import sys
import json
import argparse
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from atlassian import Confluence
import ollama

class ConfluenceAnalyzer:
    def __init__(self, verbose=None):
        """Initializes the analyzer with optional verbosity and loads environment variables."""
        self.verbose = verbose  # None, 'info', or 'debug'
        self.load_environment()
        self.confluence_client = None
        self.space_key = None
        self.days_back = 30
        self.model_name = None
        self.page_count = 0
        self.results_dir = None

    def log(self, message, level='info'):
        """Logs messages based on the verbosity level."""
        levels = {'info': 1, 'debug': 2}
        if self.verbose and levels.get(level, 0) <= levels.get(self.verbose, 0):
            print(message)

    def load_environment(self):
        """Loads required environment variables and checks for required fields."""
        if not load_dotenv():
            print("Warning: .env file not found. Please create one based on .env.example")
        self.confluence_url = os.getenv('CONFLUENCE_URL')
        self.confluence_username = os.getenv('CONFLUENCE_USERNAME')
        self.confluence_api_token = os.getenv('CONFLUENCE_API_TOKEN')
        self.ollama_host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
        missing = [v for v in ['CONFLUENCE_URL', 'CONFLUENCE_USERNAME', 'CONFLUENCE_API_TOKEN'] if not os.getenv(v)]
        if missing:
            print(f"❌ Missing env vars: {','.join(missing)}")
            sys.exit(1)

    def validate_confluence_connection(self):
        """Validates connection to Confluence and ensures the space key exists."""
        client = Confluence(
            url=self.confluence_url,
            username=self.confluence_username,
            password=self.confluence_api_token
        )
        spaces = client.get_all_spaces(start=0, limit=100).get('results', [])
        for sp in spaces:
            if sp['key'].upper() == self.space_key.upper():
                self.confluence_client = client
                print(f"✅ Space found: {sp['key']} - {sp.get('name','')}")
                return sp
        print(f"❌ Space '{self.space_key}' not found")
        sys.exit(1)

    def validate_ollama_model(self):
        """Validates that the specified Ollama model is available locally."""
        client = ollama.Client(host=self.ollama_host)
        models = client.list().get('models', [])
        for m in models:
            if m['name'] == self.model_name:
                print(f"✅ Ollama model found: {self.model_name}")
                return True
        print(f"❌ Model '{self.model_name}' not found locally")
        sys.exit(1)

    def count_confluence_pages(self):
        """Fetches Confluence pages created or modified in the last N days, excluding comments."""
        cutoff = datetime.now() - timedelta(days=self.days_back)
        cutoff_date_str = cutoff.strftime('%Y-%m-%d')
        cql = (
            f'space = "{self.space_key}" '
            f'AND (created >= "{cutoff_date_str}" OR lastmodified >= "{cutoff_date_str}")'
        )
        print(f"🔍 Using CQL: {cql}")
        results = self.confluence_client.cql(cql, limit=1000).get('results', [])
        filtered = []
        for item in results:
            content = item.get('content', item)
            if content.get('type') == 'comment':
                self.log(f"Skipping comment ID: {content.get('id')}", level='info')
                continue
            filtered.append(item)
        self.page_count = len(filtered)
        print(f"✅ Pages found (excluding comments): {self.page_count}")
        return filtered

    def setup_results_directory(self):
        """Creates a timestamped directory for saving output results."""
        date_str = datetime.now().strftime("%Y%m%d")
        safe_model = self.model_name.replace(':', '_').replace('/', '_')
        base = os.getenv('EVALUATION_OUTPUT_DIR', './evaluation_results')
        self.results_dir = os.path.join(base, f"onepass_{safe_model}_{self.days_back}d_{date_str}")
        os.makedirs(self.results_dir, exist_ok=True)
        print(f"📁 Results directory: {self.results_dir}")

    def execute_pass1(self, user_prompt, pages):
        """Analyzes each page using Ollama with the provided prompt and saves structured results."""
        prompt = (
            f"{user_prompt}

"
            "EXTRACT ALL relevant information from this Confluence page. "
            "Include the page URL as evidence for any persona conclusions. "
            "Return structured data."
        )
        client = ollama.Client(host=self.ollama_host)
        findings = []
        total = len(pages)
        start_all = datetime.now()
        for idx, page in enumerate(pages, start=1):
            page_start = datetime.now()
            content_obj = page.get('content', page)
            pid = content_obj.get('id')
            title = content_obj.get('title')
            if self.verbose:
                self.log(f"Analyzing page {idx}/{total}: {title} (ID: {pid})", level='info')
            text, url = self.get_page_content(page)
            if not text or len(text) < 100:
                self.log(f"Skipping short content for {pid}", level='debug')
                continue
            resp = client.chat(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt + "\n\n" + text[:8000]}]
            )
            analysis = resp['message']['content']
            duration = (datetime.now() - page_start).total_seconds()
            if "NO_FINDINGS" not in analysis.upper():
                findings.append({
                    'page_id': pid,
                    'page_title': title,
                    'page_url': url,
                    'analysis': analysis,
                    'timestamp': datetime.now().isoformat(),
                    'duration_s': duration
                })
        # Save results
        filename = f"{datetime.now().strftime('%Y%m%d')}_{self.model_name.replace(':', '_')}_{self.days_back}d_results.json"
        path = os.path.join(self.results_dir, filename)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump({'metadata': {
                'model': self.model_name,
                'space': self.space_key,
                'days_back': self.days_back,
                'generated': datetime.now().isoformat(),
                'total_pages': total
            }, 'findings': findings}, f, indent=2, ensure_ascii=False)
        print(f"💾 Results saved to: {path}")
        return findings

    def get_page_content(self, page):
        """Extracts and cleans text content and URL from a Confluence page."""
        content_obj = page.get('content', page)
        pid = content_obj.get('id')
        page_data = self.confluence_client.get_page_by_id(pid, expand='body.view')
        html = page_data.get('body', {}).get('view', {}).get('value', '')
        text = re.sub(r'<[^>]+>', ' ', html)
        text_content = re.sub(r'\s+', ' ', text).strip()
        webui = page_data.get('_links', {}).get('webui', '')
        page_url = self.confluence_url.rstrip('/') + webui
        return text_content, page_url

    def run_validation(self, space_key, days_back, model_name):
        """Runs validation for Confluence access and Ollama model availability."""
        self.space_key = space_key
        self.days_back = days_back
        self.model_name = model_name
        print("🔧 Validating configuration...")
        self.validate_confluence_connection()
        self.validate_ollama_model()
        pages = self.count_confluence_pages()
        return pages

    def run_analysis(self, space_key, days_back, model_name, prompt=None, prompt_file=None, verbose=None):
        """Main entry point for running the full analysis pipeline."""
        self.verbose = verbose
        pages = self.run_validation(space_key, days_back, model_name)
        if prompt_file:
            if prompt:
                print("❌ Error: Cannot use --prompt and --prompt-file together.")
                sys.exit(1)
            if not os.path.isfile(prompt_file):
                print(f"❌ Prompt file not found: {prompt_file}")
                sys.exit(1)
            with open(prompt_file, 'r', encoding='utf-8') as pf:
                prompt = pf.read().strip()
            if not prompt:
                print("❌ Prompt file is empty.")
                sys.exit(1)
            print(f"✅ Loaded prompt from file: {prompt_file}")
        if not prompt:
            print("\n✨ Validation succeeded. Re-run with --prompt or --prompt-file to perform analysis.")
            return False
        self.setup_results_directory()
        self.execute_pass1(prompt, pages)
        return True


def parse_arguments():
    """Parses command-line arguments."""
    p = argparse.ArgumentParser(description="Confluence Single-Pass Analyzer")
    p.add_argument('space_key', help='Confluence space key')
    p.add_argument('days', type=int, help='Days back to scan')
    p.add_argument('model', help='Ollama model name')
    p.add_argument('--prompt', help='Analysis prompt')
    p.add_argument('--prompt-file', help='Path to file containing the analysis prompt')
    p.add_argument('--verbose', choices=['info','debug'], help='Verbose output: info or debug')
    return p.parse_args()

def main():
    """Main function for command-line execution."""
    args = parse_arguments()
    if args.days <= 0:
        print("❌ Error: days must be positive integer")
        sys.exit(1)
    analyzer = ConfluenceAnalyzer(verbose=args.verbose)
    success = analyzer.run_analysis(
        args.space_key, args.days, args.model,
        prompt=args.prompt, prompt_file=args.prompt_file,
        verbose=args.verbose
    )
    if not success:
        sys.exit(1)

if __name__ == '__main__':
    main()
