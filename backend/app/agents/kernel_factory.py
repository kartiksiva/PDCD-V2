"""Semantic Kernel factory: builds a Kernel wired to Azure OpenAI via DefaultAzureCredential."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)

_DEFAULT_AZURE_OPENAI_API_VERSION = "2024-10-21"


@lru_cache(maxsize=8)
def _cached_kernel(endpoint: str, deployment: str, api_version: str):
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


def get_kernel(deployment: str):
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", _DEFAULT_AZURE_OPENAI_API_VERSION)
    logger.info(
        "Initializing Semantic Kernel AzureChatCompletion with endpoint=%s deployment=%s api_version=%s",
        endpoint,
        deployment,
        api_version,
    )
    return _cached_kernel(endpoint, deployment, api_version)
