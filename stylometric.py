import re
import statistics

MATTR_WINDOW_SIZE = 40
TTR_FULL_CONFIDENCE_WORDS = MATTR_WINDOW_SIZE * 5  # 200 words
BASE_TTR_WEIGHT = 1 / 3


def _split_sentences(text):
    sentences = re.split(r'[.!?]+', text)
    return [s.strip() for s in sentences if s.strip()]


def _matt_ratio(text, window_size=MATTR_WINDOW_SIZE):
    """
    Moving-Average Type-Token Ratio: computes TTR over fixed-size sliding
    windows and averages the results. This corrects for raw TTR's
    sensitivity to text length — raw TTR mathematically decreases as text
    gets longer regardless of actual vocabulary diversity, since longer
    text has more chances to naturally repeat common words. MATTR measures
    every text in consistent fixed-size chunks, making short and long
    submissions comparable on equal footing.
    """
    words = re.findall(r"\b[a-zA-Z']+\b", text.lower())

    if len(words) < window_size:
        if not words:
            return 0.0
        return len(set(words)) / len(words)

    ratios = []
    for i in range(len(words) - window_size + 1):
        window = words[i:i + window_size]
        ratios.append(len(set(window)) / window_size)

    return statistics.mean(ratios)


def _sentence_length_stddev(sentences):
    lengths = [len(s.split()) for s in sentences if s.split()]
    if len(lengths) < 2:
        return None
    return statistics.stdev(lengths)


def _punctuation_variance(sentences):
    """Std dev of punctuation marks per sentence. Low variance = uniform = AI-like."""
    counts = [len(re.findall(r'[,;:\-—()]', s)) for s in sentences]
    if len(counts) < 2:
        return None
    return statistics.stdev(counts)


def _normalize_ttr(ttr):
    """Per planning.md: below 0.4 -> 0.8, above 0.6 -> 0.2, linear between."""
    if ttr <= 0.4:
        return 0.8
    if ttr >= 0.6:
        return 0.2
    return 0.8 + (-3.0) * (ttr - 0.4)


def _normalize_sentence_variance(std):
    """Per planning.md: std < 3 -> 0.7, std > 8 -> 0.2, linear between."""
    if std is None:
        return 0.5
    if std <= 3:
        return 0.7
    if std >= 8:
        return 0.2
    return 0.7 + (-0.1) * (std - 3)


def _normalize_punctuation_variance(std):
    """Per planning.md: std <= 0.5 -> 0.7, std >= 3.0 -> 0.2, linear between."""
    if std is None:
        return 0.5
    if std <= 0.5:
        return 0.7
    if std >= 3.0:
        return 0.2
    return 0.7 + (-0.2) * (std - 0.5)


def _compute_weights(num_words):
    """
    TTR/MATTR is least reliable when text length is close to one window
    size (40 words) and most reliable once there's enough text for several
    windows to average over (200+ words). This scales TTR's weight in the
    final average accordingly, redistributing the difference to the other
    two (length-independent) sub-metrics. At 40 words, TTR contributes
    only a small fraction of the score; at 200+ words, all three sub-scores
    are weighted equally.
    """
    ttr_confidence = min(1.0, num_words / TTR_FULL_CONFIDENCE_WORDS)
    ttr_weight = BASE_TTR_WEIGHT * ttr_confidence
    remaining = 1 - ttr_weight
    other_weight = remaining / 2
    return ttr_weight, other_weight, other_weight


def classify_with_stylometrics(text):
    """
    Signal 1: Stylometric heuristics (pure Python).

    Returns:
        dict: {
            "stylometric_score": float (0.0-1.0),
            "sub_scores": {...},
            "weights_used": {...},
            "raw_metrics": {...},
        }
    """
    sentences = _split_sentences(text)
    words = re.findall(r"\b[a-zA-Z']+\b", text.lower())
    num_words = len(words)

    ttr = _matt_ratio(text)
    sentence_std = _sentence_length_stddev(sentences)
    punct_std = _punctuation_variance(sentences)

    ttr_score = _normalize_ttr(ttr)
    sentence_variance_score = _normalize_sentence_variance(sentence_std)
    punctuation_variance_score = _normalize_punctuation_variance(punct_std)

    ttr_weight, sentence_weight, punct_weight = _compute_weights(num_words)

    stylometric_score = (
        ttr_score * ttr_weight
        + sentence_variance_score * sentence_weight
        + punctuation_variance_score * punct_weight
    )

    return {
        "stylometric_score": round(stylometric_score, 4),
        "sub_scores": {
            "ttr_score": round(ttr_score, 4),
            "sentence_variance_score": round(sentence_variance_score, 4),
            "punctuation_variance_score": round(punctuation_variance_score, 4),
        },
        "weights_used": {
            "ttr_weight": round(ttr_weight, 4),
            "sentence_weight": round(sentence_weight, 4),
            "punctuation_weight": round(punct_weight, 4),
        },
        "raw_metrics": {
            "type_token_ratio": round(ttr, 4),
            "sentence_length_stddev": round(sentence_std, 4) if sentence_std is not None else None,
            "punctuation_stddev": round(punct_std, 4) if punct_std is not None else None,
        },
    }