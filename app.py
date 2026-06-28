import uuid
from flask import Flask, request, jsonify

from signals import classify_with_llm
from stylometric import classify_with_stylometrics
from confidence_scorer import compute_confidence
from audit_log import log_submission, get_log

app = Flask(__name__)

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


@app.route("/submit", methods=["POST"])
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

    # M5 will replace this with the real label-generation function.
    label = "Placeholder — real label logic added in M5"

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


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": get_log()}), 200


if __name__ == "__main__":
    app.run(debug=True, port=5050)