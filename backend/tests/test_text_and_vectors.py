import pytest

from extract_text import MAX_CHARS, NoTextError, SyllabusTooLargeError, check_size
from index_chunks import chunk_pages
from lib import vectors


def test_check_size_limits():
    assert check_size(["x" * 500]) == 500
    with pytest.raises(NoTextError):
        check_size(["", "  "])
    with pytest.raises(SyllabusTooLargeError):
        check_size(["x" * (MAX_CHARS + 1)])


def test_chunks_stay_on_their_page_and_overlap():
    words = " ".join(f"w{i}" for i in range(1000))       # ~5k chars
    chunks = chunk_pages([words, "short page"], size=1200, overlap=200)
    page1 = [c for c in chunks if c["page"] == 1]
    assert len(page1) >= 4
    assert all(len(c["text"]) <= 1200 for c in chunks)
    assert chunks[-1] == {"page": 2, "text": "short page"}
    # consecutive chunks share words (overlap) and no word is cut in half
    first, second = page1[0]["text"].split(), page1[1]["text"].split()
    assert set(first[-10:]) & set(second[:40])
    assert all(w.startswith("w") and w[1:].isdigit() for c in page1 for w in c["text"].split())
    # every word appears somewhere
    seen = {w for c in page1 for w in c["text"].split()}
    assert seen == set(words.split())


def test_empty_pages_produce_no_chunks():
    assert chunk_pages(["", "   "]) == []


def test_pack_roundtrip_and_ranking():
    v = [0.25, -1.0, 0.5]
    assert vectors.unpack(vectors.pack(v)) == pytest.approx(v)
    items = [{"id": "far", "embedding": [-1.0, 0.0]}, {"id": "near", "embedding": [0.9, 0.1]},
             {"id": "same", "embedding": [2.0, 0.0]}]
    ranked = vectors.top_k([1.0, 0.0], items, k=2)
    assert [item["id"] for _, item in ranked] == ["same", "near"]
    assert ranked[0][0] == pytest.approx(1.0)


def test_cosine_zero_vector():
    assert vectors.cosine([0, 0], [1, 1]) == 0.0
