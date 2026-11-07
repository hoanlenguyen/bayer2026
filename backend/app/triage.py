"""Triage tags for incoming requests: urgency and status.

Why rules and not a trained classifier: in SinceAI's Business_Requests sheet the
same request text carries every urgency and both statuses (for example the 22
copies of the Tableau replacement request are 16 normal, 2 high, 4 urgent and
14 new, 8 triaged), and product, market and date do not explain the labels
either. No model can predict them from the text; the best possible accuracy is
the majority guess. See `label_predictability()`.

So the tags mean what they mean in a real intake process:
- **urgency** (normal / high / urgent) is how soon the requester needs it. It is
  *stated* (the user picked it), *inferred* (explicit time words in the request,
  quoted as evidence) or *default* (normal, nothing said).
- **status** (new / triaged) is a workflow state set by the pipeline: new when a
  request arrives, triaged once the intent is clear and a decision is made.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

URGENCY_VALUES = ("normal", "high", "urgent")
STATUS_VALUES = ("new", "triaged")

URGENT_CUES = re.compile(
    r"\b(urgent(ly)?|asap|as soon as possible|immediately|right away|right now|today|tonight|tomorrow|"
    r"end of (the )?day|eod|critical|blocking|escalat\w+|emergency)\b", re.I)
HIGH_CUES = re.compile(
    r"\b(this week|next week|by (mon|tues|wednes|thurs|fri)day|before (the )?(board|leadership|quarterly|monthly|steering) "
    r"(meeting|review|call)|deadline|quarter[- ]end|month[- ]end|high priority|priority|soon|time[- ]sensitive)\b", re.I)

# Answer chips for the grill-me question "When do you need this?"
URGENCY_CHOICES = {
    "Urgent: today or tomorrow": "urgent",
    "High: this week": "high",
    "Normal: no fixed deadline": "normal",
}


def urgency_from_answer(answer: str) -> str | None:
    """Map an answer to the urgency question to a value, if it names one."""
    a = answer.strip().lower()
    for chip, value in URGENCY_CHOICES.items():
        if a == chip.lower():
            return value
    for value in ("urgent", "high", "normal"):
        if re.search(rf"\b{value}\b", a):
            return value
    return None


def infer_urgency(text: str) -> dict[str, Any]:
    """Urgency from explicit time words. Returns value, source and the quoted evidence."""
    for value, pattern in (("urgent", URGENT_CUES), ("high", HIGH_CUES)):
        m = pattern.search(text or "")
        if m:
            return {"value": value, "source": "inferred", "evidence": m.group(0)}
    return {"value": "normal", "source": "default", "evidence": None}


def verify_urgency(proposed: dict[str, Any] | None, transcript_text: str) -> dict[str, Any]:
    """Check a model's urgency claim: a raised urgency must quote words that are really in the request."""
    rules = infer_urgency(transcript_text)
    if not isinstance(proposed, dict) or proposed.get("value") not in URGENCY_VALUES:
        return rules
    value, evidence = proposed["value"], str(proposed.get("evidence") or "").strip()
    if value == "normal":
        return rules if rules["source"] == "inferred" else {"value": "normal", "source": "default", "evidence": None}
    if evidence and evidence.lower() in transcript_text.lower():
        return {"value": value, "source": "inferred", "evidence": evidence}
    return {**rules, "note": f"Model said '{value}' without quoting the request; kept the rule-based result."}


def label_predictability(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """How well the request text could predict the dataset's labels at best (text → most common label)."""
    out: dict[str, Any] = {"rows": len(rows)}
    by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_text[r["request_text"]].append(r)
    for field in ("urgency", "status"):
        overall = Counter(r[field] for r in rows)
        majority = overall.most_common(1)[0][1] / len(rows)
        best_from_text = sum(Counter(r[field] for r in rs).most_common(1)[0][1] for rs in by_text.values()) / len(rows)
        out[field] = {"distribution": dict(overall), "majority_baseline": round(majority, 3),
                      "best_possible_from_text": round(best_from_text, 3),
                      "texts_with_mixed_labels": sum(1 for rs in by_text.values() if len({r[field] for r in rs}) > 1)}
    out["distinct_texts"] = len(by_text)
    return out
