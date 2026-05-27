"""Candidate preparation, ranking, and deduplication before LLM screening."""

from __future__ import annotations

import hashlib
import heapq
import logging
import re
from pathlib import Path
from typing import Any

from config import PipelineConfig
from export_results import read_jsonl
from filter_candidates import is_english_like, passes_candidate_filter

LOGGER = logging.getLogger(__name__)


def conversation_text_for_candidate(candidate: dict[str, Any]) -> str:
    return "\n".join(
        turn.get("content", "")
        for turn in candidate["conversation"].get("turns", [])
    )


def refresh_candidate_metadata(candidate: dict[str, Any], config: PipelineConfig) -> dict[str, Any]:
    conversation = candidate["conversation"]
    _, filter_metadata = passes_candidate_filter(
        conversation,
        keywords=config.decision_keywords,
        min_user_turns=config.min_user_turns,
        min_total_turns=config.min_total_turns,
        min_chars=config.min_chars,
    )
    updated = dict(candidate)
    previous_metadata = dict(candidate.get("filter_metadata") or {})
    previous_metadata.update(filter_metadata)
    updated["filter_metadata"] = previous_metadata
    return updated


def candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int]:
    metadata = candidate["filter_metadata"]
    return (
        metadata.get("decision_signal_score", 0),
        metadata.get("num_user_turns", 0),
        metadata.get("char_count", 0),
    )


def passes_structural_screen(candidate: dict[str, Any], config: PipelineConfig) -> bool:
    metadata = candidate["filter_metadata"]
    return (
        metadata.get("num_user_turns", 0) >= config.min_user_turns
        and metadata.get("num_turns", 0) >= config.min_total_turns
        and metadata.get("char_count", 0) >= config.min_chars
    )


def candidate_id_key(candidate: dict[str, Any]) -> str:
    conversation = candidate["conversation"]
    return f"{conversation.get('source')}::{conversation.get('conversation_id')}"


def normalize_for_dedupe(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return text.strip()


def candidate_content_key(candidate: dict[str, Any]) -> str:
    user_text = " ".join(
        turn.get("content", "")
        for turn in candidate["conversation"].get("turns", [])
        if turn.get("role") == "user"
    )
    normalized = normalize_for_dedupe(user_text)[:12000]
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_ids = set()
    seen_content = set()
    deduped = []
    for candidate in candidates:
        id_key = candidate_id_key(candidate)
        content_key = candidate_content_key(candidate)
        if id_key in seen_ids or content_key in seen_content:
            continue
        seen_ids.add(id_key)
        seen_content.add(content_key)
        deduped.append(candidate)
    if len(deduped) != len(candidates):
        LOGGER.info("Deduplicated candidates: kept %s/%s before LLM screening", len(deduped), len(candidates))
    return deduped


def prepare_candidates_for_llm(
    candidates: list[dict[str, Any]],
    config: PipelineConfig,
    english_only: bool,
    min_score: int,
    top_n: int | None,
) -> list[dict[str, Any]]:
    prepared = [refresh_candidate_metadata(candidate, config) for candidate in candidates]
    before = len(prepared)
    prepared = [candidate for candidate in prepared if passes_structural_screen(candidate, config)]
    LOGGER.info(
        "Kept %s/%s candidates satisfying structural filters: user_turns >= %s, total_turns >= %s",
        len(prepared),
        before,
        config.min_user_turns,
        config.min_total_turns,
    )
    if english_only:
        before = len(prepared)
        prepared = [
            candidate
            for candidate in prepared
            if is_english_like(conversation_text_for_candidate(candidate))
        ]
        LOGGER.info("Kept %s/%s English-like candidates", len(prepared), before)
    if min_score > 0:
        before = len(prepared)
        prepared = [
            candidate
            for candidate in prepared
            if candidate["filter_metadata"].get("decision_signal_score", 0) >= min_score
        ]
        LOGGER.info(
            "Kept %s/%s candidates satisfying decision_signal_score >= %s after English filtering",
            len(prepared),
            before,
            min_score,
        )
    prepared.sort(key=candidate_sort_key, reverse=True)
    if top_n is not None:
        prepared = prepared[:top_n]
        LOGGER.info("Selected top %s candidates for LLM screening", len(prepared))
    return prepared


def stream_filter_candidates(
    path: Path,
    config: PipelineConfig,
    english_only: bool,
    min_score: int,
    dedupe: bool,
    progress_factory,
) -> list[dict[str, Any]]:
    selected = []
    seen = 0
    english_kept = 0
    eligible_kept = 0
    seen_content = set()
    duplicate_count = 0
    progress = progress_factory(None, "Filtering candidates", "candidate")
    try:
        for seen, candidate in enumerate(read_jsonl(path), start=1):
            candidate = refresh_candidate_metadata(candidate, config)
            if progress is not None:
                progress.update(1)
            if not passes_structural_screen(candidate, config):
                continue
            score = candidate["filter_metadata"].get("decision_signal_score", 0)
            if english_only and not is_english_like(conversation_text_for_candidate(candidate)):
                if progress is not None:
                    progress.set_postfix(english=english_kept, eligible=eligible_kept, score=score, refresh=False)
                continue
            english_kept += 1
            if score < min_score:
                if progress is not None:
                    progress.set_postfix(english=english_kept, eligible=eligible_kept, score=score, refresh=False)
                continue
            if dedupe:
                content_key = candidate_content_key(candidate)
                if content_key in seen_content:
                    duplicate_count += 1
                    if progress is not None:
                        progress.set_postfix(english=english_kept, eligible=eligible_kept, score=score, refresh=False)
                    continue
                seen_content.add(content_key)
            eligible_kept += 1
            selected.append(candidate)
            if progress is not None:
                progress.set_postfix(english=english_kept, eligible=eligible_kept, score=score, refresh=False)
    finally:
        if progress is not None:
            progress.close()

    if english_only:
        LOGGER.info("Kept %s/%s English-like candidates", english_kept, seen)
    if min_score > 0:
        filter_description = (
            f" (English-like AND decision_signal_score >= {min_score})"
            if english_only
            else f" (decision_signal_score >= {min_score})"
        )
        LOGGER.info(
            "Kept %s/%s candidates satisfying all pre-LLM filters%s",
            eligible_kept,
            seen,
            filter_description,
        )
    if dedupe:
        LOGGER.info("Dropped %s duplicate candidates before LLM screening", duplicate_count)
    LOGGER.info("Selected %s candidates for LLM screening", len(selected))
    return selected


def load_candidates_for_llm(
    path: Path,
    config: PipelineConfig,
    english_only: bool,
    min_score: int,
    top_n: int | None,
    dedupe: bool,
    progress_factory,
) -> list[dict[str, Any]]:
    if top_n is None:
        return stream_filter_candidates(
            path,
            config,
            english_only=english_only,
            min_score=min_score,
            dedupe=dedupe,
            progress_factory=progress_factory,
        )

    best_by_content: dict[str, dict[str, Any]] = {}
    heap: list[tuple[tuple[int, int, int], int, dict[str, Any]]] = []
    seen = 0
    english_kept = 0
    eligible_kept = 0
    duplicate_count = 0
    progress = progress_factory(None, "Ranking candidates", "candidate")
    try:
        for seen, candidate in enumerate(read_jsonl(path), start=1):
            candidate = refresh_candidate_metadata(candidate, config)
            if progress is not None:
                progress.update(1)
            if not passes_structural_screen(candidate, config):
                continue
            score = candidate["filter_metadata"].get("decision_signal_score", 0)
            if english_only and not is_english_like(conversation_text_for_candidate(candidate)):
                if progress is not None:
                    progress.set_postfix(english=english_kept, eligible=eligible_kept, score=score, refresh=False)
                continue
            english_kept += 1
            if progress is not None:
                progress.set_postfix(english=english_kept, eligible=eligible_kept, score=score, refresh=False)
            if score < min_score:
                continue
            if dedupe:
                content_key = candidate_content_key(candidate)
                existing = best_by_content.get(content_key)
                if existing and candidate_sort_key(existing) >= candidate_sort_key(candidate):
                    duplicate_count += 1
                    continue
                if existing:
                    duplicate_count += 1
                best_by_content[content_key] = candidate
                eligible_kept += 1
                continue
            eligible_kept += 1
            item = (candidate_sort_key(candidate), seen, candidate)
            if len(heap) < top_n:
                heapq.heappush(heap, item)
            else:
                heapq.heappushpop(heap, item)
    finally:
        if progress is not None:
            progress.close()

    selected = (
        sorted(best_by_content.values(), key=candidate_sort_key, reverse=True)[:top_n]
        if dedupe
        else [item[2] for item in sorted(heap, key=lambda item: item[0], reverse=True)]
    )
    if english_only:
        LOGGER.info("Kept %s/%s English-like candidates", english_kept, seen)
    if min_score > 0:
        filter_description = (
            f" (English-like AND decision_signal_score >= {min_score})"
            if english_only
            else f" (decision_signal_score >= {min_score})"
        )
        LOGGER.info(
            "Kept %s/%s candidates satisfying all pre-LLM filters%s",
            eligible_kept,
            seen,
            filter_description,
        )
    if dedupe:
        LOGGER.info("Dropped %s duplicate candidates before top-N selection", duplicate_count)
    LOGGER.info("Selected top %s candidates for LLM screening", len(selected))
    return selected
