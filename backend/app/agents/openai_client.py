"""Azure OpenAI client factory using DefaultAzureCredential."""

from __future__ import annotations

import os

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

_OPENAI_API_VERSION = "2024-02-01"


def get_openai_client() -> AzureOpenAI:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
    if not endpoint:
        raise RuntimeError("AZURE_OPENAI_ENDPOINT env var required")
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )
    return AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=_OPENAI_API_VERSION,
    )
