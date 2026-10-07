"""Lazily created AWS clients, so modules import cleanly in unit tests."""
import os
from functools import cache

import boto3
from botocore.config import Config


@cache
def table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


@cache
def s3():
    return boto3.client("s3", config=Config(signature_version="s3v4"))


@cache
def bedrock_runtime():
    return boto3.client("bedrock-runtime")


def bucket_name():
    return os.environ["BUCKET_NAME"]
