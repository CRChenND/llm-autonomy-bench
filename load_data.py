"""Load and prefilter conversations from Hugging Face datasets."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from config import DatasetSpec, PipelineConfig
from filter_candidates import passes_candidate_filter
from normalize import normalize_row

LOGGER = logging.getLogger(__name__)


def iter_hf_rows(spec: DatasetSpec, config: PipelineConfig) -> Iterator[dict[str, Any]]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency 'datasets'. Install dependencies with `uv sync`."
        ) from exc

    LOGGER.info("Loading %s from %s split=%s streaming=%s", spec.source, spec.hf_name, spec.split, config.stream_datasets)
    kwargs: dict[str, Any] = {
        "path": spec.hf_name,
        "split": spec.split,
        "streaming": config.stream_datasets,
    }
    if spec.config_name:
        kwargs["name"] = spec.config_name
    if config.hf_token:
        kwargs["token"] = config.hf_token

    dataset = load_dataset(**kwargs)
    yield from dataset


def iter_normalized_conversations(config: PipelineConfig) -> Iterator[dict[str, Any]]:
    for spec in config.datasets:
        loaded = 0
        normalized = 0
        for index, row in enumerate(iter_hf_rows(spec, config)):
            if config.max_records_per_dataset is not None and loaded >= config.max_records_per_dataset:
                break
            loaded += 1
            conversation = normalize_row(row, spec.source, index)
            if conversation is None:
                continue
            normalized += 1
            yield conversation
        LOGGER.info("Dataset %s loaded=%s normalized=%s", spec.source, loaded, normalized)


def iter_candidate_conversations(config: PipelineConfig) -> Iterator[tuple[dict[str, Any], dict[str, Any]]]:
    for conversation in iter_normalized_conversations(config):
        keep, filter_metadata = passes_candidate_filter(
            conversation,
            keywords=config.decision_keywords,
            min_user_turns=config.min_user_turns,
            min_total_turns=config.min_total_turns,
            min_chars=config.min_chars,
        )
        if keep:
            yield conversation, filter_metadata
