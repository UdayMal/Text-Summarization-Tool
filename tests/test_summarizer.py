from types import SimpleNamespace

import summarizer


class FakeTokenizer:
    model_max_length = 1024

    def __call__(self, text, add_special_tokens=False):
        token_count = len(text.split())
        return {"input_ids": list(range(token_count))}

    def decode(self, token_ids, skip_special_tokens=True, clean_up_tokenization_spaces=True):
        return " ".join(f"w{i}" for i in token_ids)


class FakeSummarizationPipeline:
    def __init__(self):
        self.tokenizer = FakeTokenizer()
        self.model = SimpleNamespace(config=SimpleNamespace(max_position_embeddings=128))
        self.calls = 0

    def __call__(self, text, max_length, min_length, do_sample, truncation=True):
        self.calls += 1
        return [{"summary_text": f"summary-{self.calls}"}]


def test_transformer_chunking_handles_long_input(monkeypatch):
    fake_pipeline = FakeSummarizationPipeline()

    def fake_pipeline_factory(task, model):
        assert task == "summarization"
        return fake_pipeline

    monkeypatch.setattr("transformers.pipeline", fake_pipeline_factory)

    long_text = " ".join(["token"] * 500)
    result = summarizer.summarize_with_transformer(long_text, "medium", "paragraph")

    assert result["engine"].startswith("transformer:")
    assert result["summary"].strip() != ""
    assert fake_pipeline.calls > 1


def test_summarize_text_falls_back_when_providers_fail(monkeypatch):
    attempted = []

    def fake_provider(provider, text, domain, length, output_format):
        attempted.append(provider)
        raise RuntimeError(f"{provider} failed")

    def fake_transformer(text, length, output_format):
        return {"summary": "fallback summary", "engine": "transformer:fake"}

    monkeypatch.setenv("LLM_PROVIDER_PRIORITY", "gemini,groq")
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    monkeypatch.setattr(summarizer, "summarize_with_provider", fake_provider)
    monkeypatch.setattr(summarizer, "summarize_with_transformer", fake_transformer)

    result = summarizer.summarize_text(
        text="A sufficiently long test input for fallback behavior.",
        domain="general",
        length="short",
        output_format="paragraph",
    )

    assert result["engine"] == "transformer:fake"
    assert attempted == ["gemini", "groq"]
