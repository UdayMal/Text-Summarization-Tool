import os
from typing import Dict, List

from dotenv import load_dotenv
import google.generativeai as genai
from openai import OpenAI


load_dotenv()


DOMAIN_PROMPTS: Dict[str, str] = {
    "general": (
        "You are an expert summarizer. Produce faithful, concise summaries while preserving key points."
    ),
    "legal": (
        "You are a legal summarization assistant. Highlight obligations, rights, liabilities,"
        " deadlines, and contractual or regulatory implications."
    ),
    "medical": (
        "You are a medical summarization assistant. Emphasize diagnosis, symptoms,"
        " treatment plan, medications, and follow-up actions."
    ),
    "finance": (
        "You are a financial summarization assistant. Focus on financial performance,"
        " risks, projections, and material business updates."
    ),
    "technical": (
        "You are a technical summarization assistant. Focus on architecture, implementation details,"
        " constraints, and technical trade-offs."
    ),
}

LENGTH_INSTRUCTIONS = {
    "short": "Return 2-4 sentences maximum.",
    "medium": "Return 1 concise paragraph of 5-8 sentences.",
    "detailed": "Return 2 concise paragraphs with complete key details.",
}

def _get_provider() -> str:
    return os.getenv("LLM_PROVIDER", "openai").strip().lower()


def _get_model_by_domain(provider: str) -> Dict[str, str]:
    if provider == "groq":
        default_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        return {
            "general": default_model,
            "technical": default_model,
            "legal": os.getenv("GROQ_MODEL_LEGAL") or default_model,
            "medical": os.getenv("GROQ_MODEL_MEDICAL") or default_model,
            "finance": os.getenv("GROQ_MODEL_FINANCE") or default_model,
        }

    if provider == "gemini":
        default_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        return {
            "general": default_model,
            "technical": default_model,
            "legal": os.getenv("GEMINI_MODEL_LEGAL") or default_model,
            "medical": os.getenv("GEMINI_MODEL_MEDICAL") or default_model,
            "finance": os.getenv("GEMINI_MODEL_FINANCE") or default_model,
        }

    default_model = os.getenv("OPENAI_MODEL", "gpt-4")
    return {
        "general": default_model,
        "technical": default_model,
        "legal": os.getenv("OPENAI_MODEL_LEGAL") or default_model,
        "medical": os.getenv("OPENAI_MODEL_MEDICAL") or default_model,
        "finance": os.getenv("OPENAI_MODEL_FINANCE") or default_model,
    }


def _build_user_prompt(text: str, domain: str, length: str, output_format: str) -> str:
    format_instruction = (
        "Use bullet points." if output_format == "bullet" else "Use plain paragraph text."
    )
    length_instruction = LENGTH_INSTRUCTIONS.get(length, LENGTH_INSTRUCTIONS["medium"])

    return (
        f"Summarize the following {domain} document. "
        f"{length_instruction} {format_instruction}\n\n"
        "Document:\n"
        f"{text}"
    )


def summarize_with_llm(text: str, domain: str, length: str, output_format: str) -> Dict[str, str]:
    provider = _get_provider()
    model_by_domain = _get_model_by_domain(provider)
    model = model_by_domain.get(domain, model_by_domain["general"])
    system_prompt = DOMAIN_PROMPTS.get(domain, DOMAIN_PROMPTS["general"])
    user_prompt = _build_user_prompt(text=text, domain=domain, length=length, output_format=output_format)

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise ValueError("GROQ_API_KEY is not configured.")

        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        response = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        summary = response.choices[0].message.content.strip()
        return {"summary": summary, "engine": f"groq:{model}"}

    if provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        genai.configure(api_key=api_key)
        gemini_model = genai.GenerativeModel(model)
        prompt = f"{system_prompt}\n\n{user_prompt}"
        response = gemini_model.generate_content(prompt)
        summary = (response.text or "").strip()
        if not summary:
            raise ValueError("Gemini returned an empty summary.")
        return {"summary": summary, "engine": f"gemini:{model}"}

    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured.")

    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    summary = response.choices[0].message.content.strip()
    return {"summary": summary, "engine": f"openai:{model}"}


def summarize_with_transformer(text: str, length: str, output_format: str) -> Dict[str, str]:
    # Lazy import so local fallback dependency loads only when needed.
    from transformers import pipeline

    model_name = os.getenv("HF_SUMMARIZER_MODEL", "facebook/bart-large-cnn")
    summarizer = pipeline("summarization", model=model_name)

    tokenizer = summarizer.tokenizer
    model_config = summarizer.model.config
    max_positions = getattr(model_config, "max_position_embeddings", None)
    tokenizer_limit = getattr(tokenizer, "model_max_length", 1024)

    # Keep a conservative token budget to avoid position embedding overflows.
    if not isinstance(tokenizer_limit, int) or tokenizer_limit > 10000:
        tokenizer_limit = 1024
    base_limit = max_positions if isinstance(max_positions, int) else tokenizer_limit
    chunk_token_limit = max(256, min(900, base_limit - 24))

    # Conservative token lengths for readability.
    if length == "short":
        max_length, min_length = 80, 25
    elif length == "detailed":
        max_length, min_length = 220, 90
    else:
        max_length, min_length = 140, 50

    min_length = min(min_length, max_length - 10)

    def _split_text_by_tokens(source_text: str) -> List[str]:
        token_ids = tokenizer(source_text, add_special_tokens=False)["input_ids"]
        if not token_ids:
            return []

        chunks: List[str] = []
        for i in range(0, len(token_ids), chunk_token_limit):
            chunk_ids = token_ids[i : i + chunk_token_limit]
            chunk_text = tokenizer.decode(
                chunk_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True,
            ).strip()
            if chunk_text:
                chunks.append(chunk_text)
        return chunks

    def _summarize_chunk(chunk_text: str) -> str:
        result = summarizer(
            chunk_text,
            max_length=max_length,
            min_length=min_length,
            do_sample=False,
            truncation=True,
        )
        return result[0]["summary_text"].strip()

    chunks = _split_text_by_tokens(text)
    if not chunks:
        raise ValueError("Input text is empty after tokenization.")

    first_pass = [_summarize_chunk(chunk) for chunk in chunks]

    if len(first_pass) == 1:
        summary = first_pass[0]
    else:
        # Second pass to merge chunk-level summaries into one cohesive summary.
        merged = " ".join(first_pass)
        merged_chunks = _split_text_by_tokens(merged)
        second_pass = [_summarize_chunk(chunk) for chunk in merged_chunks]
        summary = " ".join(second_pass).strip()

    if output_format == "bullet":
        sentences = [line.strip() for line in summary.replace("\n", " ").split(".") if line.strip()]
        summary = "\n".join(f"- {sentence}." for sentence in sentences[:8])

    return {"summary": summary, "engine": f"transformer:{model_name}"}


def summarize_text(text: str, domain: str, length: str, output_format: str) -> Dict[str, str]:
    try:
        return summarize_with_llm(
            text=text,
            domain=domain,
            length=length,
            output_format=output_format,
        )
    except Exception as llm_error:
        # Fall back to local transformer model if the LLM provider is unavailable.
        try:
            return summarize_with_transformer(text=text, length=length, output_format=output_format)
        except Exception as fallback_error:
            raise RuntimeError(
                "Summarization failed for both configured LLM provider and transformer fallback."
            ) from fallback_error
