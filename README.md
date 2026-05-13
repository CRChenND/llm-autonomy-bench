# Autonomy Seed-Case Curation Pipeline

This repository curates real decision-oriented conversations from WildChat and ShareGPT for studying user autonomy in multi-turn LLM interaction.

The pipeline has two stages:

1. **Cheap prefiltering**: stream Hugging Face datasets, normalize conversations, apply structural and keyword filters, compute a local `decision_signal_score`, and save candidate conversations.
2. **LLM screening**: rank/filter candidates, call an Azure/OpenAI-compatible model, retain decision-oriented cases, normalize labels, deduplicate outputs, and export JSONL/CSV/report files.

## Setup

Create the virtual environment and install dependencies:

```bash
uv sync
```

Create a local credentials file:

```bash
cp .env.example .env
```

Edit `.env` with your Hugging Face token and Azure OpenAI settings. `.env` is ignored by git.

For Azure OpenAI:

- `AZURE_OPENAI_ENDPOINT` can be the resource root URL, such as `https://YOUR-RESOURCE.openai.azure.com`, or a full chat completions URL copied from Azure AI Foundry.
- `LLM_MODEL` should be the Azure deployment name.
- For `o1`/`o3`/`o4` deployments, keep `LLM_MAX_TOKENS` reasonably high because reasoning tokens count against the completion budget. The default is `2000`.

## Stage 1: Prefilter Candidates

Run WildChat full prefiltering:

```bash
uv run python run_pipeline.py \
  --prefilter-only \
  --sources WildChat \
  --all-records \
  --output-prefix wildchat_
```

This writes:

```text
data/autonomy_seed_cases/wildchat_candidates.jsonl
```

Run ShareGPT full prefiltering:

```bash
uv run python run_pipeline.py \
  --prefilter-only \
  --sources ShareGPT \
  --all-records \
  --output-prefix sharegpt_
```

This writes:

```text
data/autonomy_seed_cases/sharegpt_candidates.jsonl
```

For a small smoke test, use limits:

```bash
uv run python run_pipeline.py \
  --prefilter-only \
  --sources WildChat \
  --max-records-per-dataset 5000 \
  --max-candidates 200 \
  --output-prefix wildchat_test_
```

## Stage 2: LLM Screening

Recommended first pass for WildChat:

```bash
uv run python run_pipeline.py \
  --screen-existing-candidates data/autonomy_seed_cases/wildchat_candidates.jsonl \
  --english-only \
  --min-decision-signal-score 12 \
  --top-n-for-llm 1000 \
  --resume-screening \
  --output-prefix wildchat_
```

Recommended first pass for ShareGPT:

```bash
uv run python run_pipeline.py \
  --screen-existing-candidates data/autonomy_seed_cases/sharegpt_candidates.jsonl \
  --english-only \
  --min-decision-signal-score 12 \
  --top-n-for-llm 1000 \
  --resume-screening \
  --output-prefix sharegpt_
```

To screen all currently eligible candidates, omit `--top-n-for-llm`:

```bash
uv run python run_pipeline.py \
  --screen-existing-candidates data/autonomy_seed_cases/wildchat_candidates.jsonl \
  --english-only \
  --min-decision-signal-score 12 \
  --resume-screening \
  --output-prefix wildchat_
```

`--english-only` and `--min-decision-signal-score 12` are combined as an AND filter: a candidate must satisfy both before it is sent to the LLM.

## Resume, Deduplication, and Errors

- `--resume-screening` appends to the existing prefixed `screened_results.jsonl` and skips conversations that were already screened.
- Candidate deduplication is enabled by default before LLM screening.
- Retained-case deduplication is enabled by default before final exports.
- Use `--no-dedupe-candidates` only for diagnostics.
- A single LLM failure is recorded in `screened_results.jsonl` and does not stop the whole batch unless `--fail-fast` is set.

To retry only failed LLM rows from an existing screened file:

```bash
uv run python run_pipeline.py \
  --retry-screening-errors data/autonomy_seed_cases/wildchat_screened_results.jsonl \
  --output-prefix wildchat_
```

This reads the existing `screened_results.jsonl`, reruns only rows with an `error` field, rewrites that file in place, and rebuilds:

- `wildchat_summary_report.md`

To rebuild normalized case records and exports from an existing screened file without calling the LLM:

```bash
uv run python run_pipeline.py \
  --rebuild-from-screened data/autonomy_seed_cases/wildchat_screened_results.jsonl \
  --output-prefix wildchat_
```

This rewrites `wildchat_screened_results.jsonl` in place with rebuilt `case` objects and regenerates the downstream exports. Use this after changing label normalization or export logic.

To export full-conversation analysis baselines from an existing screened file:

```bash
uv run python run_pipeline.py \
  --export-full-context-from-screened data/autonomy_seed_cases/wildchat_screened_results.jsonl \
  --full-context-output-dir data/autonomy_seed_cases_full_context \
  --output-prefix wildchat_
```

This writes a second set of files for downstream analysis, keeping the full normalized conversation turns and full conversation text for each retained case:

- `data/autonomy_seed_cases_full_context/wildchat_retained_full_context.jsonl`
- `data/autonomy_seed_cases_full_context/wildchat_full_context_summary.md`

## Outputs

The pipeline now keeps the exported surface minimal:

- `*_candidates.jsonl`: prefiltered candidate conversations
- `*_screened_results.jsonl`: full screening rows, including the normalized conversation inside each `candidate`
- `*_summary_report.md`: aggregate counts and domain/behavior summaries

If you need retained cases for downstream analysis, use the full-context export command. That is the only retained-case export the pipeline produces.

WildChat outputs:

- `data/autonomy_seed_cases/wildchat_candidates.jsonl`
- `data/autonomy_seed_cases/wildchat_screened_results.jsonl`
- `data/autonomy_seed_cases/wildchat_summary_report.md`

ShareGPT outputs:

- `data/autonomy_seed_cases/sharegpt_candidates.jsonl`
- `data/autonomy_seed_cases/sharegpt_screened_results.jsonl`
- `data/autonomy_seed_cases/sharegpt_summary_report.md`

Candidate files preserve full normalized conversations for later screening. `screened_results.jsonl` also keeps the full normalized conversation nested under each `candidate`, while `retained_full_context.jsonl` is the downstream analysis baseline for retained cases.

## Repository Structure

Core pipeline files:

- `run_pipeline.py`: CLI entrypoint and orchestration for prefiltering, LLM screening, resume behavior, and final export.
- `config.py`: dataclass configuration, dataset specs, environment variable loading, and local `.env` support.
- `load_data.py`: Hugging Face dataset streaming and iteration over normalized conversations.
- `normalize.py`: schema normalization for WildChat and ShareGPT into `{source, conversation_id, turns}`.
- `filter_candidates.py`: structural filters, keyword hits, English-likeness scoring, domain inference, and local `decision_signal_score`.
- `candidate_selection.py`: candidate metadata refresh, ranking, English/score filtering, top-N selection, and candidate deduplication before LLM calls.
- `llm_screen.py`: screening prompt, Azure/OpenAI-compatible chat call, strict JSON parsing, and LLM result validation.
- `export_results.py`: JSONL/CSV writers, retained-case schema construction, label normalization, sensitive-detail flags, and summary report generation.

Project and runtime files:

- `pyproject.toml`: uv-managed Python project dependencies.
- `uv.lock`: locked dependency versions.
- `.env.example`: local credentials template.
- `.env`: local credentials file, ignored by git.
- `.gitignore`: ignores local env, data outputs, caches, and virtualenv files.

Generated data directory:

- `data/autonomy_seed_cases/wildchat_*.jsonl|md`: WildChat candidates, screened results, and summary.
- `data/autonomy_seed_cases/sharegpt_*.jsonl|md`: ShareGPT equivalents.
- `data/autonomy_seed_cases_full_context/*_retained_full_context.jsonl`: retained-case baseline exports with full normalized conversation context.

## Practical Scaling Strategy

Start with:

```bash
--english-only --min-decision-signal-score 12 --top-n-for-llm 1000
```

Then scale up in increments:

```bash
--top-n-for-llm 2000
--top-n-for-llm 5000
```

When the retained-case yield drops, lower the threshold to `10` for a second pass, or inspect the rejected score-12 cases before spending more LLM calls.
