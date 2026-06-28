import uuid
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from signals import classify_with_llm
from stylometric import classify_with_stylometrics
from confidence_scorer import compute_confidence
from labels import generate_label
from audit_log import log_submission, get_log, find_entry_by_content_id, submit_appeal, get_analytics

app = Flask(__name__)

# Global limit applies across all requests regardless of IP, protecting the
# shared Groq API quota from being exhausted by many legitimate users at
# once (e.g. a class of students submitting near a deadline). The per-route
# limit below is applied on top of this and protects against a single
# source (one IP) flooding the endpoint.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per minute", "1000 per day"],
    storage_uri="memory://",
)

MIN_WORDS = 40
MAX_WORDS = 2000


def validate_text(text):
    """
    Input validation per planning.md Architecture > Input Validation.
    Returns an error message string if invalid, or None if valid.
    """
    if not isinstance(text, str) or not text.strip():
        return "Text field must be a non-empty string."

    word_count = len(text.split())
    if word_count < MIN_WORDS:
        return f"Text must be at least {MIN_WORDS} words."
    if word_count > MAX_WORDS:
        return f"Text must not exceed {MAX_WORDS} words."

    return None


def get_attribution(combined_score):
    """
    Maps the combined confidence score to one of three attribution
    categories per planning.md Section 2's threshold table.
    """
    if combined_score <= 0.34:
        return "likely_human"
    if combined_score <= 0.65:
        return "uncertain"
    return "likely_ai"


def validate_appeal(content_id, reasoning):
    """
    Input validation for POST /appeal, per planning.md Section 4.
    Returns an error message string if invalid, or None if valid.
    """
    if not isinstance(content_id, str) or not content_id.strip():
        return "content_id is required."

    if not isinstance(reasoning, str) or not reasoning.strip():
        return "creator_reasoning must be a non-empty string."

    if find_entry_by_content_id(content_id) is None:
        return "content_id not found."

    return None


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    error = validate_text(text)
    if error:
        return jsonify({"error": error}), 400

    content_id = str(uuid.uuid4())

    # Signal 1 runs first (cheap, no network call), then Signal 2.
    stylometric_result = classify_with_stylometrics(text)
    llm_result = classify_with_llm(text)

    confidence_result = compute_confidence(
        llm_score=llm_result["ai_probability"],
        stylometric_score=stylometric_result["stylometric_score"],
    )
    combined_score = confidence_result["combined_score"]

    attribution = get_attribution(combined_score)
    label = generate_label(combined_score)

    log_submission(
        content_id=content_id,
        creator_id=creator_id,
        attribution=attribution,
        llm_score=llm_result["ai_probability"],
        llm_reasoning=llm_result["reasoning"],
        stylometric_score=stylometric_result["stylometric_score"],
        stylometric_sub_scores=stylometric_result["sub_scores"],
        combined_score=combined_score,
        label=label,
        llm_error=llm_result["error"],
    )

    return jsonify({
        "content_id": content_id,
        "creator_id": creator_id,
        "attribution": attribution,
        "confidence": combined_score,
        "label": label,
        "llm_score": llm_result["ai_probability"],
        "llm_reasoning": llm_result["reasoning"],
        "llm_error": llm_result["error"],
        "stylometric_score": stylometric_result["stylometric_score"],
        "stylometric_sub_scores": stylometric_result["sub_scores"],
        "signal_agreement_diff": confidence_result["diff"],
    }), 200


@app.route("/appeal", methods=["POST"])
@limiter.limit("5 per minute;20 per day")
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    error = validate_appeal(content_id, creator_reasoning)
    if error:
        return jsonify({"error": error}), 400

    updated_entry = submit_appeal(content_id, creator_reasoning)

    return jsonify({
        "content_id": content_id,
        "status": updated_entry["status"],
        "appeal_received": True,
    }), 200


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": get_log()}), 200


@app.route("/analytics", methods=["GET"])
def analytics():
    return jsonify(get_analytics()), 200


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """
    Global safety net for any exception not already caught by the
    per-signal/per-route error handling above. Ensures the client always
    receives a clean JSON error instead of a raw traceback.
    """
    return jsonify({"error": "An unexpected server error occurred. Please try again."}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5050)