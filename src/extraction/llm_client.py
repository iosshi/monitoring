import os
import re
import ssl
import time
import json

import certifi
from dotenv import load_dotenv
from openai import (
    OpenAI,
    DefaultHttpx2Client,
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    RateLimitError,
)
from pydantic import ValidationError

from src.extraction.schemas import AnalysisRequest, AnalysisResult
from src.extraction.prompts import SYSTEM_PROMPT, build_user_prompt


load_dotenv()


def _retry_delay(error: Exception, attempt: int, floor_seconds: float = 0.0) -> float:
    delay = max(float(2 ** (attempt - 1)), floor_seconds)
    message = str(error)
    match = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|seconds?)\b",
                      message, flags=re.IGNORECASE)
    if match:
        suggested = float(match.group(1))
        if match.group(2).lower().startswith("m"):
            suggested /= 1000
        delay = max(delay, suggested)
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("retry-after") if hasattr(headers, "get") else None
    if retry_after:
        try:
            delay = max(delay, float(retry_after))
        except (TypeError, ValueError):
            pass
    return delay


class GroqClient:
    def __init__(self, retry_delay_floor_seconds: float = 0.0):
        api_key = os.getenv("GROQ_API_KEY")

        if not api_key:
            raise ValueError("GROQ_API_KEY not found")

        timeout_seconds = float(os.getenv("GROQ_TIMEOUT_SECONDS", "90"))
        if timeout_seconds <= 0:
            raise ValueError("GROQ_TIMEOUT_SECONDS must be greater than zero")

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            timeout=timeout_seconds,
            max_retries=0,
            http_client=DefaultHttpx2Client(
                verify=ssl.create_default_context(cafile=certifi.where()),
                trust_env=False,
            ),
        )

        self.model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        self.max_attempts = 3
        self.retry_delay_floor_seconds = max(0.0, retry_delay_floor_seconds)
        self.call_count = 0
        self.last_usage = None
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def analyze(self, request: AnalysisRequest) -> AnalysisResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(request)},
        ]
        for attempt in range(1, self.max_attempts + 1):
            retryable = False
            last_error = None
            invalid_content = None
            try:
                self.call_count += 1
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0,
                    max_tokens=4096,
                )

                content = response.choices[0].message.content
                self.last_usage = response.usage
                if response.usage is not None:
                    self.total_prompt_tokens += response.usage.prompt_tokens or 0
                    self.total_completion_tokens += response.usage.completion_tokens or 0

                if not content or not content.strip():
                    raise ValueError("Groq returned an empty response")

                try:
                    payload = json.loads(content)
                    if isinstance(payload, dict) and isinstance(payload.get("changes"), list):
                        # Models sometimes emit an empty string as a list item.
                        # It carries no change data, so remove only blank strings;
                        # all other schema violations still go through validation.
                        payload["changes"] = [
                            item for item in payload["changes"]
                            if not (isinstance(item, str) and not item.strip())
                        ]
                    return AnalysisResult.model_validate(payload)
                except (json.JSONDecodeError, ValidationError) as caught_error:
                    invalid_content = content
                    raise caught_error

            except (
                APIConnectionError,
                APITimeoutError,
                RateLimitError,
                ValidationError,
                ValueError,
            ) as caught_error:
                last_error = caught_error
                retryable = True

            except APIStatusError as caught_error:
                last_error = caught_error
                retryable = caught_error.status_code >= 500

            if last_error is None:
                raise RuntimeError("LLM attempt ended without a result or a captured error")
            if not retryable or attempt == self.max_attempts:
                raise last_error

            if invalid_content is not None:
                messages.extend([
                    {"role": "assistant", "content": invalid_content},
                    {
                        "role": "user",
                        "content": (
                            "Исправь предыдущий JSON целиком. Он не прошёл проверку "
                            f"схемы: {last_error}. Верни только один JSON-объект, "
                            "точно соответствующий схеме из system-инструкции. "
                            "Каждый элемент changes должен быть объектом; если "
                            "изменений нет, верни пустой массив []."
                        ),
                    },
                ])

            delay = _retry_delay(
                last_error,
                attempt,
                floor_seconds=self.retry_delay_floor_seconds,
            )
            print(
                f"LLM request failed (attempt {attempt}/"
                f"{self.max_attempts}): {last_error}"
            )
            print(f"Retrying in {delay} seconds...")
            time.sleep(delay)
