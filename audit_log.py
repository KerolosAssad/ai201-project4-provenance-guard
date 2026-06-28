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


def get_log(limit=20):
    """Return the most recent `limit` entries, newest first."""
    entries = _read_log()
    return entries[-limit:][::-1]