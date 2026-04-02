"""ProcessingPlugin — Semantic Kernel plugin for step extraction and PDD/SIPOC generation."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import (
    AzureChatPromptExecutionSettings,
)
from semantic_kernel.functions import kernel_function

from app.agents.schemas import DraftOutput, PDDOutput, PDDStep, SIPOCRow

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    """Load a prompt template from the prompts/ directory."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    with open(path) as f:
        return f.read()


def _parse_json_response(raw: str, label: str) -> Any:
    """Strip any accidental markdown fences and parse JSON."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("ProcessingPlugin: JSON parse error in %s response: %s", label, exc)
        raise


class ProcessingPlugin:
    """
    Semantic Kernel plugin that drives the Processing Agent LLM calls.

    Each @kernel_function takes serialised JSON as input and returns
    a JSON string that the ProcessingAgent parses into Pydantic models.
    """

    def __init__(self, kernel: Kernel, deployment: str) -> None:
        self._kernel = kernel
        self._deployment = deployment

    def _settings(self, temperature: float = 0.2, max_tokens: int = 4096) -> AzureChatPromptExecutionSettings:
        return AzureChatPromptExecutionSettings(
            deployment_name=self._deployment,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @kernel_function(description="Extract structured process steps from evidence objects")
    async def extract_steps(
        self,
        evidence_json: Annotated[str, "JSON-serialised list of EvidenceObject dicts"],
    ) -> Annotated[str, "JSON array of PDDStep objects"]:
        from semantic_kernel.contents import ChatHistory
        prompt_yaml = _load_prompt("extract_steps")

        # Build the user message directly from the template variables
        user_message = (
            "Evidence (JSON array):\n" + evidence_json +
            "\n\nExtract process steps following the rules above."
        )
        system_message = (
            "You are a process analyst specialising in extracting business process steps "
            "from recorded evidence. Return ONLY a JSON array of step objects. "
            "No preamble, no markdown fences."
        )
        history = ChatHistory(system_message=system_message)
        history.add_user_message(user_message)

        service: AzureChatCompletion = self._kernel.get_service(type=AzureChatCompletion)
        result = await service.get_chat_message_contents(
            chat_history=history,
            settings=self._settings(temperature=0.2, max_tokens=4096),
            kernel=self._kernel,
        )
        return result[0].content if result else "[]"

    @kernel_function(description="Generate a PDD document from extracted process steps")
    async def generate_pdd(
        self,
        steps_json: Annotated[str, "JSON array of PDDStep objects"],
        context_json: Annotated[str, "JSON object with source_quality and profile"],
    ) -> Annotated[str, "JSON object matching PDDOutput schema"]:
        from semantic_kernel.contents import ChatHistory

        user_message = (
            "Process Steps:\n" + steps_json +
            "\n\nJob Context:\n" + context_json +
            "\n\nGenerate the PDD following the rules above."
        )
        system_message = (
            "You are a process documentation specialist. "
            "Generate a complete Process Definition Document. "
            "Return ONLY a JSON object. No preamble, no markdown fences."
        )
        history = ChatHistory(system_message=system_message)
        history.add_user_message(user_message)

        service: AzureChatCompletion = self._kernel.get_service(type=AzureChatCompletion)
        result = await service.get_chat_message_contents(
            chat_history=history,
            settings=self._settings(temperature=0.1, max_tokens=4096),
            kernel=self._kernel,
        )
        return result[0].content if result else "{}"

    @kernel_function(description="Generate a SIPOC map from process steps and evidence")
    async def generate_sipoc(
        self,
        steps_json: Annotated[str, "JSON array of PDDStep objects"],
        evidence_json: Annotated[str, "JSON array of EvidenceObject dicts"],
    ) -> Annotated[str, "JSON array of SIPOCRow objects"]:
        from semantic_kernel.contents import ChatHistory

        user_message = (
            "Process Steps:\n" + steps_json +
            "\n\nEvidence:\n" + evidence_json +
            "\n\nGenerate the SIPOC map following the rules above."
        )
        system_message = (
            "You are a process documentation specialist. "
            "Generate a single consolidated SIPOC map. "
            "Return ONLY a JSON array. No preamble, no markdown fences."
        )
        history = ChatHistory(system_message=system_message)
        history.add_user_message(user_message)

        service: AzureChatCompletion = self._kernel.get_service(type=AzureChatCompletion)
        result = await service.get_chat_message_contents(
            chat_history=history,
            settings=self._settings(temperature=0.1, max_tokens=2048),
            kernel=self._kernel,
        )
        return result[0].content if result else "[]"

    # ------------------------------------------------------------------
    # Parsing helpers (called by ProcessingAgent)
    # ------------------------------------------------------------------

    def parse_steps(self, raw: str) -> List[PDDStep]:
        data = _parse_json_response(raw, "extract_steps")
        steps = []
        for i, item in enumerate(data if isinstance(data, list) else []):
            try:
                steps.append(PDDStep.model_validate(item))
            except Exception as exc:
                logger.warning("ProcessingPlugin: invalid step at index %d: %s", i, exc)
        return steps

    def parse_pdd(self, raw: str, steps: List[PDDStep]) -> PDDOutput:
        data = _parse_json_response(raw, "generate_pdd")
        # Enforce that the parsed steps (already validated) override whatever the LLM returned
        data["steps"] = [s.model_dump() for s in steps]
        return PDDOutput.model_validate(data)

    def parse_sipoc(self, raw: str) -> List[SIPOCRow]:
        data = _parse_json_response(raw, "generate_sipoc")
        rows = []
        for i, item in enumerate(data if isinstance(data, list) else []):
            try:
                rows.append(SIPOCRow.model_validate(item))
            except Exception as exc:
                logger.warning("ProcessingPlugin: invalid SIPOC row at index %d: %s", i, exc)
        return rows
