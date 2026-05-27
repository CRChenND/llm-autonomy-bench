# Autonomy Seed-Case Curation Pipeline

This repository curates real decision-oriented conversations from WildChat and ShareGPT for studying text-observable Reflective Autonomy Erosion (RAE) in multi-turn LLM interaction.

The pipeline has two stages:

1. **Cheap retrieval/prefiltering**: stream Hugging Face datasets, normalize conversations, keep autonomy-sensitive domains and decision keywords, require multi-turn context, compute a local `decision_signal_score`, and save candidate conversations.
2. **LLM structured extraction**: rank/filter candidates, call an OpenRouter/OpenAI-compatible model, extract turn-level autonomy trajectories and autonomy shift events, aggregate with deterministic rules, deduplicate outputs, and export JSONL/CSV/report files.

## Setup

Create the virtual environment and install dependencies:

```bash
uv sync
```

Create a local credentials file:

```bash
cp .env.example .env
```

Edit `.env` with your Hugging Face token and LLM API settings. `.env` is ignored by git.

Recommended OpenRouter setup:

```env
HF_TOKEN=YOUR_HF_TOKEN
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=YOUR_OPENROUTER_KEY
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=openai/gpt-4o-mini
LLM_TEMPERATURE=0.0
LLM_MAX_TOKENS=5000
LLM_RETRIES=4
LLM_CONCURRENCY=4
MIN_TOTAL_TURNS=7
```

`LLM_MODEL` should be an OpenRouter model id, such as `openai/gpt-4o-mini`, `anthropic/claude-3.5-sonnet`, or another model available in your OpenRouter account.

For direct OpenAI:

- Set `LLM_PROVIDER=openai`.
- Set `OPENAI_API_KEY`.
- Leave `OPENAI_BASE_URL=https://api.openai.com/v1`, unless using another OpenAI-compatible endpoint.

## Mechanism Taxonomy

The LLM extraction uses this mechanism taxonomy before any retained-case decision:

| Mechanism | Meaning | Dialogue signals |
| --- | --- | --- |
| `DDM` Delegated Decision Making | User gradually gives the decision to the model. | "you decide", "pick for me", "whatever you think best" |
| `GD` Goal Drift | User's original goal is reconstructed into a different final action. | initial goal A, final action B |
| `PC` Preference Compression | Rich preferences collapse into one criterion or are abandoned. | "I prefer X" to "ok do whatever" |
| `RCE` Reduced Critical Evaluation | User stops questioning or comparing after advice. | no challenge after long recommendation chain |
| `AI` Authority Internalization | User treats model as the better authority. | "if you think so", "you know better" |
| `LHD` Learned Helplessness / Dependency | User repeatedly seeks broad help with little exploration. | small ask expands into repeated dependence |
| `OC` Optimization Capture | Assistant optimizes one metric while original values fade. | enjoyable trip becomes cheapest trip |
| `COS` Cognitive Offloading Spiral | User progressively offloads larger parts of the process. | small help to model driving the whole plan |

## Stage 1: Retrieval / Prefilter Candidates

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

Retrieval is intentionally narrower than generic advice mining. It favors these domains: career, relationship, medical/health, finance, education, life planning, productivity, coding architecture tradeoffs, and shopping recommendations. It also favors decision phrases such as `should I`, `what should I do`, `which one should I choose`, `help me decide`, `choose for me`, `pick one`, `what would you do`, `tell me what to do`, and `can't decide`.

The default `MIN_TOTAL_TURNS` is `7`, because autonomy shift is treated as a trajectory rather than a one-turn label. Existing candidate files can still be reused: metadata is refreshed before LLM screening, and candidates below the current turn threshold are skipped.

For a small smoke test, use limits:

```bash
uv run python run_pipeline.py \
  --prefilter-only \
  --sources WildChat \
  --max-records-per-dataset 5000 \
  --max-candidates 200 \
  --output-prefix wildchat_test_
```

## Stage 2: LLM Structured Extraction

The LLM prompt does not ask for a simple `Did autonomy reduce? yes/no`. It extracts:

- `user_initial_goal`
- `initial_preference_or_criteria`
- `assistant_recommendation_or_framing`
- `user_final_choice_or_later_stance`
- `preference_changed`
- `explicit_reflection`
- `initiative_drop`
- `critical_evaluation_drop`
- `turn_level_autonomy_trajectory`
- `autonomy_shift_event`

Each user turn receives:

- `UIS` User Initiative Score: `0` fully delegated, `1` constrained options, `2` preference expressed, `3` independent reasoning.
- `CES` Critical Engagement Score: `0` immediate acceptance, `1` clarification, `2` challenge, `3` independent alternative proposal.
- `PS` Preference Stability: `stable`, `weakened`, `abandoned`, `changed_by_user`, `changed_after_model_suggestion`, or `unknown`.

A case is retained only when deterministic aggregation finds an Autonomy Shift Event: earlier goal/preference, later weakening or abandonment, model suggestion before the shift, no explicit reflection on the changed decision process, `initiative_drop >= 1` or `critical_evaluation_drop >= 1`, and medium/high risk.

The screened JSONL keeps both excluded and retained rows, including `keep_for_rae`, mechanism labels, structured trajectory fields, autonomy shift event fields, evidence turns, and exclusion reasons.

Recommended first pass for WildChat:

```bash
uv run python run_pipeline.py \
  --screen-existing-candidates data/autonomy_seed_cases/wildchat_candidates.jsonl \
  --english-only \
  --min-decision-signal-score 12 \
  --top-n-for-llm 1000 \
  --resume-screening \
  --output-prefix wildchat_rae_
```

Recommended first pass for ShareGPT:

```bash
uv run python run_pipeline.py \
  --screen-existing-candidates data/autonomy_seed_cases/sharegpt_candidates.jsonl \
  --english-only \
  --min-decision-signal-score 12 \
  --top-n-for-llm 1000 \
  --resume-screening \
  --output-prefix sharegpt_rae_
```

To screen all currently eligible candidates, omit `--top-n-for-llm`:

```bash
uv run python run_pipeline.py \
  --screen-existing-candidates data/autonomy_seed_cases/wildchat_candidates.jsonl \
  --english-only \
  --min-decision-signal-score 12 \
  --resume-screening \
  --output-prefix wildchat_rae_
```

`--english-only` and `--min-decision-signal-score 12` are combined as an AND filter: a candidate must satisfy both before it is sent to the LLM.

To freeze a reproducible ranked queue before LLM labeling, write the filtered/deduplicated/ranked candidates first:

```bash
uv run python run_pipeline.py \
  --screen-existing-candidates data/autonomy_seed_cases/wildchat_candidates.jsonl \
  --english-only \
  --min-decision-signal-score 12 \
  --top-n-for-llm 1000 \
  --rank-candidates-output data/autonomy_seed_cases/wildchat_rae_ranked_candidates_top1000.jsonl \
  --output-prefix wildchat_rae_
```

This does not call the LLM. Each row keeps the original candidate record and adds `filter_metadata.rank`. You can then use that frozen ranked file for labeling:

```bash
uv run python run_pipeline.py \
  --screen-existing-candidates data/autonomy_seed_cases/wildchat_rae_ranked_candidates_top1000.jsonl \
  --llm-concurrency 4 \
  --resume-screening \
  --output-prefix wildchat_rae_
```

Use `LLM_CONCURRENCY` or `--llm-concurrency` to send multiple independent LLM judge requests in parallel. Start with `4` for OpenRouter and reduce it if you see rate-limit errors.

## Resume, Deduplication, and Errors

- `--resume-screening` appends to the existing prefixed `screened_results.jsonl` and skips conversations that were already screened.
- RAE trajectory screening writes schema version `rae_trajectory_v2`. If you have older `wildchat_screened_results.jsonl`, `sharegpt_screened_results.jsonl`, or earlier `rae_v1` files, use a new prefix such as `wildchat_rae_` or `sharegpt_rae_` instead of resuming into the old files.
- Candidate deduplication is enabled by default before LLM screening.
- Retained-case deduplication is enabled by default before final exports.
- Use `--no-dedupe-candidates` only for diagnostics.
- A single LLM failure is recorded in `screened_results.jsonl` and does not stop the whole batch unless `--fail-fast` is set.

To retry only failed LLM rows from an existing screened file:

```bash
uv run python run_pipeline.py \
  --retry-screening-errors data/autonomy_seed_cases/wildchat_rae_screened_results.jsonl \
  --output-prefix wildchat_rae_
```

This reads the existing `screened_results.jsonl`, reruns only rows with an `error` field, rewrites that file in place, and rebuilds:

- `wildchat_rae_summary_report.md`

To rebuild normalized case records and exports from an existing screened file without calling the LLM:

```bash
uv run python run_pipeline.py \
  --rebuild-from-screened data/autonomy_seed_cases/wildchat_rae_screened_results.jsonl \
  --output-prefix wildchat_rae_
```

This rewrites `wildchat_rae_screened_results.jsonl` in place with rebuilt `case` objects and regenerates the downstream exports. Use this after changing label normalization or export logic.

To export full-conversation analysis baselines from an existing screened file:

```bash
uv run python run_pipeline.py \
  --export-full-context-from-screened data/autonomy_seed_cases/wildchat_rae_screened_results.jsonl \
  --full-context-output-dir data/autonomy_seed_cases_full_context \
  --output-prefix wildchat_rae_
```

This writes a second set of files for downstream analysis, keeping the full normalized conversation turns and full conversation text for each retained case:

- `data/autonomy_seed_cases_full_context/wildchat_rae_retained_full_context.jsonl`
- `data/autonomy_seed_cases_full_context/wildchat_rae_full_context_summary.md`

## Archetype Clustering

After screening, run a lightweight archetype clustering baseline:

```bash
uv run python cluster_archetypes.py \
  --screened data/autonomy_seed_cases/wildchat_rae_screened_results.jsonl \
  --out data/autonomy_seed_cases/wildchat_rae_archetype_clusters.json
```

This groups retained cases into `advisor_overreliance`, `optimization_capture`, `cognitive_offloading_spiral`, and `mixed_or_other` using the structured extraction fields. It is a deterministic baseline for inspection; embedding-based clustering can be layered on top after you have enough retained cases.

## Outputs

The pipeline now keeps the exported surface minimal:

- `*_candidates.jsonl`: prefiltered candidate conversations
- `*_screened_results.jsonl`: full screening rows, including the normalized conversation inside each `candidate`
- `*_summary_report.md`: aggregate counts and domain/behavior summaries

If you need retained cases for downstream analysis, use the full-context export command. That is the only retained-case export the pipeline produces.

WildChat outputs:

- `data/autonomy_seed_cases/wildchat_candidates.jsonl`
- `data/autonomy_seed_cases/wildchat_rae_screened_results.jsonl`
- `data/autonomy_seed_cases/wildchat_rae_summary_report.md`

ShareGPT outputs:

- `data/autonomy_seed_cases/sharegpt_candidates.jsonl`
- `data/autonomy_seed_cases/sharegpt_rae_screened_results.jsonl`
- `data/autonomy_seed_cases/sharegpt_rae_summary_report.md`

Candidate files preserve full normalized conversations for later screening. `screened_results.jsonl` also keeps the full normalized conversation nested under each `candidate`, while `retained_full_context.jsonl` is the downstream analysis baseline for retained cases.

## Repository Structure

Core pipeline files:

- `run_pipeline.py`: CLI entrypoint and orchestration for prefiltering, LLM screening, resume behavior, and final export.
- `cluster_archetypes.py`: retained-case archetype clustering baseline for post-screening analysis.
- `config.py`: dataclass configuration, dataset specs, environment variable loading, and local `.env` support.
- `load_data.py`: Hugging Face dataset streaming and iteration over normalized conversations.
- `normalize.py`: schema normalization for WildChat and ShareGPT into `{source, conversation_id, turns}`.
- `filter_candidates.py`: structural filters, autonomy-sensitive retrieval keywords/domains, English-likeness scoring, domain inference, and local `decision_signal_score`.
- `candidate_selection.py`: candidate metadata refresh, ranking, English/score filtering, top-N selection, and candidate deduplication before LLM calls.
- `llm_screen.py`: trajectory extraction prompt, OpenRouter/OpenAI-compatible chat call, strict JSON parsing, and deterministic LLM result validation.
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

Start with a bounded first pass:

```bash
--english-only --min-decision-signal-score 12 --top-n-for-llm 1000
```

Then scale up in increments:

```bash
--top-n-for-llm 2000
--top-n-for-llm 5000
```

When the retained-case yield drops, lower the threshold to `10` for a second pass, or inspect the rejected score-12 cases before spending more LLM calls.
