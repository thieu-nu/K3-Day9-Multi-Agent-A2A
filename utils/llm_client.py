from __future__ import annotations

import json
import os
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from together import AsyncTogether

QWEN_MODEL = "Qwen/Qwen3.5-9B"
QWEN_PARAMETER_SIZE_B = 9.0
QWEN_PROVIDER = "together"

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class LlmConfigurationError(RuntimeError):
    pass


class TogetherStructuredClient:
    """Small typed adapter around Together's Qwen structured-output API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
        structured_parse_retries: int = 2,
    ) -> None:
        resolved_key = api_key or os.getenv("TOGETHER_API_KEY")
        if not resolved_key:
            raise LlmConfigurationError(
                "TOGETHER_API_KEY is required; store it in .env, never in source code"
            )

        self._client = AsyncTogether(
            api_key=resolved_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )
        self._structured_parse_retries = structured_parse_retries

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
        schema_name: str,
        max_tokens: int = 2_048,
    ) -> ResponseModel:
        schema = response_model.model_json_schema()
        last_error: Exception | None = None
        total_attempts = self._structured_parse_retries + 1
        for parse_attempt in range(1, total_attempts + 1):
            response = await self._client.chat.completions.create(
                model=QWEN_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"{system_prompt}\n\n"
                            "Return compact JSON only and follow this JSON Schema exactly. "
                            "Keep summary and issue text concise:\n"
                            f"{json.dumps(schema, ensure_ascii=False, sort_keys=True)}"
                        ),
                    },
                    {"role": "user", "content": user_prompt},
                ],
                reasoning={"enabled": False},
                temperature=0,
                max_tokens=max_tokens,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": schema},
                },
            )

            choice = response.choices[0]
            message = choice.message
            content = message.content if message is not None else None
            if not content:
                last_error = RuntimeError("Together returned an empty structured response")
            else:
                try:
                    return response_model.model_validate_json(content)
                except ValidationError as exc:
                    finish_reason = getattr(choice, "finish_reason", "unknown")
                    last_error = RuntimeError(
                        "Together returned invalid structured JSON "
                        f"(attempt {parse_attempt}/{total_attempts}, "
                        f"finish_reason={finish_reason}): {exc.errors()[0]['msg']}"
                    )

        raise RuntimeError(
            f"Together structured output failed after {total_attempts} attempts: {last_error}"
        ) from last_error
