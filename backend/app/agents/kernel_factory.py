"""Semantic Kernel factory for Azure OpenAI and direct OpenAI providers."""

from __future__ import annotations

import logging
import os

from app.job_logic import _provider_name

logger = logging.getLogger(__name__)

_DEFAULT_AZURE_OPENAI_API_VERSION = "2024-10-21"


def _build_kernel_azure(endpoint: str, deployment: str, api_version: str):
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from semantic_kernel import Kernel
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    kernel = Kernel()
    kernel.add_service(
        AzureChatCompletion(
            deployment_name=deployment,
            endpoint=endpoint,
            ad_token_provider=token_provider,
            api_version=api_version,
        )
    )
    return kernel


def _build_kernel_openai(api_key: str, model: str):
    from semantic_kernel import Kernel
    from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion

    kernel = Kernel()
    kernel.add_service(OpenAIChatCompletion(ai_model_id=model, api_key=api_key))
    return kernel


def get_kernel(deployment: str):
    provider = _provider_name()
    if provider == "openai":
        logger.info(
            "Initializing Semantic Kernel OpenAIChatCompletion with model=%s",
            deployment,
        )
        return _build_kernel_openai(os.environ["OPENAI_API_KEY"], deployment)

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", _DEFAULT_AZURE_OPENAI_API_VERSION)
    logger.info(
        "Initializing Semantic Kernel AzureChatCompletion with endpoint=%s deployment=%s api_version=%s",
        endpoint,
        deployment,
        api_version,
    )
    return _build_kernel_azure(endpoint, deployment, api_version)


def get_chat_service(deployment: str):
    """Return the chat completion service for the active provider."""
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion, OpenAIChatCompletion

    kernel = get_kernel(deployment)
    if _provider_name() == "openai":
        return kernel.get_service(type=OpenAIChatCompletion)  # type: ignore[arg-type]
    return kernel.get_service(type=AzureChatCompletion)  # type: ignore[arg-type]
