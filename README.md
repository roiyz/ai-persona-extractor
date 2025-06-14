# Confluence AI Persona Extractor

This tool scans Confluence pages and uses a local Ollama LLM to extract persona-related insights from recently updated content.

## Features
- Connects to Confluence via API and retrieves pages created or modified within a specified number of days.
- Uses Ollama-hosted local models to analyze page content.
- Outputs JSON with findings including timestamps, analysis, confidence estimates, and source URLs.
- Logs per-page processing time and estimated finish time.
- Two-phase architecture allows validation-only runs and data filtering.

## Usage

```bash
python3 conf_scanner.py SPACE_KEY DAYS_BACK MODEL_NAME [--prompt PROMPT] [--prompt-file FILE] [--verbose info|debug]
```

### Example

```bash
python3 conf_scanner.py ConfProj1 30 qwen3:latest --prompt-file prompts/persona_prompt.txt --verbose info
```

## Environment Variables

See `.env.example` for expected variables.

## Output

Results are saved to:
```
./evaluation_results/onepass_MODELNAME_DAYSBACK_DATE/DATE_MODELNAME_DAYSBACK_results.json
```

## Requirements

- Python 3.8+
- A running [Ollama](https://ollama.com/) server
- Confluence API token

## Disclaimer

This script is provided for reference purposes only. Use at your own risk.
