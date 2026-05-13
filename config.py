"""Configuration for the autonomy seed-case curation pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_DECISION_KEYWORDS = [
    "should i",
    "what should i do",
    "help me decide",
    "choose",
    "decide",
    "pick",
    "recommend",
    "compare",
    "better option",
    "best option",
    "advice",
    "suggestion",
    "is it okay",
    "is it worth it",
    "do you think",
    "would you",
    "plan",
    "schedule",
    "strategy",
    "roadmap",
    "next step",
    "timeline",
    "prioritize",
    "reply",
    "respond",
    "email",
    "message",
    "apologize",
    "negotiate",
    "ask",
    "tell them",
    "say to",
    "job",
    "career",
    "school",
    "college",
    "phd",
    "visa",
    "immigration",
    "legal",
    "medical",
    "health",
    "therapy",
    "finance",
    "investment",
    "rent",
    "lease",
    "relationship",
]


@dataclass(frozen=True)
class DatasetSpec:
    source: str
    hf_name: str
    split: str = "train"
    config_name: Optional[str] = None


@dataclass(frozen=True)
class PipelineConfig:
    output_dir: Path = Path("data/autonomy_seed_cases")
    hf_token: Optional[str] = None
    stream_datasets: bool = True
    max_records_per_dataset: Optional[int] = 5000
    min_user_turns: int = 2
    min_total_turns: int = 4
    min_chars: int = 500
    max_chars_for_llm: int = 12000
    representative_excerpt_chars: int = 600
    decision_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_DECISION_KEYWORDS))
    datasets: tuple[DatasetSpec, ...] = (
        DatasetSpec(source="WildChat", hf_name="allenai/WildChat"),
        DatasetSpec(source="ShareGPT", hf_name="RyokoAI/ShareGPT52K"),
    )

    llm_provider: str = "azure_openai"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 2000
    llm_timeout_seconds: int = 60
    llm_retries: int = 2
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: str = "2024-02-15-preview"
    openai_api_key: Optional[str] = None
    openai_base_url: str = "https://api.openai.com/v1"
    local_llm_url: Optional[str] = None


def load_dotenv(path: Path = Path(".env")) -> dict[str, str]:
    """Read simple KEY=VALUE pairs from a local dotenv file."""

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            raise ValueError(f"Invalid dotenv line {line_number} in {path}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            raise ValueError(f"Invalid dotenv line {line_number} in {path}: empty key")
        values[key] = value
    return values


def env_value(name: str, dotenv_values: dict[str, str], default: Optional[str] = None) -> Optional[str]:
    return os.getenv(name) or dotenv_values.get(name) or default


def load_config_from_env() -> PipelineConfig:
    """Load configuration from environment variables and optional local .env file.

    Real environment variables take precedence over values from .env.
    """

    dotenv_values = load_dotenv()
    max_records = env_value("MAX_RECORDS_PER_DATASET", dotenv_values)
    return PipelineConfig(
        output_dir=Path(env_value("OUTPUT_DIR", dotenv_values, "data/autonomy_seed_cases") or "data/autonomy_seed_cases"),
        hf_token=env_value("HF_TOKEN", dotenv_values) or env_value("HUGGINGFACE_TOKEN", dotenv_values),
        stream_datasets=(env_value("STREAM_DATASETS", dotenv_values, "true") or "true").lower() != "false",
        max_records_per_dataset=int(max_records) if max_records else 5000,
        min_user_turns=int(env_value("MIN_USER_TURNS", dotenv_values, "2") or "2"),
        min_total_turns=int(env_value("MIN_TOTAL_TURNS", dotenv_values, "4") or "4"),
        min_chars=int(env_value("MIN_CHARS", dotenv_values, "500") or "500"),
        max_chars_for_llm=int(env_value("MAX_CHARS_FOR_LLM", dotenv_values, "12000") or "12000"),
        representative_excerpt_chars=int(env_value("REPRESENTATIVE_EXCERPT_CHARS", dotenv_values, "600") or "600"),
        llm_provider=env_value("LLM_PROVIDER", dotenv_values, "azure_openai") or "azure_openai",
        llm_model=env_value("LLM_MODEL", dotenv_values, "gpt-4o-mini") or "gpt-4o-mini",
        llm_temperature=float(env_value("LLM_TEMPERATURE", dotenv_values, "0.0") or "0.0"),
        llm_max_tokens=int(env_value("LLM_MAX_TOKENS", dotenv_values, "2000") or "2000"),
        llm_timeout_seconds=int(env_value("LLM_TIMEOUT_SECONDS", dotenv_values, "60") or "60"),
        llm_retries=int(env_value("LLM_RETRIES", dotenv_values, "2") or "2"),
        azure_openai_endpoint=env_value("AZURE_OPENAI_ENDPOINT", dotenv_values),
        azure_openai_api_key=env_value("AZURE_OPENAI_API_KEY", dotenv_values),
        azure_openai_api_version=env_value(
            "AZURE_OPENAI_API_VERSION",
            dotenv_values,
            "2024-02-15-preview",
        )
        or "2024-02-15-preview",
        openai_api_key=env_value("OPENAI_API_KEY", dotenv_values),
        openai_base_url=env_value("OPENAI_BASE_URL", dotenv_values, "https://api.openai.com/v1")
        or "https://api.openai.com/v1",
        local_llm_url=env_value("LOCAL_LLM_URL", dotenv_values),
    )
