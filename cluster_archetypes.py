"""Cluster retained autonomy-shift cases into coarse research archetypes."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from export_results import read_jsonl


ARCHETYPES = {
    "advisor_overreliance": "Type A - Advisor Overreliance",
    "optimization_capture": "Type B - Optimization Capture",
    "cognitive_offloading_spiral": "Type C - Cognitive Offloading Spiral",
    "mixed_or_other": "Mixed / Other",
}


def case_text(case: dict[str, Any], screening: dict[str, Any]) -> str:
    fields = [
        case.get("domain", ""),
        case.get("decision_type", ""),
        screening.get("user_initial_goal", ""),
        screening.get("initial_preference_or_criteria", ""),
        screening.get("assistant_recommendation_or_framing", ""),
        screening.get("user_final_choice_or_later_stance", ""),
        screening.get("why_categorized_this_way", ""),
    ]
    return " ".join(str(field).lower() for field in fields)


def assign_archetype(case: dict[str, Any], screening: dict[str, Any]) -> str:
    mechanism = str(case.get("primary_mechanism") or screening.get("primary_mechanism") or "none")
    secondary = str(case.get("secondary_mechanism") or screening.get("secondary_mechanism") or "none")
    mechanisms = {mechanism.upper(), secondary.upper()}
    domain = str(case.get("domain") or "").lower()
    text = case_text(case, screening)
    initiative_drop = int(case.get("initiative_drop") or screening.get("initiative_drop") or 0)

    if mechanisms & {"OC", "PC"} or any(term in text for term in ["cheapest", "cost", "optimize", "efficient"]):
        return "optimization_capture"
    if mechanisms & {"COS", "LHD"} or initiative_drop >= 2:
        return "cognitive_offloading_spiral"
    if mechanisms & {"DDM", "AI", "RCE"} and domain in {"career", "health", "medical", "relationship"}:
        return "advisor_overreliance"
    return "mixed_or_other"


def load_retained_cases(path: Path) -> list[dict[str, Any]]:
    rows = []
    for row in read_jsonl(path):
        case = row.get("case")
        screening = row.get("screening", {})
        if case and screening.get("keep_for_rae", False):
            rows.append({"case": case, "screening": screening})
    return rows


def build_archetype_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        archetype = assign_archetype(row["case"], row["screening"])
        buckets[archetype].append(row)

    summaries = {}
    for archetype, items in buckets.items():
        domains = Counter(item["case"].get("domain", "") for item in items)
        mechanisms = Counter(item["case"].get("primary_mechanism", "none") for item in items)
        examples = [
            {
                "case_id": item["case"].get("case_id"),
                "domain": item["case"].get("domain"),
                "primary_mechanism": item["case"].get("primary_mechanism"),
                "initial_preference_or_criteria": item["screening"].get(
                    "initial_preference_or_criteria",
                    "",
                ),
                "user_final_choice_or_later_stance": item["screening"].get(
                    "user_final_choice_or_later_stance",
                    "",
                ),
            }
            for item in items[:10]
        ]
        summaries[archetype] = {
            "label": ARCHETYPES[archetype],
            "count": len(items),
            "top_domains": dict(domains.most_common(10)),
            "top_mechanisms": dict(mechanisms.most_common(10)),
            "examples": examples,
        }

    return {
        "total_retained_cases": len(rows),
        "archetypes": summaries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screened", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_retained_cases(args.screened)
    summary = build_archetype_summary(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
