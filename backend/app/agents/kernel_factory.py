"""Semantic Kernel factory: builds a Kernel wired to Azure OpenAI via DefaultAzureCredential."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def get_kernel(deployment: str):
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from semantic_kernel import Kernel
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    logger.info(
        "Initializing Semantic Kernel AzureChatCompletion with endpoint=%s deployment=%s",
        endpoint,
        deployment,
    )
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
        )
    )
    return kernel
