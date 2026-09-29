"""BM25 passage ranking over extracted document text.

Documents are cut into overlapping windows ranked with Lucene-compatible BM25,
so a query returns the few passages that answer it, never a whole document.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import bm25s

MAX_PASSAGE_CHARS = 1400
_WINDOW_OVERLAP = 240
_TOKEN_PATTERN = r"(?u)\b\w[\w-]*\b"


@dataclass(frozen=True)
class Passage:
    document: int
    start: int
    end: int
    score: float
    text: str


def relevant_passages(
    documents: Sequence[str], query: str, *, limit: int
) -> list[Passage]:
    """The ``limit`` best passages for ``query``, none overlapping another.

    ``Passage.document`` indexes ``documents``; all windows share one index, so
    scores compare across documents.
    """
    windows = [
        (index, start, end, passage)
        for index, text in enumerate(documents)
        for start, end, passage in _windows(text)
    ]
    if not windows:
        return []
    query_tokens = _tokens([query])
    if not query_tokens[0]:
        return []
    # Match OpenSearch/Lucene's BM25 variant for local, transient passages.
    retriever = bm25s.BM25(method="lucene")
    retriever.index(_tokens([passage for *_, passage in windows]), show_progress=False)
    ranked = retriever.retrieve(
        query_tokens,
        corpus=list(range(len(windows))),
        k=len(windows),
        show_progress=False,
    )
    selected: list[Passage] = []
    for window_index, score in zip(ranked.documents[0], ranked.scores[0], strict=True):
        if score <= 0:
            continue
        document, start, end, passage = windows[int(window_index)]
        if any(
            kept.document == document and start < kept.end and end > kept.start
            for kept in selected
        ):
            continue
        selected.append(Passage(document, start, end, float(score), passage))
        if len(selected) >= limit:
            break
    return selected


def _tokens(texts: list[str]) -> list[list[str]]:
    return bm25s.tokenize(
        texts,
        token_pattern=_TOKEN_PATTERN,
        # BM25 downweights document-common terms without a global stop list.
        stopwords=None,
        return_ids=False,
        show_progress=False,
    )


def _windows(text: str) -> list[tuple[int, int, str]]:
    windows = []
    start = 0
    while start < len(text):
        end = min(start + MAX_PASSAGE_CHARS, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + MAX_PASSAGE_CHARS // 2, end)
            if boundary > start:
                end = boundary
        passage = " ".join(text[start:end].split())
        windows.append((start, end, passage))
        if end >= len(text):
            break
        start = max(start + 1, end - _WINDOW_OVERLAP)
    return windows
