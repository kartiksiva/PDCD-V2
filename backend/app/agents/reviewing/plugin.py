"""ReviewingPlugin — Semantic Kernel plugin for confidence scoring and review flag generation."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Dict, List

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import (
    AzureChatPromptExecutionSettings,
)
from semantic_kernel.functions import kernel_function

from app.agents.schemas import ReviewFlag, ReviewOutput

logger = logging.getLogger(__name__)


def _parse_review_response(raw: str) -> ReviewOutput:
    """Parse and validate the LLM review response."""
    text = raw.strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines()
            if not line.strip().startswith("```")
        ).strip()
    try:
        data = json.loads(text)
        return ReviewOutput.model_validate(data)
    except Exception as exc:
        logger.error("ReviewingPlugin: failed to parse review response: %s", exc)
        return ReviewOutput(
            decision="needs_review",
            flags=[ReviewFlag(
                code="review_parse_error",
                severity="warning",
                message=f"Reviewing agent response could not be parsed: {exc}",
                requires_user_action=False,
            )],
        )


class ReviewingPlugin:
    """
    Semantic Kernel plugin that runs the LLM-based quality review.

    The rule-based quality gates (schema validation, SIPOC anchor check) are
    run by ReviewingAgent before this plugin is called. This plugin adds
    nuanced confidence scoring and semantic review flags that rules cannot catch.
    """

    def __init__(self, kernel: Kernel, deployment: str) -> None:
        self._kernel = kernel
        self._deployment = deployment

    def _settings(self) -> AzureChatPromptExecutionSettings:
        return AzureChatPromptExecutionSettings(
            deployment_name=self._deployment,
            temperature=0.0,   # deterministic for reviewing
            max_tokens=2048,
        )

    @kernel_function(description="Score draft confidence and generate semantic review flags")
    async def review_draft(
        self,
        draft_json: Annotated[str, "JSON-serialised DraftOutput"],
        evidence_json: Annotated[str, "JSON-serialised EvidenceGraph"],
    ) -> Annotated[str, "JSON-serialised ReviewOutput"]:
        from semantic_kernel.contents import ChatHistory

        system_message = (
            "You are a quality reviewer for process documentation. "
            "Analyse the draft against the evidence and return a JSON object. "
            "Return ONLY a JSON object. No preamble, no markdown fences."
        )
        user_message = f"""Review this process draft for quality, completeness, and evidence alignment.

Draft:
{draft_json}

Evidence:
{evidence_json}

Respond with a single JSON object:
{{
  "decision": "approve_for_draft" | "needs_review" | "blocked",
  "flags": [
    {{
      "code": "short_code",
      "severity": "blocker" | "warning" | "info",
      "message": "description",
      "requires_user_action": true | false
    }}
  ],
  "alignment_verdict": "match" | "inconclusive" | "suspected_mismatch",
  "similarity_score": 0.0,
  "evidence_strength": "high" | "medium" | "low" | "insufficient",
  "confidence_score": 0.0,
  "reviewer_notes": "optional summary"
}}

Decision rules:
- "blocked": any field in the draft is missing required PDD content, or evidence_strength is insufficient
- "needs_review": draft is present but has warnings or reduced confidence
- "approve_for_draft": all required content present and evidence is strong
"""
        history = ChatHistory(system_message=system_message)
        history.add_user_message(user_message)

        service: AzureChatCompletion = self._kernel.get_service(type=AzureChatCompletion)
        result = await service.get_chat_message_contents(
            chat_history=history,
            settings=self._settings(),
            kernel=self._kernel,
        )
        return result[0].content if result else "{}"

    def parse_review(self, raw: str) -> ReviewOutput:
        return _parse_review_response(raw)
