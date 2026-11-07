from pydantic import BaseModel, Field, model_validator
from datetime import date
from typing import List, Optional, Dict, Any, Literal

class RequestOptions(BaseModel):
    top_k: int = Field(5, ge=1, le=100, description="Nechta kontekst bo'lagi qaytarilsin")
    return_contexts: bool = Field(True, description="Topilgan bo'laklar matni bilan qaytsin")
    return_debug: bool = Field(False, description="Debug ma'lumotlari")
    temperature: float = Field(0.0, ge=0, le=2, description="Temperature parameter")
    seed: Optional[int] = Field(None, description="Seed parameter")
    as_of_date: Optional[date] = Field(None, description="Tahrir sanasi")
    answer_language: Literal["auto", "uz-Latn", "uz-Cyrl", "ru"] = "auto"

class RagItem(BaseModel):
    id: str = Field(..., min_length=1, max_length=100, description="Batch ichida unikal ID (q001-q100)")
    question: str = Field(..., min_length=1, max_length=2000, description="Savol matni")
    language: Optional[Literal["uz-Latn", "uz-Cyrl", "ru"]] = Field(None, description="Savol tili")

    @model_validator(mode="after")
    def question_must_not_be_blank(self):
        if not self.question.strip():
            raise ValueError("question must not be blank")
        return self

class BatchRequest(BaseModel):
    run_id: str = Field(..., min_length=1, max_length=200, description="Run ID")
    batch_id: str = Field(..., min_length=1, max_length=200, description="Batch ID (Idempotentness key)")
    batch_index: int = Field(..., ge=1, le=10)
    total_batches: int = Field(10, ge=1, le=10)
    options: RequestOptions = Field(default_factory=RequestOptions)
    seed: Optional[int] = Field(42)
    as_of_date: Optional[date] = Field(None)
    answer_language: Literal["auto", "uz-Latn", "uz-Cyrl", "ru"] = Field("auto")
    items: List[RagItem] = Field(..., min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_batch_index(self):
        if self.batch_index > self.total_batches:
            raise ValueError("batch_index cannot exceed total_batches")
        return self


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    id: str = Field("q001", min_length=1, max_length=100)
    language: Optional[Literal["uz-Latn", "uz-Cyrl", "ru"]] = None
    options: RequestOptions = Field(default_factory=RequestOptions)
    as_of_date: Optional[date] = None

    @model_validator(mode="after")
    def question_must_not_be_blank(self):
        if not self.question.strip():
            raise ValueError("question must not be blank")
        return self

class CitationModel(BaseModel):
    ref: int
    doc_id: str
    doc_title: str
    doc_type: str
    url: str
    article: str
    part: Optional[str] = None
    edition_date: str
    doc_status: str
    chunk_id: str
    quote: str

class ContextModel(BaseModel):
    rank: int
    chunk_id: str
    doc_id: str
    article: str
    text: str
    retrieval_score: float
    rerank_score: float
    used_in_answer: bool

class ErrorObjectModel(BaseModel):
    code: str
    message: str
    retryable: bool

class ResultItemModel(BaseModel):
    id: str
    status: Literal["ok", "no_answer", "error", "timeout"] = Field(..., description="Natija holati")
    answer: Optional[str] = None
    answer_language: Optional[str] = None
    no_answer: bool = False
    confidence: Optional[float] = None
    citations: List[CitationModel] = Field(default_factory=list)
    contexts: List[ContextModel] = Field(default_factory=list)
    debug: Optional[Dict[str, Any]] = None
    timing: Optional[Dict[str, int]] = None
    usage: Optional[Dict[str, int]] = None
    error: Optional[ErrorObjectModel] = None

class SystemInfoModel(BaseModel):
    pipeline_version: str
    llm_model: Optional[str] = None
    embedding_model: Optional[str] = None
    reranker: Optional[str] = None
    index_version: Optional[str] = None
    lex_snapshot_date: Optional[str] = None

class BatchResponse(BaseModel):
    run_id: str
    batch_id: str
    status: str = Field("completed", description="completed, processing, failed")
    system: SystemInfoModel
    timing: Dict[str, Any]
    summary: Dict[str, int]
    results: List[ResultItemModel]
