"""Pipeline step (parallel branch): chunk the text and embed it for /ask retrieval.

Output: {"chunkCount": n} under $.indexed
"""
from concurrent.futures import ThreadPoolExecutor

from extract_text import load_pages
from lib import aws, db, vectors

CHUNK_CHARS = 1200
OVERLAP_CHARS = 200
EMBED_WORKERS = 8           # stays well under Titan's default request quota


def chunk_pages(pages, size=CHUNK_CHARS, overlap=OVERLAP_CHARS):
    """Split each page into ~size-char windows on whitespace, overlapping by ~overlap chars.

    Chunks never span pages, so every chunk can cite one page number.
    """
    chunks = []
    for page_no, text in enumerate(pages, start=1):
        text = " ".join(text.split())
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            if end < len(text):
                space = text.rfind(" ", start + size // 2, end)
                end = space if space > start else end
            piece = text[start:end].strip()
            if piece:
                chunks.append({"page": page_no, "text": piece})
            if end >= len(text):
                break
            next_start = max(end - overlap, start + 1)
            space = text.find(" ", next_start)
            start = space + 1 if 0 <= space < end else next_start
    return chunks


def handler(event, context):
    syllabus_id = event["syllabusId"]
    chunks = chunk_pages(load_pages(event["bucket"], event["text"]["textKey"]))

    # Embedding calls are independent network round-trips; run them concurrently (boto3 clients are thread-safe).
    with ThreadPoolExecutor(max_workers=EMBED_WORKERS) as pool:
        embeddings = list(pool.map(lambda c: vectors.embed(c["text"], operation="index_chunks"), chunks))

    db.delete_items(syllabus_id, "CHUNK#")
    with aws.table().batch_writer() as batch:
        for n, (chunk, embedding) in enumerate(zip(chunks, embeddings), start=1):
            batch.put_item(Item={
                "pk": db.syllabus_pk(syllabus_id),
                "sk": f"CHUNK#{n:04d}",
                "syllabusId": syllabus_id,
                "filename": event.get("filename", ""),
                "page": chunk["page"],
                "text": chunk["text"],
                "embedding": vectors.pack(embedding),
            })
    return {"chunkCount": len(chunks)}
