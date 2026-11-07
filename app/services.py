import asyncio
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx

from app.config import (
    INDEX_VERSION,
    LEX_SNAPSHOT_DATE,
    LLM_MODEL,
    OPENROUTER_API_KEY,
    PIPELINE_VERSION,
)
from app.retrieval import IndexUnavailable, search
from app.lex_live import search_lex
from app.schemas import (
    BatchRequest,
    CitationModel,
    ContextModel,
    RequestOptions,
    ResultItemModel,
    SystemInfoModel,
)


def system_info() -> SystemInfoModel:
    return SystemInfoModel(
        pipeline_version=PIPELINE_VERSION,
        llm_model=LLM_MODEL or "not-configured",
        embedding_model="BM25 lexical retrieval (no embedding model)",
        reranker="lexical-metadata-boost-v1",
        index_version=INDEX_VERSION or "not-configured",
        lex_snapshot_date=LEX_SNAPSHOT_DATE or "not-configured",
    )


def _language(question: str, requested: str, item_language: Optional[str]) -> str:
    if item_language:
        return item_language
    if requested != "auto":
        return requested
    if re.search(r"[\u049b\u0492\u04b3\u045e\u049a\u0493\u04b2\u040e]", question):
        return "uz-Cyrl"
    if re.search(r"[\u044b\u044d\u0451\u044a\u042b\u042d\u0401\u042a]", question):
        return "ru"
    if re.search(r"\b(что|какой|какая|какие|как|установлен|исковой|срок|гражданским)\b", question.casefold()):
        return "ru"
    if re.search(r"[\u0400-\u04ff]", question):
        return "uz-Cyrl"
    return "uz-Latn"


def _citation(ref: int, chunk: Dict[str, Any]) -> CitationModel:
    return CitationModel(
        ref=ref,
        doc_id=chunk["doc_id"],
        doc_title=chunk["doc_title"],
        doc_type=chunk["doc_type"],
        url=chunk["url"],
        article=chunk["article"],
        part=chunk.get("part") or "butun modda",
        edition_date=chunk["edition_date"],
        doc_status=chunk["doc_status"],
        chunk_id=chunk["chunk_id"],
        quote=chunk["text"][:1200],
    )


def _extractive_answer(question: str, source_text: str) -> str:
    """Select source sentences that overlap the question; do not synthesize facts."""
    stop_words = {
        "qancha", "qanday", "qaysi", "uchun", "haqida", "bo'yicha", "bo‘yicha", "hisoblanadi",
        "что", "какой", "какая", "какие", "сколько", "установлен", "согласно", "является",
        "the", "what", "how", "when", "which", "does", "are", "is",
    }
    tokens = lambda value: {token.casefold().replace("’", "'").replace("ʻ", "'").replace("ʼ", "'").strip("'") for token in re.findall(r"[\wʻ’ʼ'-]+", value) if len(token) > 2 and token.casefold() not in stop_words}
    query_terms = tokens(question)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", source_text) if len(part.strip()) > 20]
    if not sentences:
        sentences = [source_text.strip()]
    scored = []
    for index, sentence in enumerate(sentences):
        overlap = len(query_terms & tokens(sentence))
        if overlap:
            scored.append((overlap, -index, sentence))
    if not scored:
        return sentences[0] + " [1]"
    scored.sort(reverse=True)
    selected = [scored[0][2]]
    if len(scored) > 1 and scored[1][0] >= max(2, scored[0][0] // 2):
        selected.append(scored[1][2])
    return " ".join(selected) + " [1]"


async def _generate(question: str, contexts: List[Dict[str, Any]], options: RequestOptions, language: str):
    if not OPENROUTER_API_KEY or not LLM_MODEL:
        if language != "uz-Latn" and contexts[0].get("language") != language:
            raise RuntimeError("A matching-language extractive answer is unavailable")
        return _extractive_answer(question, contexts[0]["text"]), None, None
    context_text = "\n\n".join(f"[{i}] {c['text']}" for i, c in enumerate(contexts, 1))
    prompt = (
        "Answer only from the supplied legal excerpts. If they do not answer the question, respond exactly NO_ANSWER. "
        "Cite every legal claim with the excerpt number, such as [1]. Do not invent laws or citations. "
        f"Answer in {language}.\n\nExcerpts:\n{context_text}\n\nQuestion: {question}"
    )
    request: Dict[str, Any] = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": options.temperature,
    }
    if options.seed is not None:
        request["seed"] = options.seed
    async with httpx.AsyncClient(timeout=55.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
            json=request,
        )
        response.raise_for_status()
        data = response.json()
    answer = data["choices"][0]["message"]["content"].strip()
    usage = data.get("usage") or {}
    return answer, {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0)}, data.get("choices", [{}])[0].get("finish_reason")


async def process_rag_item(item, options: RequestOptions, request: BatchRequest) -> ResultItemModel:
    started = time.perf_counter()
    language = _language(item.question, options.answer_language, item.language)
    try:
        retrieval_started = time.perf_counter()
        as_of_date = options.as_of_date or request.as_of_date
        try:
            chunks = search(item.question, options.top_k, as_of_date)
        except IndexUnavailable:
            chunks = await search_lex(item.question, options.top_k, as_of_date, language)
        if not chunks:
            chunks = await search_lex(item.question, options.top_k, as_of_date, language)
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)
    except IndexUnavailable:
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)
        return ResultItemModel(
            id=item.id,
            status="error",
            answer=None,
            answer_language=language,
            no_answer=False,
            error={"code": "INDEX_UNAVAILABLE", "message": "Lex.uz qidiruv indeksi sozlanmagan yoki o'qilmaydi.", "retryable": True},
            timing={"retrieval_ms": retrieval_ms, "rerank_ms": 0, "generation_ms": 0, "total_ms": int((time.perf_counter() - started) * 1000)},
        )
    except httpx.HTTPError:
        retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)
        return ResultItemModel(
            id=item.id,
            status="error",
            answer=None,
            answer_language=language,
            no_answer=False,
            error={"code": "RETRIEVAL_FAILED", "message": "Lex.uz qidiruv sahifasiga ulanib bo'lmadi.", "retryable": True},
            timing={"retrieval_ms": retrieval_ms, "rerank_ms": 0, "generation_ms": 0, "total_ms": int((time.perf_counter() - started) * 1000)},
        )
    if not chunks:
        return ResultItemModel(
            id=item.id,
            status="no_answer",
            answer=None,
            answer_language=language,
            no_answer=True,
            citations=[],
            contexts=[],
            debug={"rewritten_query": item.question, "retrieved_total": 0} if options.return_debug else None,
            timing={"retrieval_ms": retrieval_ms, "rerank_ms": 0, "generation_ms": 0, "total_ms": int((time.perf_counter() - started) * 1000)},
        )

    # Stable metadata boost is the configured lightweight reranker when no learned reranker is supplied.
    rerank_started = time.perf_counter()
    query_terms = set(item.question.casefold().split())
    for chunk in chunks:
        title_terms = set(chunk["doc_title"].casefold().split()) | set(chunk["article"].casefold().split())
        chunk["rerank_score"] = min(1.0, chunk["retrieval_score"] + 0.05 * bool(query_terms & title_terms))
    chunks.sort(key=lambda c: (-c["rerank_score"], c["rank"], c["chunk_id"]))
    rerank_ms = int((time.perf_counter() - rerank_started) * 1000)
    generation_started = time.perf_counter()
    try:
        answer, usage, _ = await _generate(item.question, chunks, options, language)
    except (httpx.HTTPError, KeyError, IndexError, RuntimeError, ValueError) as exc:
        failed_contexts = [
            ContextModel(rank=i, chunk_id=chunk["chunk_id"], doc_id=chunk["doc_id"], article=chunk["article"], text=chunk["text"], retrieval_score=chunk["retrieval_score"], rerank_score=chunk["rerank_score"], used_in_answer=False)
            for i, chunk in enumerate(chunks, 1)
        ] if options.return_contexts else []
        retryable = isinstance(exc, httpx.HTTPError) and (not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code >= 500 or exc.response.status_code == 429)
        return ResultItemModel(
            id=item.id,
            status="error",
            answer=None,
            answer_language=language,
            no_answer=False,
            citations=[],
            contexts=failed_contexts,
            error={"code": "LLM_ERROR", "message": "Javob yaratish xizmati ishlamadi.", "retryable": retryable},
            timing={"retrieval_ms": retrieval_ms, "rerank_ms": rerank_ms, "generation_ms": int((time.perf_counter() - generation_started) * 1000), "total_ms": int((time.perf_counter() - started) * 1000)},
        )
    generation_ms = int((time.perf_counter() - generation_started) * 1000)

    if answer.strip().upper() == "NO_ANSWER":
        contexts = [
            ContextModel(rank=i, chunk_id=chunk["chunk_id"], doc_id=chunk["doc_id"], article=chunk["article"], text=chunk["text"], retrieval_score=chunk["retrieval_score"], rerank_score=chunk["rerank_score"], used_in_answer=False)
            for i, chunk in enumerate(chunks, 1)
        ] if options.return_contexts else []
        return ResultItemModel(
            id=item.id, status="no_answer", answer=None, answer_language=language, no_answer=True,
            contexts=contexts, citations=[], usage=usage,
            debug={"rewritten_query": item.question, "retrieved_total": len(chunks)} if options.return_debug else None,
            timing={"retrieval_ms": retrieval_ms, "rerank_ms": rerank_ms, "generation_ms": generation_ms, "total_ms": int((time.perf_counter() - started) * 1000)},
        )

    used_refs = {int(ref) for ref in re.findall(r"\[(\d+)\]", answer)}
    valid_refs = {ref for ref in used_refs if 1 <= ref <= len(chunks)}
    if OPENROUTER_API_KEY and (not valid_refs or len(valid_refs) != len(used_refs)):
        return ResultItemModel(
            id=item.id,
            status="error",
            answer=None,
            answer_language=language,
            no_answer=False,
            error={"code": "LLM_ERROR", "message": "Javob manba havolasi bilan qaytmadi.", "retryable": True},
            timing={"retrieval_ms": retrieval_ms, "rerank_ms": rerank_ms, "generation_ms": generation_ms, "total_ms": int((time.perf_counter() - started) * 1000)},
        )
    if options.return_contexts:
        contexts = [
        ContextModel(
            rank=i,
            chunk_id=chunk["chunk_id"],
            doc_id=chunk["doc_id"],
            article=chunk["article"],
            text=chunk["text"],
            retrieval_score=chunk["retrieval_score"],
            rerank_score=chunk["rerank_score"],
            used_in_answer=(i in valid_refs),
        )
        for i, chunk in enumerate(chunks, 1)
        ]
        citations = [_citation(i, chunks[i - 1]) for i in sorted(valid_refs)]
    else:
        contexts = []
        citations = []
        answer = re.sub(r"\s*\[\d+\]", "", answer)
    return ResultItemModel(
        id=item.id,
        status="ok",
        answer=answer,
        answer_language=language,
        no_answer=False,
        citations=citations,
        contexts=contexts,
        debug={"rewritten_query": item.question, "retrieved_total": len(chunks)} if options.return_debug else None,
        timing={"retrieval_ms": retrieval_ms, "rerank_ms": rerank_ms, "generation_ms": generation_ms, "total_ms": int((time.perf_counter() - started) * 1000)},
        usage=usage,
    )


def _effective_options(request: BatchRequest) -> RequestOptions:
    opts = request.options.model_copy(deep=True)
    if opts.seed is None:
        opts.seed = request.seed
    if opts.as_of_date is None:
        opts.as_of_date = request.as_of_date
    if opts.answer_language == "auto" and request.answer_language != "auto":
        opts.answer_language = request.answer_language
    return opts


async def execute_batch(request: BatchRequest) -> Dict[str, Any]:
    tashkent = timezone(timedelta(hours=5))
    started_at = datetime.now(timezone.utc).astimezone(tashkent).isoformat(timespec="seconds")
    timer = time.perf_counter()
    options = _effective_options(request)
    semaphore = asyncio.Semaphore(10)

    async def run(item):
        async with semaphore:
            try:
                return await process_rag_item(item, options, request)
            except asyncio.TimeoutError:
                return ResultItemModel(id=item.id, status="timeout", error={"code": "LLM_TIMEOUT", "message": "Savolni qayta ishlash vaqti tugadi.", "retryable": True})
            except Exception:
                return ResultItemModel(id=item.id, status="error", error={"code": "INTERNAL_ERROR", "message": "Savolni qayta ishlashda ichki xato yuz berdi.", "retryable": True})

    results = await asyncio.gather(*(run(item) for item in request.items))
    total_ms = int((time.perf_counter() - timer) * 1000)
    counts = {key: sum(result.status == key for result in results) for key in ("ok", "no_answer", "error", "timeout")}
    return {
        "run_id": request.run_id,
        "batch_id": request.batch_id,
        "status": "completed",
        "system": system_info().model_dump(),
        "timing": {"received_at": started_at, "completed_at": datetime.now(timezone.utc).astimezone(tashkent).isoformat(timespec="seconds"), "total_ms": total_ms},
        "summary": {"total": len(results), "ok": counts["ok"], "no_answer": counts["no_answer"], "error": counts["error"] + counts["timeout"]},
        "results": [result.model_dump() for result in results],
    }
