"""Run the autonomy-oriented conversation seed-case curation pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from config import PipelineConfig, load_config_from_env
from candidate_selection import (
    candidate_id_key,
    candidate_sort_key,
    dedupe_candidates,
    load_candidates_for_llm,
    normalize_for_dedupe,
    prepare_candidates_for_llm,
)
from export_results import (
    append_jsonl,
    build_case_record,
    ensure_output_dir,
    read_jsonl,
    write_jsonl,
    write_summary_report,
)
from load_data import iter_candidate_conversations
from llm_screen import SCREENING_SCHEMA_VERSION, screen_conversation
from normalize import conversation_to_text

LOGGER = logging.getLogger(__name__)


def progress_bar(items: list[dict[str, Any]], description: str):
    try:
        from tqdm import tqdm
    except ImportError:
        return items
    return tqdm(items, total=len(items), desc=description, unit="case", dynamic_ncols=True)


def streaming_progress_bar(total: int | None, description: str, unit: str):
    try:
        from tqdm import tqdm
    except ImportError:
        return None
    return tqdm(total=total, desc=description, unit=unit, dynamic_ncols=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--output-prefix",
        default="",
        help="Prefix for generated output filenames, e.g. wildchat_ or sharegpt_.",
    )
    parser.add_argument("--max-records-per-dataset", type=int, default=None)
    parser.add_argument("--all-records", action="store_true", help="Scan all records from each configured dataset.")
    parser.add_argument(
        "--sources",
        default=None,
        help="Comma-separated source names to scan, e.g. WildChat,ShareGPT or ShareGPT.",
    )
    parser.add_argument("--max-candidates", type=int, default=None)
    parser.add_argument("--prefilter-only", action="store_true")
    parser.add_argument("--candidate-output", type=Path, default=None)
    parser.add_argument("--append-candidates", action="store_true")
    parser.add_argument("--screen-existing-candidates", type=Path, default=None)
    parser.add_argument(
        "--rank-candidates-output",
        type=Path,
        default=None,
        help="Write the filtered/deduplicated/ranked candidate queue to JSONL and exit before LLM screening.",
    )
    parser.add_argument(
        "--retry-screening-errors",
        type=Path,
        default=None,
        help="Rerun only rows with an error field in an existing screened_results.jsonl file, then rebuild exports.",
    )
    parser.add_argument(
        "--rebuild-from-screened",
        type=Path,
        default=None,
        help="Rebuild case records and exports from an existing screened_results.jsonl file without calling the LLM.",
    )
    parser.add_argument(
        "--export-full-context-from-screened",
        type=Path,
        default=None,
        help="Export retained/full-context analysis baselines from an existing screened_results.jsonl file.",
    )
    parser.add_argument(
        "--full-context-output-dir",
        type=Path,
        default=Path("data/autonomy_seed_cases_full_context"),
        help="Output directory for full-context analysis baseline exports.",
    )
    parser.add_argument("--english-only", action="store_true", help="Only send English-like candidates to LLM screening.")
    parser.add_argument("--min-decision-signal-score", type=int, default=0)
    parser.add_argument("--top-n-for-llm", type=int, default=None)
    parser.add_argument(
        "--llm-concurrency",
        type=int,
        default=None,
        help="Number of concurrent LLM screening requests. Defaults to LLM_CONCURRENCY or 1.",
    )
    parser.add_argument("--no-dedupe-candidates", action="store_true", help="Disable candidate deduplication before LLM screening.")
    parser.add_argument("--resume-screening", action="store_true", help="Append to existing screened_results.jsonl and skip already screened conversations.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop screening on the first LLM error.")
    parser.add_argument("--log-every", type=int, default=1000)
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args()


def prefixed_path(output_dir: Path, prefix: str, filename: str) -> Path:
    return output_dir / f"{prefix}{filename}"


def config_from_args(args: argparse.Namespace) -> PipelineConfig:
    config = load_config_from_env()
    updates: dict[str, Any] = {}
    if args.output_dir is not None:
        updates["output_dir"] = args.output_dir
    if args.all_records:
        updates["max_records_per_dataset"] = None
    if args.max_records_per_dataset is not None:
        updates["max_records_per_dataset"] = args.max_records_per_dataset
    if args.llm_concurrency is not None:
        updates["llm_concurrency"] = max(1, args.llm_concurrency)
    if args.sources:
        requested_sources = {source.strip().lower() for source in args.sources.split(",") if source.strip()}
        datasets = tuple(
            dataset for dataset in config.datasets if dataset.source.lower() in requested_sources
        )
        if not datasets:
            known = ", ".join(dataset.source for dataset in config.datasets)
            raise ValueError(f"No matching sources for {args.sources!r}. Known sources: {known}")
        updates["datasets"] = datasets
    return PipelineConfig(**{**config.__dict__, **updates})


def collect_candidates(config: PipelineConfig, max_candidates: int | None) -> list[dict[str, Any]]:
    candidates = []
    candidate_iter = iter_candidate_conversations(config)
    for conversation, filter_metadata in candidate_iter:
        candidates.append({"conversation": conversation, "filter_metadata": filter_metadata})
        if max_candidates is not None and len(candidates) >= max_candidates:
            break
    return candidates


def write_candidates_streaming(
    config: PipelineConfig,
    output_path: Path,
    max_candidates: int | None,
    log_every: int,
    append: bool,
) -> int:
    count = 0
    progress = streaming_progress_bar(max_candidates, "Prefiltering candidates", "candidate")
    candidate_iter = iter_candidate_conversations(config)
    mode = "a" if append else "w"
    try:
        with output_path.open(mode, encoding="utf-8") as file:
            for conversation, filter_metadata in candidate_iter:
                row = {"conversation": conversation, "filter_metadata": filter_metadata}
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
                if progress is not None:
                    progress.update(1)
                    progress.set_postfix(
                        source=conversation["source"],
                        score=filter_metadata.get("decision_signal_score", 0),
                        refresh=False,
                    )
                elif log_every > 0 and count % log_every == 0:
                    LOGGER.info("Wrote %s candidates so far to %s", count, output_path)
                if max_candidates is not None and count >= max_candidates:
                    break
    finally:
        if progress is not None:
            progress.close()
    return count


def error_screening_result(error_message: str) -> dict[str, Any]:
    return {
        "screening_schema_version": SCREENING_SCHEMA_VERSION,
        "decision_oriented_score": 0,
        "case_category": "insufficient_context",
        "autonomy_shift_strength": "none",
        "trajectory_signal_strength": "none",
        "keep": False,
        "keep_for_rae": False,
        "keep_for_main_analysis": False,
        "keep_for_contrast_or_training": False,
        "keep_for_manual_review": False,
        "decision_type": "",
        "domain": "",
        "topic_consistency_score": 0,
        "topic_consistency_rationale": "",
        "autonomy_relevant_behaviors": [],
        "primary_mechanism": "none",
        "secondary_mechanism": "none",
        "user_initial_goal": "",
        "initial_preference_or_criteria": "",
        "assistant_recommendation_or_framing": "",
        "user_final_choice_or_later_stance": "",
        "preference_changed": False,
        "explicit_reflection": False,
        "initiative_drop": 0,
        "critical_evaluation_drop": 0,
        "turn_level_autonomy_trajectory": [],
        "autonomy_shift_event": {
            "preference_or_goal_expressed_earlier": False,
            "preference_absent_or_weakened_later": False,
            "model_suggestion_precedes_shift": False,
            "no_explicit_reflection_on_shift": False,
            "initiative_drop": 0,
            "critical_evaluation_drop": 0,
            "shift_turn": "",
            "summary": "",
        },
        "evidence_turns": [],
        "why_categorized_this_way": f"LLM screening failed: {error_message}",
        "risk_level": "none",
        "candidate_seed_quality": "poor",
    }


def case_dedupe_key(case: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(case.get("domain", "")),
            str(case.get("decision_type", "")),
            str(case.get("user_initial_goal", "")),
            str(case.get("initial_preference_or_criteria", "")),
        ]
    )
    normalized = normalize_for_dedupe(text)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def dedupe_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    quality_rank = {"excellent": 3, "good": 2, "fair": 1, "poor": 0}
    sorted_cases = sorted(
        cases,
        key=lambda case: (
            case.get("decision_oriented_score", 0),
            quality_rank.get(case.get("seed_quality", "poor"), 0),
            case.get("num_turns", 0),
        ),
        reverse=True,
    )
    for case in sorted_cases:
        key = case_dedupe_key(case)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(case)
    if len(deduped) != len(cases):
        LOGGER.info("Deduplicated retained cases: kept %s/%s", len(deduped), len(cases))
    return deduped


def screen_candidates(
    config: PipelineConfig,
    candidates: list[dict[str, Any]],
    fail_fast: bool,
    resume: bool,
    output_prefix: str,
) -> list[dict[str, Any]]:
    screened_path = prefixed_path(config.output_dir, output_prefix, "screened_results.jsonl")
    existing_rows = []
    existing_ids = set()
    if resume and screened_path.exists():
        loaded_rows = list(read_jsonl(screened_path))
        existing_rows = [
            row
            for row in loaded_rows
            if row.get("screening", {}).get("screening_schema_version") == SCREENING_SCHEMA_VERSION
        ]
        if len(existing_rows) != len(loaded_rows):
            raise RuntimeError(
                f"{screened_path} contains {len(loaded_rows) - len(existing_rows)} legacy screened rows "
                f"that do not match {SCREENING_SCHEMA_VERSION}. Use a new --output-prefix for RAE screening "
                "or move the old screened_results.jsonl before resuming."
            )
        existing_ids = {candidate_id_key(row["candidate"]) for row in existing_rows if row.get("candidate")}
        LOGGER.info("Resume enabled: loaded %s existing screened rows", len(existing_rows))
    elif screened_path.exists():
        screened_path.unlink()

    pending_candidates = [
        candidate for candidate in candidates if candidate_id_key(candidate) not in existing_ids
    ]
    if resume and len(pending_candidates) != len(candidates):
        LOGGER.info("Resume enabled: skipping %s already screened candidates", len(candidates) - len(pending_candidates))

    screened_rows = list(existing_rows)
    concurrency = max(1, min(config.llm_concurrency, len(pending_candidates) or 1))
    LOGGER.info("Screening %s pending candidates with concurrency=%s", len(pending_candidates), concurrency)

    def screen_one(candidate: dict[str, Any]) -> dict[str, Any]:
        conversation = candidate["conversation"]
        error_message = None
        try:
            screening = screen_conversation(conversation, config)
        except Exception as exc:  # noqa: BLE001 - keep batch jobs moving unless requested otherwise.
            if fail_fast:
                raise
            error_message = str(exc)
            LOGGER.error(
                "Skipping candidate after LLM screening failure source=%s id=%s error=%s",
                conversation["source"],
                conversation["conversation_id"],
                error_message,
            )
            screening = error_screening_result(error_message)
        case = None
        if screening.get("keep_for_rae", screening.get("keep", False)):
            case = build_case_record(candidate, screening, config.representative_excerpt_chars)
        row = {"candidate": candidate, "screening": screening, "case": case}
        if error_message:
            row["error"] = error_message
        return row

    if concurrency == 1:
        progress = progress_bar(pending_candidates, "Screening candidates")
        for candidate in progress:
            conversation = candidate["conversation"]
            if hasattr(progress, "set_postfix"):
                progress.set_postfix(
                    source=conversation["source"],
                    id=str(conversation["conversation_id"])[:10],
                    score=candidate.get("filter_metadata", {}).get("decision_signal_score", 0),
                    en=candidate.get("filter_metadata", {}).get("english_likeness_score", 0),
                    refresh=False,
                )
            row = screen_one(candidate)
            append_jsonl(screened_path, row)
            screened_rows.append(row)
        return screened_rows

    progress = progress_bar(pending_candidates, "Screening candidates")
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(screen_one, candidate): candidate for candidate in pending_candidates}
        for future in as_completed(futures):
            candidate = futures[future]
            conversation = candidate["conversation"]
            if hasattr(progress, "set_postfix"):
                progress.set_postfix(
                    source=conversation["source"],
                    id=str(conversation["conversation_id"])[:10],
                    score=candidate.get("filter_metadata", {}).get("decision_signal_score", 0),
                    en=candidate.get("filter_metadata", {}).get("english_likeness_score", 0),
                    refresh=False,
                )
            row = future.result()
            append_jsonl(screened_path, row)
            if hasattr(progress, "update"):
                progress.update(1)
            screened_rows.append(row)
    if hasattr(progress, "close"):
        progress.close()
    return screened_rows


def export_screened_outputs(
    config: PipelineConfig,
    screened_rows: list[dict[str, Any]],
    output_prefix: str,
) -> None:
    retained_cases = dedupe_cases([row["case"] for row in screened_rows if row.get("case")])
    write_summary_report(
        prefixed_path(config.output_dir, output_prefix, "summary_report.md"),
        screened_rows,
        retained_cases_override=retained_cases,
    )


def build_full_context_row(row: dict[str, Any]) -> dict[str, Any]:
    candidate = row["candidate"]
    conversation = candidate["conversation"]
    case = row.get("case")
    screening = row.get("screening", {})
    return {
        "case_id": case.get("case_id") if case else None,
        "source": conversation["source"],
        "conversation_id": conversation["conversation_id"],
        "screening": screening,
        "case": case,
        "filter_metadata": candidate.get("filter_metadata", {}),
        "conversation": conversation,
        "conversation_text": conversation_to_text(conversation),
    }


def export_full_context_baselines(
    screened_rows: list[dict[str, Any]],
    output_dir: Path,
    output_prefix: str,
) -> None:
    ensure_output_dir(output_dir)
    retained_rows = [row for row in screened_rows if row.get("case")]
    retained_rows.sort(
        key=lambda row: (
            row["screening"].get("decision_oriented_score", 0),
            row["case"].get("seed_quality", "poor") if row.get("case") else "",
            row["case"].get("num_turns", 0) if row.get("case") else 0,
        ),
        reverse=True,
    )

    write_jsonl(
        output_dir / f"{output_prefix}retained_full_context.jsonl",
        [build_full_context_row(row) for row in retained_rows],
    )

    summary_lines = [
        "# Full-Context Export Summary",
        "",
        f"- Screened rows loaded: {len(screened_rows)}",
        f"- Retained full-context rows: {len(retained_rows)}",
        "",
        "## Files",
        f"- {output_dir / f'{output_prefix}retained_full_context.jsonl'}",
    ]
    (output_dir / f"{output_prefix}full_context_summary.md").write_text(
        "\n".join(summary_lines) + "\n",
        encoding="utf-8",
    )


def rebuild_screened_rows(
    config: PipelineConfig,
    screened_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rebuilt_rows: list[dict[str, Any]] = []
    for row in screened_rows:
        candidate = row.get("candidate")
        screening = row.get("screening", {})
        case = None
        if candidate and screening.get("keep_for_rae", screening.get("keep", False)):
            case = build_case_record(candidate, screening, config.representative_excerpt_chars)
        rebuilt_row = {
            "candidate": candidate,
            "screening": screening,
            "case": case,
        }
        if row.get("error"):
            rebuilt_row["error"] = row["error"]
        rebuilt_rows.append(rebuilt_row)
    return rebuilt_rows


def rerun_screening_errors(
    config: PipelineConfig,
    screened_path: Path,
    fail_fast: bool,
    output_prefix: str,
) -> list[dict[str, Any]]:
    if not screened_path.exists():
        raise FileNotFoundError(f"Screened results file not found: {screened_path}")

    screened_rows = list(read_jsonl(screened_path))
    error_indexes = [index for index, row in enumerate(screened_rows) if row.get("error")]
    LOGGER.info("Loaded %s screened rows from %s", len(screened_rows), screened_path)
    LOGGER.info("Found %s rows with screening errors to retry", len(error_indexes))

    if not error_indexes:
        export_screened_outputs(config, screened_rows, output_prefix=output_prefix)
        LOGGER.info("No error rows found. Rebuilt exports from existing screened results.")
        return screened_rows

    retry_progress = progress_bar(
        [screened_rows[index] for index in error_indexes],
        "Retrying screening errors",
    )
    for row in retry_progress:
        candidate = row["candidate"]
        conversation = candidate["conversation"]
        if hasattr(retry_progress, "set_postfix"):
            retry_progress.set_postfix(
                source=conversation["source"],
                id=str(conversation["conversation_id"])[:10],
                score=candidate.get("filter_metadata", {}).get("decision_signal_score", 0),
                refresh=False,
            )

        error_message = None
        try:
            screening = screen_conversation(conversation, config)
        except Exception as exc:  # noqa: BLE001 - keep batch jobs moving unless requested otherwise.
            if fail_fast:
                raise
            error_message = str(exc)
            LOGGER.error(
                "Retry failed for source=%s id=%s error=%s",
                conversation["source"],
                conversation["conversation_id"],
                error_message,
            )
            screening = error_screening_result(error_message)

        case = None
        if screening.get("keep_for_rae", screening.get("keep", False)):
            case = build_case_record(candidate, screening, config.representative_excerpt_chars)
        updated_row = {"candidate": candidate, "screening": screening, "case": case}
        if error_message:
            updated_row["error"] = error_message

        row.clear()
        row.update(updated_row)

    write_jsonl(screened_path, screened_rows)
    export_screened_outputs(config, screened_rows, output_prefix=output_prefix)
    LOGGER.info("Retried %s error rows and rewrote %s", len(error_indexes), screened_path)
    return screened_rows


def rebuild_from_screened(
    config: PipelineConfig,
    screened_path: Path,
    output_prefix: str,
) -> list[dict[str, Any]]:
    if not screened_path.exists():
        raise FileNotFoundError(f"Screened results file not found: {screened_path}")
    screened_rows = list(read_jsonl(screened_path))
    LOGGER.info("Loaded %s screened rows from %s", len(screened_rows), screened_path)
    rebuilt_rows = rebuild_screened_rows(config, screened_rows)
    write_jsonl(screened_path, rebuilt_rows)
    export_screened_outputs(config, rebuilt_rows, output_prefix=output_prefix)
    LOGGER.info("Rebuilt case records and exports from %s", screened_path)
    return rebuilt_rows


def export_full_context_from_screened(
    screened_path: Path,
    output_dir: Path,
    output_prefix: str,
) -> list[dict[str, Any]]:
    if not screened_path.exists():
        raise FileNotFoundError(f"Screened results file not found: {screened_path}")
    screened_rows = list(read_jsonl(screened_path))
    LOGGER.info("Loaded %s screened rows from %s", len(screened_rows), screened_path)
    export_full_context_baselines(screened_rows, output_dir=output_dir, output_prefix=output_prefix)
    LOGGER.info("Exported full-context baselines to %s", output_dir)
    return screened_rows


def main() -> None:
    warnings.filterwarnings("ignore", message="resource_tracker:.*")
    os.environ.setdefault("PYTHONWARNINGS", "ignore:resource_tracker")
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)
    config = config_from_args(args)
    ensure_output_dir(config.output_dir)

    if args.export_full_context_from_screened:
        export_full_context_from_screened(
            screened_path=args.export_full_context_from_screened,
            output_dir=args.full_context_output_dir,
            output_prefix=args.output_prefix,
        )
        LOGGER.info("Full-context export mode complete. Outputs written to %s", args.full_context_output_dir)
        return
    if args.rebuild_from_screened:
        rebuild_from_screened(
            config,
            screened_path=args.rebuild_from_screened,
            output_prefix=args.output_prefix,
        )
        LOGGER.info("Rebuild-from-screened mode complete. Outputs written to %s", config.output_dir)
        return
    if args.retry_screening_errors:
        rerun_screening_errors(
            config,
            screened_path=args.retry_screening_errors,
            fail_fast=args.fail_fast,
            output_prefix=args.output_prefix,
        )
        LOGGER.info("Retry-errors mode complete. Outputs written to %s", config.output_dir)
        return
    if args.screen_existing_candidates:
        candidates = load_candidates_for_llm(
            args.screen_existing_candidates,
            config,
            english_only=args.english_only,
            min_score=args.min_decision_signal_score,
            top_n=args.top_n_for_llm,
            dedupe=not args.no_dedupe_candidates,
            progress_factory=streaming_progress_bar,
        )
        if args.rank_candidates_output:
            ranked_candidates = sorted(candidates, key=candidate_sort_key, reverse=True)
            for rank, candidate in enumerate(ranked_candidates, start=1):
                metadata = dict(candidate.get("filter_metadata") or {})
                metadata["rank"] = rank
                candidate["filter_metadata"] = metadata
            write_jsonl(args.rank_candidates_output, ranked_candidates)
            LOGGER.info("Wrote %s ranked candidates to %s", len(ranked_candidates), args.rank_candidates_output)
            LOGGER.info("Rank-candidates mode complete; no LLM screening was run.")
            return
    elif args.prefilter_only:
        candidate_path = args.candidate_output or prefixed_path(config.output_dir, args.output_prefix, "candidates.jsonl")
        if args.append_candidates and not candidate_path.exists():
            LOGGER.warning("Append requested but %s does not exist yet; creating it.", candidate_path)
        count = write_candidates_streaming(
            config,
            output_path=candidate_path,
            max_candidates=args.max_candidates,
            log_every=args.log_every,
            append=args.append_candidates,
        )
        action = "Appended" if args.append_candidates else "Wrote"
        LOGGER.info("%s %s candidates to %s", action, count, candidate_path)
        LOGGER.info("Prefilter-only mode complete.")
        logging.shutdown()
        os._exit(0)
    else:
        candidates = collect_candidates(config, args.max_candidates)
        candidate_path = prefixed_path(config.output_dir, args.output_prefix, "candidates.jsonl")
        write_jsonl(candidate_path, candidates)
        LOGGER.info("Wrote %s candidates to %s", len(candidates), candidate_path)

    if not args.screen_existing_candidates:
        candidates = prepare_candidates_for_llm(
            candidates,
            config,
            english_only=args.english_only,
            min_score=args.min_decision_signal_score,
            top_n=args.top_n_for_llm,
        )
    if not args.no_dedupe_candidates:
        candidates = dedupe_candidates(candidates)
    screened_rows = screen_candidates(
        config,
        candidates,
        fail_fast=args.fail_fast,
        resume=args.resume_screening,
        output_prefix=args.output_prefix,
    )
    export_screened_outputs(config, screened_rows, output_prefix=args.output_prefix)
    LOGGER.info("Pipeline complete. Outputs written to %s", config.output_dir)


if __name__ == "__main__":
    main()
