"""Titan text embeddings + a tiny in-memory vector search.

Each user has a handful of syllabi (a few hundred chunks), so brute-force cosine over
chunks stored in DynamoDB is fast and costs nothing at rest. See README "Trade-offs".
"""
import json
import math
from array import array

from lib import aws, metrics

EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
DIMENSIONS = 512


def embed(text, operation="embed"):
    resp = aws.bedrock_runtime().invoke_model(
        modelId=EMBEDDING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"inputText": text, "dimensions": DIMENSIONS, "normalize": True}),
    )
    body = json.loads(resp["body"].read())
    metrics.emit(operation, {"EmbeddingTokens": body.get("inputTextTokenCount", 0)}, model=EMBEDDING_MODEL_ID)
    return body["embedding"]


def pack(vector):
    return array("f", vector).tobytes()


def unpack(blob):
    vec = array("f")
    vec.frombytes(bytes(getattr(blob, "value", blob)))   # boto3 returns dynamodb.types.Binary
    return vec.tolist()


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def top_k(query_vec, items, k=5, key="embedding"):
    """items: dicts holding a vector under `key`. Returns [(score, item)] best first."""
    scored = [(cosine(query_vec, item[key]), item) for item in items]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored[:k]
