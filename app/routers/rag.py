import asyncio
import hmac
import logging
import math
import sqlite3
import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from app.config import BATCH_TIMEOUT_SECONDS, RAG_API_KEY
from app.schemas import BatchRequest, QueryRequest, ResultItemModel
from app.services import execute_batch, process_rag_item, system_info
from app.storage import batch_storage

router = APIRouter(prefix="/v1/rag", tags=["RAG Batch API"])
logger = logging.getLogger(__name__)
_last_batch_at: Dict[str, float] = {}
_tasks: Dict[str, asyncio.Task] = {}


def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    parts = authorization.split()
    if not RAG_API_KEY:
        raise HTTPException(status_code=503, detail="API authentication is not configured")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not hmac.compare_digest(parts[1], RAG_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return parts[1]


def _request_data(request: BatchRequest):
    return request.model_dump(mode="json")


async def _process_and_store(batch_id: str, request: BatchRequest):
    try:
        result = await execute_batch(request)
    except Exception:
        logger.exception("Batch processing failed for batch_id=%s", batch_id)
        result = {
            "run_id": request.run_id,
            "batch_id": batch_id,
            "status": "failed",
            "system": system_info().model_dump(mode="json"),
            "timing": {},
            "summary": {"total": len(request.items), "ok": 0, "no_answer": 0, "error": len(request.items)},
            "results": [ResultItemModel(id=item.id, status="error", error={"code": "INTERNAL_ERROR", "message": "Batchni qayta ishlashda xato yuz berdi.", "retryable": True}).model_dump(mode="json") for item in request.items],
        }
    batch_storage.complete_batch(batch_id, result)
    return result


def _start_task(batch_id: str, request: BatchRequest):
    task = asyncio.create_task(_process_and_store(batch_id, request))
    _tasks[batch_id] = task
    task.add_done_callback(lambda _: _tasks.pop(batch_id, None))
    return task


@router.post("/batch")
async def submit_batch(request: BatchRequest, token: str = Depends(verify_token)):
    ids = [item.id for item in request.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(status_code=400, detail="Duplicate item IDs in batch")

    data = _request_data(request)
    existing = batch_storage.get_batch(request.batch_id)
    if existing:
        if existing["request"] != data:
            raise HTTPException(status_code=409, detail="batch_id was submitted with different contents")
        if existing["status"] == "processing":
            if request.batch_id not in _tasks:
                _start_task(request.batch_id, request)
            return JSONResponse(status_code=202, content={"batch_id": request.batch_id, "status": "processing"})
        return existing["response"]

    now = time.monotonic()
    previous = _last_batch_at.get(token)
    if previous is not None and now - previous < 1.0:
        retry_after = max(1, math.ceil(1.0 - (now - previous)))
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}, headers={"Retry-After": str(retry_after)})
    _last_batch_at[token] = now

    try:
        batch_storage.create_batch(request.batch_id, data)
    except sqlite3.IntegrityError:
        existing = batch_storage.get_batch(request.batch_id)
        if not existing or existing["request"] != data:
            raise HTTPException(status_code=409, detail="batch_id was submitted with different contents")
    task = _tasks.get(request.batch_id) or _start_task(request.batch_id, request)
    try:
        timeout_seconds = min(120.0, max(1.0, BATCH_TIMEOUT_SECONDS))
        return await asyncio.wait_for(asyncio.shield(task), timeout=timeout_seconds)
    except asyncio.TimeoutError:
        return JSONResponse(status_code=202, content={"batch_id": request.batch_id, "status": "processing"})


@router.get("/batch/{batch_id}")
async def get_batch_status(batch_id: str, token: str = Depends(verify_token)):
    record = batch_storage.get_batch(batch_id)
    if not record:
        raise HTTPException(status_code=404, detail="Batch ID not found")
    if record["status"] == "processing":
        if batch_id not in _tasks:
            request = BatchRequest.model_validate(record["request"])
            _start_task(batch_id, request)
        return JSONResponse(status_code=202, content={"batch_id": batch_id, "status": "processing"})
    return record["response"]


@router.post("/query", response_model=ResultItemModel)
async def query_one(request: QueryRequest, token: str = Depends(verify_token)):
    wrapper = BatchRequest(
        run_id="debug-query",
        batch_id="debug-query",
        batch_index=1,
        total_batches=1,
        options=request.options,
        as_of_date=request.as_of_date,
        items=[{"id": request.id, "question": request.question, "language": request.language}],
    )
    return await process_rag_item(wrapper.items[0], request.options, wrapper)


async def resume_processing_batches():
    for batch_id, data in batch_storage.list_processing():
        if batch_id not in _tasks:
            _start_task(batch_id, BatchRequest.model_validate(data))


router.add_event_handler("startup", resume_processing_batches)
