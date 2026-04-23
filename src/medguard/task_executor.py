from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from .models import Principal, ToolCall


@dataclass(slots=True)
class TaskExecutorStatus:
    enabled: bool
    model: str | None
    reason: str


EXECUTOR_DEVELOPER_PROMPT = (
    "You are the MedGuard healthcare assistant. "
    "Use the approved tool result and the recent conversation context to answer the user. "
    "Do not invent protected medical data that is not present in the approved tool result. "
    "If the approved tool result is a conversation note, respond naturally and briefly without claiming new permissions or authentication. "
    "If the tool result indicates a limitation or refusal, explain that clearly and briefly."
)


class OpenAITaskExecutor:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("MEDGUARD_CHAT_MODEL", "gpt-4o-mini")
        self.timeout_seconds = timeout_seconds

    def status(self) -> TaskExecutorStatus:
        if not self.api_key:
            return TaskExecutorStatus(
                enabled=False,
                model=None,
                reason="OPENAI_API_KEY is not set. GPT task execution is unavailable.",
            )
        return TaskExecutorStatus(
            enabled=True,
            model=self.model,
            reason="GPT task execution is available through the OpenAI Responses API.",
        )

    def execute(
        self,
        principal: Principal,
        user_message: str,
        tool_call: ToolCall,
        tool_result: str,
        history: list[dict] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            return {
                "executed": False,
                "source": "executor_unavailable",
                "model": None,
                "response": tool_result,
                "error": "GPT task execution is unavailable because OPENAI_API_KEY is not set.",
            }

        body = {
            "model": self.model,
            "input": [
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": EXECUTOR_DEVELOPER_PROMPT,
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": json.dumps(
                                {
                                    "principal": principal.to_dict(),
                                    "user_message": user_message,
                                    "tool_call": tool_call.to_dict(),
                                    "approved_tool_result": tool_result,
                                    "recent_history": (history or [])[-6:],
                                }
                            ),
                        }
                    ],
                },
            ],
        }

        req = request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            return {
                "executed": False,
                "source": "executor_error",
                "model": self.model,
                "response": tool_result,
                "error": f"GPT task execution failed with HTTP {exc.code}: {detail}",
            }
        except error.URLError as exc:
            return {
                "executed": False,
                "source": "executor_error",
                "model": self.model,
                "response": tool_result,
                "error": f"GPT task execution failed: {exc.reason}",
            }

        output_text = self._extract_output_text(data)
        if not output_text:
            return {
                "executed": False,
                "source": "executor_error",
                "model": self.model,
                "response": tool_result,
                "error": "GPT task execution returned no parseable text output.",
            }

        return {
            "executed": True,
            "source": "openai",
            "model": self.model,
            "response": output_text,
            "error": None,
        }

    @staticmethod
    def _extract_output_text(data: dict[str, Any]) -> str | None:
        if isinstance(data.get("output_text"), str) and data["output_text"]:
            return data["output_text"]

        for item in data.get("output", []):
            for content in item.get("content", []):
                text_value = content.get("text")
                if isinstance(text_value, str) and text_value:
                    return text_value
        return None
