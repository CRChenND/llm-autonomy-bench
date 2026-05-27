"""Export candidate and screened autonomy seed-case data."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from normalize import conversation_to_text


SENSITIVE_TERMS = [
    "suicide",
    "self harm",
    "self-harm",
    "abuse",
    "assault",
    "rape",
    "medical diagnosis",
    "immigration status",
    "visa denied",
    "bankruptcy",
]

BEHAVIOR_ALIASES = {
    "preference construction": "preference_construction",
    "preference_construction": "preference_construction",
    "epistemic reliance": "epistemic_reliance",
    "epistemic_reliance": "epistemic_reliance",
    "agency delegation": "agency_delegation",
    "agency_delegation": "agency_delegation",
    "delegation": "agency_delegation",
    "delegation of agency": "agency_delegation",
    "delegation_of_agency": "agency_delegation",
    "reflection support": "reflection_support",
    "reflection_support": "reflection_support",
    "reflection suppression": "reflection_suppression",
    "reflection_suppression": "reflection_suppression",
    "autonomy degradation risk": "autonomy_degradation_risk",
    "autonomy_degradation_risk": "autonomy_degradation_risk",
    "autonomy vulnerability": "autonomy_degradation_risk",
    "next action shaping": "next_action_shaping",
    "next_action_shaping": "next_action_shaping",
    "risk assessment": "risk_assessment",
    "option generation": "option_generation",
    "reflection decline": "reflection_decline",
    "choice awareness decline": "choice_awareness_decline",
    "verification decline": "verification_decline",
    "ownership decline": "ownership_decline",
    "delegation increase": "delegation_increase",
    "acceptance after pressure": "acceptance_after_pressure",
    "delegated decision making": "delegated_decision_making",
    "goal drift": "goal_drift",
    "preference compression": "preference_compression",
    "reduced critical evaluation": "reduced_critical_evaluation",
    "authority internalization": "authority_internalization",
    "learned helplessness": "learned_helplessness_dependency",
    "dependency": "learned_helplessness_dependency",
    "optimization capture": "optimization_capture",
    "cognitive offloading spiral": "cognitive_offloading_spiral",
}


def ensure_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                yield json.loads(line)


def representative_excerpt(conversation: dict[str, Any], max_chars: int) -> str:
    text = conversation_to_text(conversation)
    return text[:max_chars].strip()


def contains_sensitive_details(conversation: dict[str, Any]) -> bool:
    text = conversation_to_text(conversation).lower()
    return any(term in text for term in SENSITIVE_TERMS)


def normalize_label(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(text).strip().lower()).strip()
    return normalized


def normalize_behavior(label: str) -> str:
    normalized = normalize_label(label)
    underscored = normalized.replace(" ", "_")
    return BEHAVIOR_ALIASES.get(normalized) or BEHAVIOR_ALIASES.get(underscored) or underscored


def normalize_behaviors(behaviors: list[Any]) -> list[str]:
    seen = set()
    normalized_behaviors = []
    for behavior in behaviors:
        normalized = normalize_behavior(str(behavior))
        if normalized and normalized not in seen:
            seen.add(normalized)
            normalized_behaviors.append(normalized)
    return normalized_behaviors


def normalize_domain(domain: str) -> str:
    normalized = normalize_label(domain).replace(" ", "_")
    aliases = {
        "education_career": "education_career",
        "career_planning": "career",
        "employment_career": "career",
        "higher_education_applications": "education",
        "higher_education": "education",
        "personal_finance_tax_planning": "finance",
        "personal_finance": "finance",
        "health_medical": "health",
        "employment_contract_job_change": "employment",
    }
    return aliases.get(normalized, normalized)


def build_case_record(
    candidate: dict[str, Any],
    screening: dict[str, Any],
    representative_excerpt_chars: int,
) -> dict[str, Any]:
    conversation = candidate["conversation"]
    source_slug = conversation["source"].lower().replace(" ", "_")
    case_id = f"{source_slug}_{conversation['conversation_id']}"
    return {
        "case_id": case_id,
        "source": conversation["source"],
        "conversation_id": conversation["conversation_id"],
        "domain": normalize_domain(screening.get("domain") or candidate["filter_metadata"].get("inferred_domain", "")),
        "decision_type": screening.get("decision_type", ""),
        "decision_oriented_score": screening.get("decision_oriented_score", 0),
        "case_category": screening.get("case_category", ""),
        "autonomy_shift_strength": screening.get("autonomy_shift_strength", "none"),
        "trajectory_signal_strength": screening.get("trajectory_signal_strength", "none"),
        "keep_for_main_analysis": screening.get("keep_for_main_analysis", False),
        "keep_for_contrast_or_training": screening.get("keep_for_contrast_or_training", False),
        "keep_for_manual_review": screening.get("keep_for_manual_review", False),
        "topic_consistency_score": screening.get("topic_consistency_score", 0),
        "topic_consistency_rationale": screening.get("topic_consistency_rationale", ""),
        "seed_quality": screening.get("candidate_seed_quality", "poor"),
        "risk_level": screening.get("risk_level", "low"),
        "keep_for_rae": screening.get("keep_for_rae", False),
        "primary_mechanism": screening.get("primary_mechanism", "none"),
        "secondary_mechanism": screening.get("secondary_mechanism", "none"),
        "user_initial_goal": screening.get("user_initial_goal", ""),
        "initial_preference_or_criteria": screening.get("initial_preference_or_criteria", ""),
        "assistant_recommendation_or_framing": screening.get("assistant_recommendation_or_framing", ""),
        "user_final_choice_or_later_stance": screening.get("user_final_choice_or_later_stance", ""),
        "preference_changed": screening.get("preference_changed", False),
        "explicit_reflection": screening.get("explicit_reflection", False),
        "initiative_drop": screening.get("initiative_drop", 0),
        "critical_evaluation_drop": screening.get("critical_evaluation_drop", 0),
        "turn_level_autonomy_trajectory": screening.get("turn_level_autonomy_trajectory", []),
        "autonomy_shift_event": screening.get("autonomy_shift_event", {}),
        "evidence_turns": screening.get("evidence_turns", []),
        "num_turns": candidate["filter_metadata"].get("num_turns", len(conversation["turns"])),
        "autonomy_behaviors": normalize_behaviors(screening.get("autonomy_relevant_behaviors", [])),
        "why_categorized_this_way": screening.get("why_categorized_this_way", ""),
        "representative_excerpt": representative_excerpt(conversation, representative_excerpt_chars),
        "template_potential": template_potential(screening),
        "exclude_sensitive_details": contains_sensitive_details(conversation),
        "notes_for_later_template_design": "",
    }


def template_potential(screening: dict[str, Any]) -> str:
    domain = screening.get("domain") or "decision-making"
    decision_type = screening.get("decision_type") or "a practical decision"
    return f"Can be converted into a scenario about {domain} involving {decision_type}."


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "case_id",
        "source",
        "conversation_id",
        "domain",
        "decision_type",
        "decision_oriented_score",
        "case_category",
        "autonomy_shift_strength",
        "trajectory_signal_strength",
        "keep_for_main_analysis",
        "keep_for_contrast_or_training",
        "keep_for_manual_review",
        "topic_consistency_score",
        "topic_consistency_rationale",
        "seed_quality",
        "risk_level",
        "keep_for_rae",
        "primary_mechanism",
        "secondary_mechanism",
        "user_initial_goal",
        "initial_preference_or_criteria",
        "assistant_recommendation_or_framing",
        "user_final_choice_or_later_stance",
        "preference_changed",
        "explicit_reflection",
        "initiative_drop",
        "critical_evaluation_drop",
        "turn_level_autonomy_trajectory",
        "autonomy_shift_event",
        "evidence_turns",
        "num_turns",
        "autonomy_behaviors",
        "why_categorized_this_way",
        "representative_excerpt",
        "template_potential",
        "exclude_sensitive_details",
        "notes_for_later_template_design",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            csv_row = dict(row)
            csv_row["autonomy_behaviors"] = "; ".join(row.get("autonomy_behaviors", []))
            csv_row["turn_level_autonomy_trajectory"] = json.dumps(
                row.get("turn_level_autonomy_trajectory", []),
                ensure_ascii=False,
            )
            csv_row["autonomy_shift_event"] = json.dumps(row.get("autonomy_shift_event", {}), ensure_ascii=False)
            csv_row["evidence_turns"] = json.dumps(row.get("evidence_turns", []), ensure_ascii=False)
            writer.writerow(csv_row)


def write_summary_report(
    path: Path,
    screened_rows: list[dict[str, Any]],
    total_loaded: int | None = None,
    retained_cases_override: list[dict[str, Any]] | None = None,
) -> None:
    scores = Counter(row["screening"]["decision_oriented_score"] for row in screened_rows)
    risk_levels = Counter(row["screening"].get("risk_level", "none") for row in screened_rows)
    nonmain_categories = Counter(
        row["screening"].get("case_category", "unknown")
        for row in screened_rows
        if not row["screening"].get("keep_for_rae", False)
    )
    retained_cases = retained_cases_override or [row["case"] for row in screened_rows if row.get("case")]
    mechanisms = Counter(case.get("primary_mechanism", "none") for case in retained_cases)
    initiative_drops = Counter(case.get("initiative_drop", 0) for case in retained_cases)
    critical_drops = Counter(case.get("critical_evaluation_drop", 0) for case in retained_cases)
    domains = Counter(case["domain"] for case in retained_cases)
    behaviors = Counter(
        behavior
        for case in retained_cases
        for behavior in case.get("autonomy_behaviors", [])
    )
    recommended = [
        case
        for case in retained_cases
        if case["decision_oriented_score"] == 3
        and case["seed_quality"] in {"good", "excellent"}
    ][:10]

    lines = [
        "# Autonomy Seed-Case Curation Summary",
        "",
        f"- Conversations loaded: {total_loaded if total_loaded is not None else 'not tracked'}",
        f"- Conversations screened: {len(screened_rows)}",
        f"- Retained deduplicated cases: {len(retained_cases)}",
        f"- Score counts: {dict(sorted(scores.items()))}",
        f"- Risk levels: {dict(risk_levels.most_common())}",
        f"- Primary mechanisms among retained cases: {dict(mechanisms.most_common())}",
        f"- Initiative drop among retained cases: {dict(sorted(initiative_drops.items()))}",
        f"- Critical evaluation drop among retained cases: {dict(sorted(critical_drops.items()))}",
        f"- Top non-main case categories: {dict(nonmain_categories.most_common(10))}",
        f"- Top domains: {dict(domains.most_common(10))}",
        f"- Top autonomy behaviors: {dict(behaviors.most_common(10))}",
        "",
        "## Recommended Scenario-Template Cases",
    ]
    for case in recommended:
        lines.append(
            f"- {case['case_id']} | {case['domain']} | score={case['decision_oriented_score']} | "
            f"quality={case['seed_quality']} | {case['user_initial_goal']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
