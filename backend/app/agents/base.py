"""Base agent: Semantic Kernel factory and cost tracking helpers."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from azure.identity import DefaultAzureCredential
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

from app.job_logic import add_agent_run

logger = logging.getLogger(__name__)

# Per-token cost estimates in USD (approximate, update as Azure pricing changes)
_COST_PER_1K_TOKENS: Dict[str, float] = {
    "gpt-4.1-mini": 0.00015,
    "gpt-4o": 0.005,
    "gpt-4o-mini": 0.00015,
}

_DEPLOYMENT_BY_PROFILE = {
    "balanced": os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_BALANCED", "gpt-4.1-mini"),
    "quality": os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_QUALITY", "gpt-4o"),
}


def _build_kernel(profile: str) -> Kernel:
    """Create a Semantic Kernel instance wired to Azure OpenAI for the given profile."""
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    deployment = _DEPLOYMENT_BY_PROFILE.get(profile, "gpt-4.1-mini")

    kernel = Kernel()
    if endpoint:
        kernel.add_service(
            AzureChatCompletion(
                deployment_name=deployment,
                endpoint=endpoint,
                credential=DefaultAzureCredential(),
            )
        )
        logger.debug("SK kernel built: profile=%s deployment=%s", profile, deployment)
    else:
        logger.warning(
            "AZURE_OPENAI_ENDPOINT not set; SK kernel created without LLM service. "
            "Agent LLM calls will fail at runtime."
        )
    return kernel


def estimate_cost(token_count: int, profile: str) -> float:
    """Return a USD cost estimate for the given token count and profile."""
    deployment = _DEPLOYMENT_BY_PROFILE.get(profile, "gpt-4.1-mini")
    rate = _COST_PER_1K_TOKENS.get(deployment, 0.0)
    return round((token_count / 1000) * rate, 6)


class BaseAgent:
    """
    Base class for all PFCD agents.

    Provides:
    - Semantic Kernel instance (`self.kernel`) wired to Azure OpenAI
    - Deployment name for the resolved profile (`self.deployment`)
    - Elapsed-time tracking helpers
    - `record_run()` convenience method to append an agent_run entry to the job payload
    """

    def __init__(self, agent_name: str, profile: str, job: Dict[str, Any]) -> None:
        self.agent_name = agent_name
        self.profile = profile
        self.job = job
        self.deployment = _DEPLOYMENT_BY_PROFILE.get(profile, "gpt-4.1-mini")
        self.kernel = _build_kernel(profile)
        self._start_time: Optional[float] = None

    def _start_timer(self) -> None:
        self._start_time = time.monotonic()

    def _elapsed_ms(self) -> int:
        if self._start_time is None:
            return 0
        return int((time.monotonic() - self._start_time) * 1000)

    def record_run(
        self,
        status: str,
        *,
        token_count: int = 0,
        confidence_delta: float = 0.0,
        message: Optional[str] = None,
    ) -> str:
        """Append an agent_run entry to self.job and return the run_id."""
        cost = estimate_cost(token_count, self.profile)
        run_id = add_agent_run(
            self.job,
            agent=self.agent_name,
            profile=self.profile,
            status=status,
            model=self.deployment,
            duration_ms=self._elapsed_ms(),
            cost=cost,
            confidence_delta=confidence_delta,
            message=message,
        )
        logger.info(
            "agent_run recorded: agent=%s status=%s tokens=%d cost=$%.6f duration=%dms",
            self.agent_name, status, token_count, cost, self._elapsed_ms(),
        )
        return run_id
