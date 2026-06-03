import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Dict, List

from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import RequestEntityTooLarge

from summarizer import summarize_text


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH_BYTES", str(2 * 1024 * 1024)))

limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[os.getenv("DEFAULT_RATE_LIMIT", "30 per minute")],
)

SUPPORTED_FILE_EXTENSIONS = {".txt", ".pdf", ".docx"}
JOB_STORE: Dict[str, Dict] = {}
JOB_LOCK = threading.Lock()


@app.errorhandler(RequestEntityTooLarge)
def handle_large_payload(error):
    return jsonify({"error": "Payload too large. Reduce document size and try again."}), 413


@app.get("/")
def index():
    return render_template("index.html")


def _split_text_into_chunks(text: str, max_chars: int = 6000) -> List[str]:
    words = text.split()
    if not words:
        return []

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_length = 0

    for word in words:
        word_len = len(word) + 1
        if current_chunk and current_length + word_len > max_chars:
            chunks.append(" ".join(current_chunk))
            current_chunk = [word]
            current_length = len(word)
        else:
            current_chunk.append(word)
            current_length += word_len

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def _update_job(job_id: str, **kwargs):
    with JOB_LOCK:
        if job_id in JOB_STORE:
            JOB_STORE[job_id].update(kwargs)


def _summarize_with_timeout(
    job_id: str,
    text: str,
    domain: str,
    length: str,
    output_format: str,
    status_message: str,
):
    timeout_seconds = max(20, int(os.getenv("CHUNK_SUMMARY_TIMEOUT_SECONDS", "120")))
    heartbeat_seconds = 5

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            summarize_text,
            text=text,
            domain=domain,
            length=length,
            output_format=output_format,
        )

        elapsed = 0
        while True:
            try:
                return future.result(timeout=heartbeat_seconds)
            except TimeoutError:
                elapsed += heartbeat_seconds
                _update_job(job_id, message=f"{status_message} ({elapsed}s elapsed)")
                if elapsed >= timeout_seconds:
                    future.cancel()
                    raise RuntimeError(
                        "A chunk request timed out. Try reducing input size or lowering retries."
                    )


def _summarize_with_chunk_progress(
    job_id: str,
    text: str,
    domain: str,
    length: str,
    output_format: str,
    progress_start: int,
    progress_end: int,
):
    chunks = _split_text_into_chunks(text)
    if not chunks:
        raise ValueError("No text available for summarization.")

    chunk_summaries: List[str] = []
    last_engine = ""
    total_chunks = len(chunks)

    if total_chunks == 1:
        _update_job(
            job_id,
            message="Processing chunk 1/1",
            progress=progress_start,
        )
        result = _summarize_with_timeout(
            job_id=job_id,
            text=chunks[0],
            domain=domain,
            length=length,
            output_format=output_format,
            status_message="Processing chunk 1/1",
        )
        _update_job(job_id, progress=progress_end)
        return result

    span = max(1, progress_end - progress_start)
    for index, chunk in enumerate(chunks, start=1):
        progress = progress_start + int((index / total_chunks) * max(1, span - 15))
        _update_job(
            job_id,
            message=f"Processing chunk {index}/{total_chunks}",
            progress=progress,
        )
        # Keep per-chunk passes concise; detailed formatting is applied during final merge.
        chunk_length = "short"
        result = _summarize_with_timeout(
            job_id=job_id,
            text=chunk,
            domain=domain,
            length=chunk_length,
            output_format="paragraph",
            status_message=f"Processing chunk {index}/{total_chunks}",
        )
        chunk_summaries.append(result["summary"])
        last_engine = result["engine"]

    _update_job(job_id, message="Merging chunk summaries", progress=progress_end - 10)
    merged_text = "\n\n".join(chunk_summaries)
    merged_result = _summarize_with_timeout(
        job_id=job_id,
        text=merged_text,
        domain=domain,
        length=length,
        output_format=output_format,
        status_message="Merging chunk summaries",
    )

    if not merged_result.get("engine"):
        merged_result["engine"] = last_engine

    _update_job(job_id, progress=progress_end)
    return merged_result


def _run_summarization_job(
    job_id: str,
    text: str,
    domain: str,
    length: str,
    output_format: str,
    compare_lengths: bool,
):
    try:
        _update_job(job_id, status="running", message="Preparing summarization", progress=5)

        lengths = ["short", "medium", "detailed"] if compare_lengths else [length]
        compare_results: Dict[str, Dict[str, str]] = {}

        for idx, current_length in enumerate(lengths, start=1):
            step_start = int(((idx - 1) / len(lengths)) * 90) + 5
            step_end = int((idx / len(lengths)) * 90) + 5
            _update_job(
                job_id,
                message=f"Generating {current_length} summary ({idx}/{len(lengths)})",
                progress=step_start,
            )
            result = _summarize_with_chunk_progress(
                job_id=job_id,
                text=text,
                domain=domain,
                length=current_length,
                output_format=output_format,
                progress_start=step_start,
                progress_end=step_end,
            )

            if compare_lengths:
                compare_results[current_length] = {
                    "summary": result["summary"],
                    "engine": result["engine"],
                }
            else:
                _update_job(
                    job_id,
                    status="completed",
                    message="Summary ready",
                    progress=100,
                    result={"summary": result["summary"], "engine": result["engine"]},
                )
                return

        _update_job(
            job_id,
            status="completed",
            message="Comparison ready",
            progress=100,
            result={"compare": compare_results},
        )
    except Exception as error:
        _update_job(
            job_id,
            status="failed",
            message="Summarization failed",
            error=str(error),
        )


def _extract_text_from_file(uploaded_file):
    filename = (uploaded_file.filename or "").strip()
    if not filename:
        raise ValueError("No file selected.")

    lower_name = filename.lower()
    extension = os.path.splitext(lower_name)[1]
    if extension not in SUPPORTED_FILE_EXTENSIONS:
        raise ValueError("Unsupported file type. Use PDF, DOCX, or TXT.")

    uploaded_file.stream.seek(0)

    if extension == ".txt":
        return uploaded_file.stream.read().decode("utf-8", errors="ignore").strip()

    if extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(uploaded_file.stream)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        return text.strip()

    from docx import Document

    document = Document(uploaded_file.stream)
    text = "\n".join(p.text for p in document.paragraphs)
    return text.strip()


@app.post("/extract-text")
@limiter.limit(os.getenv("EXTRACT_RATE_LIMIT", "10 per minute"))
def extract_text():
    uploaded_file = request.files.get("file")
    if not uploaded_file:
        return jsonify({"error": "No file provided."}), 400

    try:
        text = _extract_text_from_file(uploaded_file)
        if len(text) < 30:
            return jsonify({"error": "Uploaded file has too little extractable text."}), 400
        return jsonify({"text": text, "filename": uploaded_file.filename}), 200
    except Exception as error:
        return jsonify({"error": str(error)}), 400


@app.post("/summarize")
@limiter.limit(os.getenv("SUMMARIZE_RATE_LIMIT", "10 per minute"))
def summarize():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    domain = (data.get("domain") or "general").strip().lower()
    length = (data.get("length") or "medium").strip().lower()
    output_format = (data.get("format") or "paragraph").strip().lower()

    if len(text) < 30:
        return jsonify({"error": "Please provide at least 30 characters of text."}), 400

    max_chars = int(os.getenv("MAX_INPUT_CHARS", "50000"))
    if len(text) > max_chars:
        return jsonify({"error": f"Input too long. Maximum allowed characters: {max_chars}."}), 400

    if domain not in {"general", "legal", "medical", "finance", "technical"}:
        return jsonify({"error": "Invalid domain selected."}), 400

    if length not in {"short", "medium", "detailed"}:
        return jsonify({"error": "Invalid summary length selected."}), 400

    if output_format not in {"paragraph", "bullet"}:
        return jsonify({"error": "Invalid output format selected."}), 400

    try:
        result = summarize_text(
            text=text,
            domain=domain,
            length=length,
            output_format=output_format,
        )
        return jsonify(result), 200
    except Exception as error:
        return jsonify({"error": str(error)}), 500


@app.post("/summarize-job")
@limiter.limit(os.getenv("SUMMARIZE_JOB_RATE_LIMIT", "10 per minute"))
def summarize_job():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    domain = (data.get("domain") or "general").strip().lower()
    length = (data.get("length") or "medium").strip().lower()
    output_format = (data.get("format") or "paragraph").strip().lower()
    compare_lengths = bool(data.get("compare_lengths"))

    if len(text) < 30:
        return jsonify({"error": "Please provide at least 30 characters of text."}), 400

    max_chars = int(os.getenv("MAX_INPUT_CHARS", "50000"))
    if len(text) > max_chars:
        return jsonify({"error": f"Input too long. Maximum allowed characters: {max_chars}."}), 400

    if domain not in {"general", "legal", "medical", "finance", "technical"}:
        return jsonify({"error": "Invalid domain selected."}), 400

    if length not in {"short", "medium", "detailed"}:
        return jsonify({"error": "Invalid summary length selected."}), 400

    if output_format not in {"paragraph", "bullet"}:
        return jsonify({"error": "Invalid output format selected."}), 400

    job_id = str(uuid.uuid4())
    with JOB_LOCK:
        JOB_STORE[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "message": "Job queued",
            "progress": 0,
        }

    worker = threading.Thread(
        target=_run_summarization_job,
        args=(job_id, text, domain, length, output_format, compare_lengths),
        daemon=True,
    )
    worker.start()

    return jsonify({"job_id": job_id}), 202


@app.get("/summarize-job/<job_id>")
@limiter.limit(os.getenv("SUMMARIZE_STATUS_RATE_LIMIT", "120 per minute"))
def summarize_job_status(job_id: str):
    with JOB_LOCK:
        job = JOB_STORE.get(job_id)

    if not job:
        return jsonify({"error": "Job not found."}), 404

    return jsonify(job), 200


if __name__ == "__main__":
    app.run(debug=True)
