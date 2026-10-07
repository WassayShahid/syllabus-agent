"""Claude on Amazon Bedrock (Messages API endpoint) with per-request token logging."""
import os
from functools import cache

import anthropic
from anthropic import AnthropicBedrockMantle

from lib import metrics

DEFAULT_MODEL_ID = "anthropic.claude-opus-5-5"


class RetryableModelError(Exception):
    """Throttling / overload / 5xx after the SDK's own retries. Step Functions retries this."""


class ModelRefusalError(Exception):
    """The model declined the request (stop_reason == "refusal")."""


@cache
def client():
    # Credentials come from the Lambda execution role via the default AWS chain.
    return AnthropicBedrockMantle(aws_region=os.environ.get("AWS_REGION", "us-east-1"), max_retries=3)


def model_id():
    return os.environ.get("MODEL_ID", DEFAULT_MODEL_ID)


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
