# Domain Text Summarization Tool (OpenAI, Groq, Gemini)

A Flask web app for summarizing long documents with:

- LLM-based summarization via OpenAI, Groq, or Gemini
- Domain-aware summarization prompts (general, legal, medical, finance, technical)
- Optional domain-specific model mapping per provider
- Transformer-based fallback summarization using Hugging Face pipelines

## Features

- Web UI for inputting long text and selecting domain
- Adjustable summary style: short, medium, detailed
- Optional bullet-point summary format
- Automatic fallback to transformer summarization if provider call fails

## Project Structure

- `app.py`: Flask routes and web app entry point
- `summarizer.py`: OpenAI/Groq/Gemini + transformer summarization logic
- `templates/index.html`: Main page
- `static/style.css`: Styling
- `static/app.js`: Client-side form handling

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and configure:
   - `LLM_PROVIDER` as one of `openai`, `groq`, `gemini`
   - Matching API key for the selected provider
   - Optional domain model IDs for your provider
4. Run the app:
   ```bash
   flask --app app run --debug
   ```
5. Open the URL printed in your terminal.

## Provider Configuration

Set `LLM_PROVIDER` in `.env`:

- `groq` to use Groq (free tier available)
- `gemini` to use Gemini (free tier available)
- `openai` to use OpenAI

Examples:

- Groq:
   - `GROQ_API_KEY`
   - `GROQ_MODEL=llama-3.1-8b-instant`
- Gemini:
   - `GEMINI_API_KEY`
   - `GEMINI_MODEL=gemini-1.5-flash`
- OpenAI:
   - `OPENAI_API_KEY`
   - `OPENAI_MODEL=gpt-4`

Optional domain overrides are available for each provider:

- `*_MODEL_LEGAL`
- `*_MODEL_MEDICAL`
- `*_MODEL_FINANCE`

The app automatically selects the matching domain model when set.

## API Endpoint

`POST /summarize`

Request JSON:

```json
{
  "text": "Long document text...",
  "domain": "general",
  "length": "medium",
  "format": "paragraph"
}
```

Response JSON:

```json
{
  "summary": "Concise summary text...",
   "engine": "groq:llama-3.1-8b-instant"
}
```
