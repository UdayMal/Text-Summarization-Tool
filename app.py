from flask import Flask, jsonify, render_template, request

from summarizer import summarize_text


app = Flask(__name__)


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/summarize")
def summarize():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    domain = (data.get("domain") or "general").strip().lower()
    length = (data.get("length") or "medium").strip().lower()
    output_format = (data.get("format") or "paragraph").strip().lower()

    if len(text) < 30:
        return jsonify({"error": "Please provide at least 30 characters of text."}), 400

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


if __name__ == "__main__":
    app.run(debug=True)
