LABEL_HIGH_CONFIDENCE_HUMAN = (
    "This content appears to be written by a human. Our system found no "
    "significant signs of AI generation."
)

LABEL_UNCERTAIN = (
    "We can't confidently determine whether this content was written by a "
    "human or AI. If you believe this result is incorrect, you can appeal below."
)

LABEL_HIGH_CONFIDENCE_AI = (
    "This content is very likely AI-generated. Our system identified strong "
    "AI-style patterns with high confidence."
)


def generate_label(combined_score):
    """
    Maps a combined confidence score to the correct transparency label text,
    per planning.md Section 2's thresholds and Section 3's exact label text.

    Thresholds (per planning.md Section 2):
        0.00 - 0.34 -> high-confidence human
        0.35 - 0.65 -> uncertain
        0.66 - 1.00 -> high-confidence AI
    """
    if combined_score <= 0.34:
        return LABEL_HIGH_CONFIDENCE_HUMAN
    if combined_score <= 0.65:
        return LABEL_UNCERTAIN
    return LABEL_HIGH_CONFIDENCE_AI