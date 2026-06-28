# Provenance Guard

A backend system that classifies submitted text as likely AI-generated, likely human-written, or uncertain — using two independent detection signals, a calibrated confidence score, a plain-language transparency label, and an appeals workflow for contested classifications.

## Architecture

Full architecture diagrams (submission flow and appeal flow) and detailed design decisions live in [`planning.md`](./planning.md). Summary: a submission passes through input validation, then two independent detection signals, then a confidence scorer that combines them, then a label generator, then gets written to a structured audit log before the response is returned.

## Detection Signals

This system uses two genuinely independent signals, per the project requirement that signals capture different properties of the text (not two versions of the same approach):

**Signal 1 — Stylometric heuristics (pure Python).** Measures structural/statistical properties: vocabulary diversity (via MATTR — Moving-Average Type-Token Ratio), sentence length variance, and punctuation variance. The underlying assumption is that AI-generated text tends to be more statistically uniform, while human writing is more variable. **Blind spot:** this signal struggles on short text (near the 40-word minimum), where there isn't enough data for these statistics to be reliable — see Known Limitations below for a concrete example.

**Signal 2 — LLM-based classification (Groq, llama-3.3-70b-versatile).** Measures holistic semantic and stylistic coherence — whether the passage *reads* as AI- or human-written overall, the way a human reader might judge it. **Blind spot:** it's a black box — there's no way to point to exactly why it reached a judgment, and it can be fooled by lightly-edited AI text or by very generic, formulaic human writing.

These two signals were chosen specifically because they're independent in kind (one semantic/holistic, one structural/statistical), which means they can genuinely disagree — and that disagreement is itself useful information (see Confidence Scoring below).

## Confidence Scoring

Both signals return a 0–1 score. Naive averaging was rejected because it hides disagreement between signals — exactly the case that can produce a dangerous false positive (labeling human writing as AI). Instead:

```
diff = abs(llm_score - stylometric_score)
base_score = (llm_score + stylometric_score) / 2
agreement_weight_factor = 1.0 if diff <= 0.3 else 0.6
combined_score = (agreement_weight_factor * base_score) + ((1 - agreement_weight_factor) * 0.5)
```

When the two signals agree closely (diff ≤ 0.3), the combined score is just their average. When they diverge significantly, the result is blended toward 0.5 (genuine uncertainty) rather than toward either extreme.

**Thresholds:**

| Combined score | Attribution |
|---|---|
| 0.00 – 0.34 | likely_human |
| 0.35 – 0.65 | uncertain |
| 0.66 – 1.00 | likely_ai |

**Two real examples from testing, showing meaningfully different scores:**

1. *Casual, rambling human text:*
   > "so i tried cooking dinner tonight and it was honestly a disaster from start to finish. like i burned the garlic right away because i got distracted scrolling my phone, and then i forgot to season anything until it was basically already done cooking which defeats the whole purpose. my roommate walked in halfway through and just looked at the smoke alarm going off and didnt even say anything, just turned around and left. we ended up ordering pizza instead lol, classic friday night honestly"

   → `llm_score: 0.2`, `stylometric_score: 0.41`, **combined: 0.3073** → `likely_human`

2. *Generic, formulaic AI-style text:*
   > "In conclusion, it is important to note that effective communication requires careful consideration of multiple factors. Furthermore, it is essential to recognize that successful outcomes depend on thorough planning. Additionally, stakeholders must collaborate to ensure comprehensive understanding. Moreover, it is crucial to acknowledge that ongoing evaluation remains necessary for continued improvement and success."

   → `llm_score: 0.8`, `stylometric_score: 0.62`, **combined: 0.7103** → `likely_ai`

**Confidence magnitude also varies meaningfully, independent of direction** — comparing a higher-confidence and a lower-confidence result directly:

- *Higher-confidence case* (the generic AI-style text above): `combined: 0.7103` — a fairly decisive result, above the 0.66 threshold.
- *Lower-confidence case:*
  > "The sun dipped below the horizon, painting the sky in hues of amber and rose. I sat on the porch, coffee in hand, watching the neighborhood slowly go quiet. It was the kind of evening that made you forget your phone existed for a while, just watching the colors shift overhead."

  → `llm_score: 0.4`, `stylometric_score: 0.59`, **combined: 0.4942** — landing almost exactly at the center of the 0–1 scale, about as uncertain as a score can get, correctly producing the "uncertain" label rather than a falsely decisive one.

This confirms the scoring system isn't producing a near-constant value — it spans from a clearly decisive 0.71 down to a nearly maximally uncertain 0.49 depending on how much the two signals actually agree, which is the behavior the design specifically targets.

**How scoring was validated:** four deliberately chosen test inputs were run through the live endpoint — a clearly AI-generated passage, a clearly human-written passage, and two borderline cases (formal human writing, lightly-edited AI output). The combined scores varied meaningfully across these inputs (ranging from 0.31 to 0.71 across all tests run), and both signals' individual scores were inspected on every test to confirm why the combined score landed where it did, rather than treating the formula as a black box.

One specific finding from this testing: the textbook "clearly AI-generated" paragraph used as a test input —

> "Artificial intelligence represents a transformative paradigm shift in modern society. It is important to note that while the benefits of AI are numerous, it is equally essential to consider the ethical implications. Furthermore, stakeholders across various sectors must collaborate to ensure responsible deployment."

— scored only 0.5936 (landing in "uncertain," not "likely_ai") — because while the LLM signal confidently flagged it as AI (0.70), the stylometric signal disagreed (0.49), since this passage happened to have high vocabulary diversity and sentence-length variance, which the heuristic reads as human-like. This is the agreement-weighted formula working as designed: when signals genuinely disagree, the system reports uncertainty rather than picking a side.

## Transparency Label

The three label variants, written exactly as they're returned by the API:

- **High-confidence AI:**
  > "This content is very likely AI-generated. Our system identified strong AI-style patterns with high confidence."

- **High-confidence human:**
  > "This content appears to be written by a human. Our system found no significant signs of AI generation."

- **Uncertain:**
  > "We can't confidently determine whether this content was written by a human or AI. If you believe this result is incorrect, you can appeal below."

All three avoid technical jargon (no raw scores or signal names) and were tested live through the `/submit` endpoint to confirm each is reachable at the appropriate confidence range — not just verified as a standalone function.

## Appeals Workflow

`POST /appeal` accepts `content_id` and `creator_reasoning`. It validates that the `content_id` exists, then updates that submission's status to `"under_review"` and attaches the appeal (reasoning, timestamp, and the original label/confidence score) to the same audit log entry — preserving the original decision rather than overwriting it. No automated re-classification is triggered.

**Example request:**
```bash
curl -s -X POST http://localhost:5050/appeal \
  -H "Content-Type: application/json" \
  -d '{"content_id": "9d99528a-4df5-44b1-b67a-51b0469ec958", "creator_reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical."}'
```

**Response:**
```json
{
  "appeal_received": true,
  "content_id": "9d99528a-4df5-44b1-b67a-51b0469ec958",
  "status": "under_review"
}
```

**Resulting audit log entry** (showing the appeal alongside the original decision):
```json
{
  "content_id": "9d99528a-4df5-44b1-b67a-51b0469ec958",
  "creator_id": "test-appeal",
  "timestamp": "2026-06-28T07:33:03.476487+00:00",
  "attribution": "uncertain",
  "confidence": 0.4942,
  "llm_score": 0.4,
  "stylometric_score": 0.5883,
  "label": "We can't confidently determine whether this content was written by a human or AI. If you believe this result is incorrect, you can appeal below.",
  "status": "under_review",
  "appeal": {
    "reasoning": "I wrote this myself from personal experience. I am a non-native English speaker and my writing style may appear more formal than typical.",
    "timestamp": "2026-06-28T07:34:27.201557+00:00",
    "original_label": "We can't confidently determine whether this content was written by a human or AI. If you believe this result is incorrect, you can appeal below.",
    "original_confidence_score": 0.4942
  }
}
```

**Design note:** the appeal reasoning is stored as a nested object (`appeal.reasoning`) rather than a flat `appeal_reasoning` field, to keep all appeal-related metadata (reasoning, timestamp, original decision) grouped together in one place rather than scattered across top-level fields.

## Rate Limiting

Both `POST /submit` and `POST /appeal` are rate-limited with **Flask-Limiter**, using two tiers:

- **Per-IP:** `/submit` allows 10 per minute, 100 per day — sized for a realistic writer iterating on a single piece (submitting, reading the result, revising, resubmitting a few times in one sitting), while still blocking a single source from flooding the endpoint. `/appeal` allows a tighter 5 per minute, 20 per day, since legitimate appeal volume per person should be much lower than submission volume — appealing is occasional, not part of routine iteration. `/appeal` is also cheaper per-request than `/submit` (no Groq call, no stylometric computation), which makes it an easier target to flood if left unprotected.
- **Global (across all requests, all routes):** 100 per minute, 1000 per day — protects the shared Groq API quota/cost from being exhausted by many legitimate users submitting around the same time (e.g., a class of students all testing near a deadline), independent of any single IP's behavior.

**Evidence of `/submit` rate limiting** — 12 rapid requests, exceeding the 10/minute per-IP limit:
```
200
200
200
200
200
200
200
200
200
200
429
429
```

**Evidence of `/appeal` rate limiting** — 7 rapid requests, exceeding the 5/minute per-IP limit:
```
200
200
200
200
200
429
429
```

Both endpoints correctly allow requests up to their configured limit, then reject excess requests with `429 Too Many Requests`. Testing also confirmed the limiter counts every request against the budget regardless of whether the request is otherwise valid — a batch of requests with an invalid `content_id` (which returned `400`) still consumed the rate limit budget, meaning the limiter protects against flooding *before* any business logic runs, not after.

## Audit Log

Every submission and appeal is written to a structured JSON log (`audit_log.json`), capturing: timestamp, content ID, creator ID, attribution result, combined confidence score, both individual signal scores (with stylometric sub-scores broken out), the label shown, current status, and appeal details if filed. Accessible via `GET /log`.

**Sample entries** (3 of 22+ generated during testing):

```json
{
  "content_id": "0a2ad6a8-1d90-449e-b34c-4b034982efa5",
  "creator_id": "test-extreme-ai",
  "timestamp": "2026-06-28T07:38:34.155868+00:00",
  "attribution": "likely_ai",
  "confidence": 0.7103,
  "llm_score": 0.8,
  "stylometric_score": 0.6205,
  "label": "This content is very likely AI-generated. Our system identified strong AI-style patterns with high confidence.",
  "status": "classified",
  "appeal": null
}
```

```json
{
  "content_id": "dd37c1b0-adda-447d-90f7-cc044cf67b01",
  "creator_id": "test-extreme-human-2",
  "timestamp": "2026-06-28T07:40:35.158400+00:00",
  "attribution": "likely_human",
  "confidence": 0.3073,
  "llm_score": 0.2,
  "stylometric_score": 0.4146,
  "label": "This content appears to be written by a human. Our system found no significant signs of AI generation.",
  "status": "classified",
  "appeal": null
}
```

(See the Appeals Workflow section above for a full appeal entry example.)

## Known Limitations

**Vocabulary-diversity scoring is unreliable on short text near the validation floor.** During Milestone 4 testing, two test passages of similar length (a "clearly AI" and a "clearly human" example, both under 60 words) produced nearly identical raw type-token ratio scores (0.875 and 0.873), because raw TTR is mathematically sensitive to text length, not just actual vocabulary diversity — short texts naturally have less chance to repeat words regardless of who wrote them. This was partially mitigated by switching to MATTR (a windowed version of TTR) with confidence-weighted averaging (see `planning.md` Section 1), which reduces but does not eliminate the issue — the system still gives this sub-signal very little weight (roughly 7%) for submissions near the 40-word minimum, deliberately leaning on the other two stylometric sub-metrics and the LLM signal instead.

**Short, punchy, informal writing can be misread as structurally AI-like.** A deliberately casual test submission (full of slang, very short consistent sentences) scored unexpectedly *high* on the stylometric signal's sentence-variance sub-metric (0.7 — strongly AI-leaning), because its short sentences happened to be fairly uniform in length, which the heuristic associates with AI generation. The LLM signal correctly read this text as human, and the disagreement between the two signals correctly pulled the combined result toward "uncertain" rather than a confident (and wrong) "likely_ai" — but it illustrates a genuine blind spot in the stylometric signal specifically.

## Spec Reflection

**How the spec helped:** writing out the exact confidence-scoring formula and threshold table in `planning.md` *before* writing any code caught a real bug early — the originally-planned formula (`combined_score = base_score * agreement_weight_factor`) was tested against the documented thresholds and found to silently misclassify strongly-disagreeing signals as "high-confidence human" instead of "uncertain," because multiplying shrinks scores toward 0 rather than toward the center. Having concrete thresholds written down in advance made this bug immediately checkable, rather than something that would have been discovered much later by accident.

**Where implementation diverged from the plan:** the original plan specified raw type-token ratio as part of the stylometric signal. Empirical testing during Milestone 4 (see Known Limitations) revealed raw TTR's length-sensitivity problem, which wasn't anticipated during planning. The implementation diverged by switching to MATTR with confidence-weighted averaging — a correction made *because* of hands-on testing against real text, not something that could have been predicted from the spec alone.

## AI Usage

**Instance 1 — Rate limiting design.** I proposed a two-tier rate-limiting structure: a per-user limit generous enough for a writer iterating on revisions, plus a separate global limit protecting the shared Groq API quota from being exhausted by many legitimate users at once. When I directed an AI tool to implement this, it pointed out a flaw in my original framing: Flask-Limiter keys by IP by default, and a per-`creator_id` limit would be trivially bypassed, since `creator_id` is a self-reported field with no real authentication behind it. I decided to keep my original two-tier structure but changed the per-user tier to per-IP instead, since IP is harder to spoof in this project's unauthenticated context — preserving the design intent (protect against a single source flooding the endpoint) while fixing the implementation gap.

**Instance 2 — Confidence-weighted averaging for the stylometric signal.** After an AI tool initially implemented a type-token-ratio-based vocabulary diversity sub-metric (per `planning.md`), I ran standalone tests on two short test passages (a "clearly AI" and "clearly human" example, both under 60 words) and found they scored almost identically (0.875 vs. 0.873) regardless of actual content — meaning the sub-metric was contributing noise, not signal, at that length. The AI tool's first fix was MATTR (a windowed moving-average TTR), which corrects raw TTR's sensitivity to text length, but standalone re-testing after that fix still showed only a small improvement (0.4062 → 0.4872 and 0.3828 → 0.4490 for the same two passages) — the underlying problem of too little text to compute a reliable window average wasn't fully solved by windowing alone. I proposed scaling the sub-metric's weight in the final average based on how much text was actually available, rather than treating all three stylometric sub-scores as equally trustworthy regardless of length. The AI tool implemented this as a confidence-weighting formula (`ttr_weight = (1/3) * min(1.0, num_words / 200)`), and I verified it directly by re-running the standalone tests and confirming the weight values shrank to roughly 7-9% at the 40-word validation floor, as intended, while remaining at the full 1/3 weight for longer submissions.

**Instance 3 — Identifying a missing rate limit on `/appeal`.** While reviewing the completed rate-limiting implementation, which only covered `POST /submit`, I asked whether `/appeal` should also be rate-limited. I directed an AI tool to add equivalent protection. In that same conversation, I also asked whether the limit should be scoped to a specific `content_id` rather than per-IP/global — since someone could spread appeals across multiple IPs or pace them under the per-minute ceiling to specifically target one piece of content rather than flood the server generally. The AI tool explained that implementing this would require custom key-extraction logic (Flask-Limiter's built-in key functions are address/header-based, not body-field-based) and recommended documenting it as a known gap rather than building it for this project's scope. I agreed with that scoping decision and had it added to the README's "What I'd Change for a Real Deployment" section instead of implementing it now.

## What I'd Change for a Real Deployment

This implementation was built for a class project's scope, and a few things would need to change before this could run on a real creative-sharing platform:

- **Persistent, concurrent-safe storage.** The audit log is currently a single JSON file, rewritten in full on every entry — fine for testing, but it wouldn't scale past light traffic or handle concurrent writes safely. A real deployment needs a proper database (e.g., SQLite was already in scope for the audit log; Postgres for anything with real concurrent load).
- **Real authentication.** `creator_id` is currently just a self-reported string with no verification — anyone can submit or appeal under any identity. Production would need actual accounts, both to make rate limiting meaningfully tied to a person rather than an IP, and so appeals are tied to a verified creator rather than an unverifiable claim.
- **A third detection signal, or a different ensemble approach.** During testing, a meaningful fraction of submissions — including a textbook "clearly AI" example — landed in "uncertain" because the two signals disagreed. That's honest behavior, not a bug, but a real platform would likely want to reduce how often legitimate content lands in limbo, which would mean adding a third, genuinely different signal (e.g., comparing against a creator's writing history) rather than relying on just two.
- **An actual moderation workflow for appeals.** Right now an appeal just flips a status flag with no real reviewer interface, queue, or SLA. A production appeals system would need a real dashboard for human reviewers and a defined process for resolving (not just flagging) contested cases.
- **Per-content rate limiting, not just per-IP/global.** Current rate limits protect the server from being flooded, but don't prevent one specific piece of content from being targeted with repeated appeals spread across a longer time window or multiple IPs. A real deployment might add a limit keyed by `content_id` (e.g., no more than N appeals per piece of content within a time window) to prevent harassment of a specific creator's submission, separate from general server-flooding protection.
- **Cost and latency planning at scale.** Groq's free tier and a general-purpose prompted LLM are fine for a class project, but a platform with real submission volume would need to evaluate per-request cost, latency under load, and possibly a smaller fine-tuned model dedicated to this specific classification task rather than a general LLM.

## Stretch Feature: Analytics Dashboard

`GET /analytics` aggregates over the full audit log to surface three metrics, with no changes to the detection pipeline itself: detection pattern (the distribution of attribution results), appeal rate, and average signal disagreement (the average `|llm_score - stylometric_score|` across all submissions) — chosen because it's diagnostic of the system's own core design decision (signal disagreement → uncertainty), giving a single number that summarizes how often the two signals actually disagree in practice.

**Live output from testing** (22 accumulated submissions):
```json
{
    "appeal_rate": 9.1,
    "average_signal_disagreement": 0.2571,
    "detection_pattern": {
        "likely_ai": {
            "count": 1,
            "percentage": 4.5
        },
        "likely_human": {
            "count": 4,
            "percentage": 18.2
        },
        "uncertain": {
            "count": 16,
            "percentage": 72.7
        }
    },
    "total_submissions": 22
}
```

**What this reveals:** 72.7% of all test submissions landed in "uncertain" — far more than "likely_ai" or "likely_human" combined. This is honest behavior given the design (the system reports uncertainty rather than forcing a confident answer when signals disagree), but it's also concrete evidence for a real limitation: a two-signal system that disagrees this often would frustrate real users in production, reinforcing the "What I'd Change for a Real Deployment" point about needing a third signal to reduce how frequently legitimate content lands in limbo. The dashboard turned an assumption ("the signals probably disagree sometimes") into a measured fact (nearly three-quarters of the time, in this test set).

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the repo root:
```
GROQ_API_KEY=your_key_here
```

Run the app:
```bash
python app.py
```

The server runs on `http://localhost:5050` (port 5050 is used instead of Flask's default 5000, which conflicts with macOS AirPlay Receiver).