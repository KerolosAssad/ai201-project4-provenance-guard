AGREEMENT_DIFF_THRESHOLD = 0.3
AGREEMENT_FACTOR_AGREE = 1.0
AGREEMENT_FACTOR_DISAGREE = 0.6
CENTER = 0.5


def compute_confidence(llm_score, stylometric_score):
    """
    Combines Signal 1 (stylometric) and Signal 2 (LLM) scores into a single
    confidence score, per planning.md Section 1.

    Naive averaging is rejected on purpose: it hides disagreement between
    signals. When signals diverge significantly, the result is blended
    toward 0.5 (genuine uncertainty) rather than multiplied — multiplying
    shrinks disagreeing scores toward 0, which can silently misclassify a
    disagreement as "high-confidence human."

    Returns:
        dict: {
            "combined_score": float (0.0-1.0),
            "diff": float,
            "agreement_weight_factor": float,
        }
    """
    diff = abs(llm_score - stylometric_score)
    base_score = (llm_score + stylometric_score) / 2

    agreement_weight_factor = (
        AGREEMENT_FACTOR_AGREE if diff <= AGREEMENT_DIFF_THRESHOLD else AGREEMENT_FACTOR_DISAGREE
    )

    combined_score = (agreement_weight_factor * base_score) + (
        (1 - agreement_weight_factor) * CENTER
    )

    combined_score = max(0.0, min(1.0, combined_score))

    return {
        "combined_score": round(combined_score, 4),
        "diff": round(diff, 4),
        "agreement_weight_factor": agreement_weight_factor,
    }