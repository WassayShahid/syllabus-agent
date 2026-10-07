"""Claude on Amazon Bedrock with per-request token logging.

Two Bedrock paths, picked from the model ID:
- cross-region inference profiles (`global.` / `us.` / `eu.` ... prefix, e.g. Claude Sonnet 4.6)
  go through bedrock-runtime InvokeModel (`AnthropicBedrock`)
- bare `anthropic.` IDs (Claude Opus 4.7 and later) go through the Messages API endpoint
  (`AnthropicBedrockMantle`)
Both expose the same `messages.create`.
"""
import os
from functools import cache

import anthropic
from anthropic import AnthropicBedrock, AnthropicBedrockMantle

from lib import metrics

DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-6"


class RetryableModelError(Exception):
    """Throttling / overload / 5xx after the SDK's own retries. Step Functions retries this."""


class ModelRefusalError(Exception):
    """The model declined the request (stop_reason == "refusal")."""


def model_id():
    return os.environ.get("MODEL_ID", DEFAULT_MODEL_ID)


def uses_invoke_model(model):
    return not model.startswith("anthropic.")


@cache
def client():
    # Credentials come from the Lambda execution role via the default AWS chain.
    region = os.environ.get("AWS_REGION", "us-east-1")
    if uses_invoke_model(model_id()):
        return AnthropicBedrock(aws_region=region, max_retries=3)
    return AnthropicBedrockMantle(aws_region=region, max_retries=3)


def create(operation, **kwargs):
    """messages.create + EMF token metrics. Retryable failures are re-raised as RetryableModelError."""
    try:
        response = client().messages.create(model=model_id(), **kwargs)
    except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APIConnectionError) as e:
        raise RetryableModelError(str(e)) from e

    usage = response.usage
    metrics.emit(
        operation,
        {
            "InputTokens": usage.input_tokens,
            "OutputTokens": usage.output_tokens,
            "CacheReadInputTokens": getattr(usage, "cache_read_input_tokens", None) or 0,
        },
        model=model_id(),
        stopReason=response.stop_reason,
    )

    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise ModelRefusalError(getattr(details, "explanation", None) or "model declined the request")
    return response


def text_of(response):
    return "".join(b.text for b in response.content if b.type == "text").strip()
