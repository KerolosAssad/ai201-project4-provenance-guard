import json
import os
from datetime import datetime, timezone

LOG_FILE = "audit_log.json"
MAX_LOG_ENTRIES = 500  # keeps the log file from growing unbounded over time


def _read_log():
    """Load the log file, returning an empty list if it doesn't exist or is corrupt."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupt or unreadable log shouldn't crash the app — start fresh in memory.
        return []


def _write_log(entries):
    # Trim to the most recent MAX_LOG_ENTRIES before writing, so the file
    # doesn't grow indefinitely and every write doesn't get progressively slower.
    if len(entries) > MAX_LOG_ENTRIES:
        entries = entries[-MAX_LOG_ENTRIES:]

    try:
        with open(LOG_FILE, "w") as f:
            json.dump(entries, f, indent=2)
    except OSError as e:
        # Logging failures shouldn't crash the request; surface to console instead.
        print(f"Warning: failed to write audit log: {e}")


def log_submission(
    content_id,
    creator_id,
    attribution,
    llm_score,
    llm_reasoning,
    stylometric_score,
    stylometric_sub_scores,
    combined_score,
    label,
    llm_error=None,
):
    """
    Append a structured audit entry for a new submission.
    Both signals' individual scores and the combined score/label are now
    fully populated (placeholders from M3 are resolved as of M4/M5).
    """
    entries = _read_log()
    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "llm_score": llm_score,
        "llm_reasoning": llm_reasoning,
        "llm_error": llm_error,
        "stylometric_score": stylometric_score,
        "stylometric_sub_scores": stylometric_sub_scores,
        "confidence": combined_score,
        "label": label,
        "status": "classified",
        "appeal": None,
    }
    entries.append(entry)
    _write_log(entries)
    return entry


def find_entry_by_content_id(content_id):
    """Returns the entry dict matching content_id, or None if not found."""
    entries = _read_log()
    for entry in entries:
        if entry.get("content_id") == content_id:
            return entry
    return None


def submit_appeal(content_id, creator_reasoning):
    """
    Updates the matching entry's status to 'under_review' and attaches the
    appeal reasoning, per planning.md Section 4's appeals workflow.

    Returns the updated entry on success, or None if content_id was not found
    (caller is responsible for treating this as an invalid/unknown content_id).
    """
    entries = _read_log()
    for entry in entries:
        if entry.get("content_id") == content_id:
            entry["status"] = "under_review"
            entry["appeal"] = {
                "reasoning": creator_reasoning,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "original_label": entry.get("label"),
                "original_confidence_score": entry.get("confidence"),
            }
            _write_log(entries)
            return entry
    return None


def get_log(limit=20):
    """Return the most recent `limit` entries, newest first."""
    entries = _read_log()
    return entries[-limit:][::-1]


def get_analytics():
    """
    Aggregates over the full audit log to compute three metrics for the
    stretch-feature analytics dashboard: detection pattern distribution,
    appeal rate, and average signal disagreement.
    """
    entries = _read_log()
    total = len(entries)

    if total == 0:
        return {
            "total_submissions": 0,
            "detection_pattern": {},
            "appeal_rate": 0.0,
            "average_signal_disagreement": None,
        }

    attribution_counts = {"likely_ai": 0, "likely_human": 0, "uncertain": 0}
    appeal_count = 0
    disagreement_sum = 0.0
    disagreement_count = 0

    for entry in entries:
        attribution = entry.get("attribution")
        if attribution in attribution_counts:
            attribution_counts[attribution] += 1

        if entry.get("appeal") is not None:
            appeal_count += 1

        llm_score = entry.get("llm_score")
        stylometric_score = entry.get("stylometric_score")
        if llm_score is not None and stylometric_score is not None:
            disagreement_sum += abs(llm_score - stylometric_score)
            disagreement_count += 1

    detection_pattern = {
        key: {
            "count": count,
            "percentage": round((count / total) * 100, 1),
        }
        for key, count in attribution_counts.items()
    }

    average_disagreement = (
        round(disagreement_sum / disagreement_count, 4)
        if disagreement_count > 0
        else None
    )

    return {
        "total_submissions": total,
        "detection_pattern": detection_pattern,
        "appeal_rate": round((appeal_count / total) * 100, 1),
        "average_signal_disagreement": average_disagreement,
    }