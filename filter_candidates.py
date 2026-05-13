"""Cheap structural and keyword filters for decision-oriented candidates."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from normalize import conversation_to_text


CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z'-]+")

STRONG_DECISION_PATTERNS = [
    r"\bwhat should i do\b",
    r"\bshould i\b",
    r"\bhelp me decide\b",
    r"\bwhich (one|option|would|should)\b",
    r"\bwhat would you do\b",
    r"\bdo you think i should\b",
    r"\bis it worth it\b",
    r"\bwould it be (better|okay|wise)\b",
]

COMPARISON_PATTERNS = [
    r"\bcompare\b",
    r"\bpros and cons\b",
    r"\btrade[- ]?offs?\b",
    r"\bbetter option\b",
    r"\bbest option\b",
    r"\boption a\b",
    r"\boption b\b",
    r"\bbetween .{0,80}\band\b",
]

AGENCY_PATTERNS = [
    r"\btell me what to do\b",
    r"\bchoose for me\b",
    r"\bpick (one|for me)\b",
    r"\bmake (a|the) plan\b",
    r"\bwrite (a|the|my) (reply|response|email|message)\b",
    r"\bhow should i (reply|respond|say|tell|ask)\b",
]

REFLECTION_PATTERNS = [
    r"\bmy priorities\b",
    r"\bmy values\b",
    r"\bdepends on\b",
    r"\bclarify\b",
    r"\bconstraints?\b",
    r"\bgoals?\b",
]

HIGH_STAKES_PATTERNS = [
    r"\bvisa\b",
    r"\bimmigration\b",
    r"\blegal\b",
    r"\blawyer\b",
    r"\bmedical\b",
    r"\bdoctor\b",
    r"\btherapy\b",
    r"\binvest(ment|ing)?\b",
    r"\bjob offer\b",
    r"\bsalary\b",
    r"\brent\b",
    r"\blease\b",
]

LOW_SIGNAL_PATTERNS = [
    r"\bwhat is\b",
    r"\bwho is\b",
    r"\bdefine\b",
    r"\bexplain\b",
    r"\bsummarize\b",
    r"\btranslate\b",
    r"\bwrite code\b",
    r"\bdebug\b",
]


def count_turns(conversation: dict[str, Any], role: str | None = None) -> int:
    if role is None:
        return len(conversation["turns"])
    return sum(1 for turn in conversation["turns"] if turn["role"] == role)


def looks_like_code_only(text: str) -> bool:
    without_code = CODE_BLOCK_RE.sub("", text)
    code_chars = len(text) - len(without_code)
    if len(text) < 200:
        return False
    return code_chars / max(len(text), 1) > 0.65


def english_likeness_score(text: str) -> float:
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return 0.0
    ascii_letters = sum(1 for character in letters if ord(character) < 128)
    return ascii_letters / len(letters)


def is_english_like(text: str, threshold: float = 0.95) -> bool:
    return english_likeness_score(text) >= threshold


def keyword_hits(text: str, keywords: list[str]) -> list[str]:
    lower = text.lower()
    return [keyword for keyword in keywords if keyword in lower]


def regex_hits(text: str, patterns: list[str]) -> list[str]:
    lower = text.lower()
    return [pattern for pattern in patterns if re.search(pattern, lower)]


def decision_signal_score(conversation: dict[str, Any], keyword_hit_count: int) -> tuple[int, dict[str, list[str]]]:
    text = conversation_to_text(conversation)
    strong_hits = regex_hits(text, STRONG_DECISION_PATTERNS)
    comparison_hits = regex_hits(text, COMPARISON_PATTERNS)
    agency_hits = regex_hits(text, AGENCY_PATTERNS)
    reflection_hits = regex_hits(text, REFLECTION_PATTERNS)
    high_stakes_hits = regex_hits(text, HIGH_STAKES_PATTERNS)
    low_signal_hits = regex_hits(text, LOW_SIGNAL_PATTERNS)

    user_turns = count_turns(conversation, "user")
    assistant_turns = count_turns(conversation, "assistant")
    score = 0
    score += min(keyword_hit_count, 5)
    score += 4 * len(strong_hits)
    score += 3 * len(comparison_hits)
    score += 3 * len(agency_hits)
    score += 2 * len(reflection_hits)
    score += 2 * len(high_stakes_hits)
    score += 2 if user_turns >= 3 else 0
    score += 1 if assistant_turns >= 2 else 0
    score -= min(4, len(low_signal_hits))
    score -= 4 if looks_like_code_only(text) else 0

    signals = {
        "strong_decision": strong_hits,
        "comparison": comparison_hits,
        "agency_delegation": agency_hits,
        "reflection": reflection_hits,
        "high_stakes": high_stakes_hits,
        "low_signal": low_signal_hits,
    }
    return max(score, 0), signals


def infer_domain(text: str) -> str:
    lower = text.lower()
    domain_keywords = {
        "career": ["job", "career", "offer", "interview", "salary", "manager", "work"],
        "education": ["school", "college", "university", "phd", "study", "exam", "class"],
        "relationship": ["relationship", "partner", "boyfriend", "girlfriend", "friend", "family"],
        "health": ["medical", "health", "doctor", "therapy", "therapist", "symptom"],
        "finance": ["finance", "investment", "money", "rent", "lease", "loan", "budget"],
        "legal": ["legal", "lawyer", "contract", "court", "sue", "rights"],
        "immigration": ["visa", "immigration", "green card", "citizenship"],
        "communication": ["reply", "respond", "email", "message", "apologize", "negotiate"],
        "planning": ["plan", "schedule", "roadmap", "timeline", "itinerary", "strategy"],
    }
    scores = Counter(
        domain
        for domain, terms in domain_keywords.items()
        for term in terms
        if term in lower
    )
    return scores.most_common(1)[0][0] if scores else "general"


def passes_candidate_filter(
    conversation: dict[str, Any],
    keywords: list[str],
    min_user_turns: int,
    min_total_turns: int,
    min_chars: int,
) -> tuple[bool, dict[str, Any]]:
    text = conversation_to_text(conversation)
    hits = keyword_hits(text, keywords)
    words = WORD_RE.findall(text)
    metadata = {
        "num_turns": count_turns(conversation),
        "num_user_turns": count_turns(conversation, "user"),
        "num_assistant_turns": count_turns(conversation, "assistant"),
        "char_count": len(text),
        "word_count": len(words),
        "keyword_hits": hits,
        "inferred_domain": infer_domain(text),
        "english_likeness_score": round(english_likeness_score(text), 4),
    }
    score, signals = decision_signal_score(conversation, len(hits))
    metadata["decision_signal_score"] = score
    metadata["decision_signal_hits"] = signals

    keep = (
        metadata["num_user_turns"] >= min_user_turns
        and metadata["num_turns"] >= min_total_turns
        and metadata["char_count"] >= min_chars
        and bool(hits)
        and not looks_like_code_only(text)
    )
    return keep, metadata
