"""Pipeline step 2: PDF -> per-page text, stored in S3 (Step Functions payloads cap at 256 KB).

Output: {"textKey", "pageCount", "charCount"} under $.text
"""
import io
import json

from pypdf import PdfReader

from lib import aws

# ~75k tokens. Far beyond any real course outline; bigger files are almost certainly not syllabi.
MAX_CHARS = 300_000
MIN_CHARS = 200


class NoTextError(Exception):
    """PDF has no selectable text (probably a scan). Not retried."""


class SyllabusTooLargeError(Exception):
    """Text exceeds MAX_CHARS. Not retried; we never silently truncate."""


def extract_pages(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def check_size(pages):
    chars = sum(len(p) for p in pages)
    if chars < MIN_CHARS:
        raise NoTextError("No selectable text found. Is this a scanned PDF? Export it with text, then re-upload.")
    if chars > MAX_CHARS:
        raise SyllabusTooLargeError(f"Document has {chars:,} characters; the limit is {MAX_CHARS:,}.")
    return chars


def handler(event, context):
    obj = aws.s3().get_object(Bucket=event["bucket"], Key=event["key"])
    pages = extract_pages(obj["Body"].read())
    chars = check_size(pages)

    text_key = f"text/{event['syllabusId']}.json"
    aws.s3().put_object(
        Bucket=event["bucket"],
        Key=text_key,
        Body=json.dumps({"pages": pages}).encode(),
        ContentType="application/json",
    )
    return {"textKey": text_key, "pageCount": len(pages), "charCount": chars}


def load_pages(bucket, text_key):
    obj = aws.s3().get_object(Bucket=bucket, Key=text_key)
    return json.loads(obj["Body"].read())["pages"]
