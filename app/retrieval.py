"""Deterministic lexical retrieval over an explicitly supplied Lex.uz JSONL snapshot.

Each JSONL row is one chunk. See README for the required metadata fields.
"""
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.config import LEX_CORPUS_PATH, RETRIEVAL_MIN_SCORE

TOKEN_RE = re.compile(r"[\wʻ’'-]+", re.UNICODE)
_cache_path: Optional[Path] = None
_cache_mtime: Optional[int] = None
_cache_docs: List[Dict[str, Any]] = []


class IndexUnavailable(RuntimeError):
    pass


def _tokens(text: str) -> List[str]:
    return [token.casefold().replace("’", "'").replace("ʻ", "'").replace("ʼ", "'") for token in TOKEN_RE.findall(text)]


def _load_corpus() -> List[Dict[str, Any]]:
    global _cache_path, _cache_mtime, _cache_docs
    path = Path(LEX_CORPUS_PATH)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError as exc:
        raise IndexUnavailable(f"Corpus fayli topilmadi: {path}") from exc
    if _cache_path == path and _cache_mtime == mtime:
        return _cache_docs

    docs = []
    seen_chunk_ids = set()
    try:
        with path.open("r", encoding="utf-8") as source:
            for line_no, line in enumerate(source, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                required = ("doc_id", "doc_title", "doc_type", "url", "article", "edition_date", "doc_status", "chunk_id", "text")
                if not isinstance(row, dict) or any(not row.get(key) for key in required):
                    raise ValueError(f"{line_no}-qatorda majburiy maydon yetishmaydi")
                host = (urlparse(row["url"]).hostname or "").casefold()
                if host != "lex.uz" and not host.endswith(".lex.uz"):
                    raise ValueError(f"{line_no}-qatordagi URL lex.uz domenida emas")
                if row["chunk_id"] in seen_chunk_ids:
                    raise ValueError(f"{line_no}-qatorda takroriy chunk_id bor")
                seen_chunk_ids.add(row["chunk_id"])
                row["_tokens"] = _tokens(row["text"])
                row["_length"] = len(row["_tokens"])
                docs.append(row)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise IndexUnavailable(f"Corpusni o'qib bo'lmadi: {exc}") from exc
    if not docs:
        raise IndexUnavailable("Corpus bo'sh")
    _cache_path, _cache_mtime, _cache_docs = path, mtime, docs
    return docs


def search(query: str, top_k: int, as_of_date: Optional[date] = None) -> List[Dict[str, Any]]:
    docs = _load_corpus()
    query_terms = _tokens(query)
    if not query_terms:
        return []
    n_docs = len(docs)
    df = Counter(term for doc in docs for term in set(doc["_tokens"]))
    avg_len = sum(doc["_length"] for doc in docs) / n_docs
    # Jamoa sanani keltirmaganda "amaldagi" degani — bugungi kun:
    # kelgusi kuchga kirilgan va muddati tugagan tahrirlar chqarilmaydi.
    reference = as_of_date if as_of_date else date.today()
    ranked = []
    for doc in docs:
        try:
            starts = date.fromisoformat(doc.get("valid_from", doc["edition_date"]))
            ends_raw = doc.get("valid_to")
            ends = date.fromisoformat(ends_raw) if ends_raw else None
        except ValueError:
            continue
        if reference < starts or (ends and reference > ends):
            continue
        status = str(doc["doc_status"]).casefold().replace("'", "").replace("’", "").replace("ʻ", "")
        if not as_of_date and any(marker in status for marker in ("kuchi yoq", "kuchini yoqotgan", "bekor", "amaldan chiqqan", "утратил силу")):
            continue
        counts = Counter(doc["_tokens"])
        length = max(doc["_length"], 1)
        score = 0.0
        for term in query_terms:
            freq = counts[term]
            if not freq:
                continue
            idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (freq * 2.2) / (freq + 1.2 * (0.25 + 0.75 * length / max(avg_len, 1)))
        if score > 0:
            ranked.append((score, doc))
    ranked.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
    if not ranked or ranked[0][0] < RETRIEVAL_MIN_SCORE:
        return []
    max_score = ranked[0][0]
    results = []
    for rank, (score, doc) in enumerate(ranked[:top_k], 1):
        result = {key: value for key, value in doc.items() if not key.startswith("_")}
        result["rank"] = rank
        result["raw_retrieval_score"] = score
        result["retrieval_score"] = score / max_score if max_score else 0.0
        metadata_match = any(term in (result["doc_title"] + " " + result["article"]).casefold() for term in query_terms)
        result["rerank_score"] = min(1.0, result["retrieval_score"] + (0.05 if metadata_match else 0.0))
        results.append(result)
    return results
