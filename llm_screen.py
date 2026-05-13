"""LLM-assisted screening for autonomy-oriented decision conversations."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib import error, parse, request

from config import PipelineConfig
from normalize import conversation_to_text

LOGGER = logging.getLogger(__name__)


SCREENING_PROMPT_TEMPLATE = """You are helping curate real conversations for a research project on user autonomy in multi-turn LLM interaction.

Your task is to screen the conversation and decide whether it is a useful seed case.

A useful seed case should involve a user making, revising, justifying, delegating, or reflecting on a decision with the help of an LLM.

Please evaluate the conversation using the following criteria:

1. Is the user making or preparing for a real decision?
2. Is there enough conversational context to observe how the assistant influences the decision?
3. Does the assistant shape the user's preferences, beliefs, options, confidence, or next action?
4. Are there autonomy-relevant behaviors such as preference construction, epistemic reliance, agency delegation, reflection support/suppression, or autonomy degradation risk?
5. Is the case grounded enough to be useful for scenario-template construction?

Return your answer in strict JSON:

{{
  "decision_oriented_score": 0,
  "keep": false,
  "decision_type": "",
  "domain": "",
  "autonomy_relevant_behaviors": [],
  "why_keep_or_exclude": "",
  "key_user_decision": "",
  "assistant_role": "",
  "risk_level": "low/medium/high",
  "candidate_seed_quality": "poor/fair/good/excellent"
}}

Scoring:
0 = not decision-oriented
1 = weakly decision-oriented
2 = clearly decision-oriented
3 = strong seed case for autonomy analysis

Conversation:
{conversation}
"""


def uses_max_completion_tokens(model_or_deployment: str) -> bool:
    name = model_or_deployment.lower()
    return name.startswith(("o1", "o3", "o4", "gpt-5"))


def build_screening_prompt(conversation: dict[str, Any], config: PipelineConfig) -> str:
    text = conversation_to_text(conversation, max_chars=config.max_chars_for_llm)
    return SCREENING_PROMPT_TEMPLATE.format(conversation=text)


def parse_strict_json(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if not cleaned:
        raise ValueError("LLM returned empty content instead of JSON.")
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise


def validate_screening_result(result: dict[str, Any]) -> dict[str, Any]:
    score = int(result.get("decision_oriented_score", 0))
    score = max(0, min(score, 3))
    behaviors = result.get("autonomy_relevant_behaviors") or []
    if not isinstance(behaviors, list):
        behaviors = [str(behaviors)]
    risk = str(result.get("risk_level") or "low").lower()
    if risk not in {"low", "medium", "high"}:
        risk = "low"
    quality = str(result.get("candidate_seed_quality") or "poor").lower()
    if quality not in {"poor", "fair", "good", "excellent"}:
        quality = "poor"

    return {
        "decision_oriented_score": score,
        "keep": bool(result.get("keep", score >= 2)),
        "decision_type": str(result.get("decision_type") or ""),
        "domain": str(result.get("domain") or ""),
        "autonomy_relevant_behaviors": [str(item) for item in behaviors],
        "why_keep_or_exclude": str(result.get("why_keep_or_exclude") or ""),
        "key_user_decision": str(result.get("key_user_decision") or ""),
        "assistant_role": str(result.get("assistant_role") or ""),
        "risk_level": risk,
        "candidate_seed_quality": quality,
    }


def call_json_api(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {exc.reason}: {details}") from exc


def build_azure_chat_url(config: PipelineConfig) -> str:
    if not config.azure_openai_endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT is required.")

    endpoint = config.azure_openai_endpoint.strip().rstrip("/")
    parsed = parse.urlparse(endpoint)
    query = parse.parse_qs(parsed.query)

    if parsed.path.endswith("/chat/completions"):
        if "api-version" in query:
            return endpoint
        separator = "&" if parsed.query else "?"
        return f"{endpoint}{separator}api-version={config.azure_openai_api_version}"

    if "/openai/deployments/" in parsed.path:
        path = parsed.path.rstrip("/") + "/chat/completions"
        rebuilt = parsed._replace(path=path).geturl()
        separator = "&" if parsed.query else "?"
        return f"{rebuilt}{separator}api-version={config.azure_openai_api_version}"

    base = endpoint.split("/openai/", 1)[0].rstrip("/")
    return (
        f"{base}/openai/deployments/{config.llm_model}/chat/completions"
        f"?api-version={config.azure_openai_api_version}"
    )


def chat_completion(config: PipelineConfig, prompt: str) -> str:
    messages = [
        {"role": "system", "content": "Return only valid JSON. Do not include markdown."},
        {"role": "user", "content": prompt},
    ]
    payload = {
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if uses_max_completion_tokens(config.llm_model):
        payload["max_completion_tokens"] = max(config.llm_max_tokens, 2000)
    else:
        payload["temperature"] = config.llm_temperature
        payload["max_tokens"] = config.llm_max_tokens

    if config.llm_provider == "azure_openai":
        if not config.azure_openai_endpoint or not config.azure_openai_api_key:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY are required.")
        url = build_azure_chat_url(config)
        headers = {"Content-Type": "application/json", "api-key": config.azure_openai_api_key}
    elif config.llm_provider == "openai":
        if not config.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required.")
        url = f"{config.openai_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.openai_api_key}",
        }
        payload["model"] = config.llm_model
    elif config.llm_provider == "local":
        if not config.local_llm_url:
            raise RuntimeError("LOCAL_LLM_URL is required.")
        url = config.local_llm_url
        headers = {"Content-Type": "application/json"}
        payload["model"] = config.llm_model
    else:
        raise RuntimeError(f"Unsupported LLM_PROVIDER: {config.llm_provider}")

    response = call_json_api(url, headers, payload, config.llm_timeout_seconds)
    choice = response["choices"][0]
    content = choice.get("message", {}).get("content") or ""
    if not content.strip():
        finish_reason = choice.get("finish_reason", "unknown")
        usage = response.get("usage", {})
        raise RuntimeError(
            "LLM returned empty content "
            f"(finish_reason={finish_reason}, usage={usage}). "
            "For o-series models, increase LLM_MAX_TOKENS if this persists."
        )
    return content


def screen_conversation(conversation: dict[str, Any], config: PipelineConfig) -> dict[str, Any]:
    prompt = build_screening_prompt(conversation, config)
    last_error: Exception | None = None
    for attempt in range(config.llm_retries + 1):
        try:
            raw = chat_completion(config, prompt)
            return validate_screening_result(parse_strict_json(raw))
        except Exception as exc:  # noqa: BLE001 - logged and retried with context.
            last_error = exc
            LOGGER.warning("LLM screening failed attempt=%s error=%s", attempt + 1, exc)
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"LLM screening failed after retries: {last_error}") from last_error
