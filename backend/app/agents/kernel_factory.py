"""Semantic Kernel factory: builds a Kernel wired to Azure OpenAI via DefaultAzureCredential."""

from __future__ import annotations

import os

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion


def get_kernel(deployment: str) -> Kernel:
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
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
