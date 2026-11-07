import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
LOCAL_ENV_PATH = Path(__file__).resolve().parent.parent / ".env.local"
external_rag_api_key = os.getenv("RAG_API_KEY", "").strip()
file_values = dotenv_values(ENV_PATH)
local_values = dotenv_values(LOCAL_ENV_PATH)
load_dotenv(ENV_PATH)

# .env.local is intentionally the project-local override for the generated
# development key. It is excluded from version control.
RAG_API_KEY = (
    (local_values.get("RAG_API_KEY") or "").strip()
    or external_rag_api_key
    or (file_values.get("RAG_API_KEY") or "").strip()
)
LEX_CORPUS_PATH = os.getenv("LEX_CORPUS_PATH", "data/lex_chunks.jsonl")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "")
INDEX_VERSION = os.getenv("INDEX_VERSION", "")
LEX_SNAPSHOT_DATE = os.getenv("LEX_SNAPSHOT_DATE", "")
PIPELINE_VERSION = os.getenv("PIPELINE_VERSION", "0.5.0")
BATCH_TIMEOUT_SECONDS = float(os.getenv("BATCH_TIMEOUT_SECONDS", "120"))
RETRIEVAL_MIN_SCORE = float(os.getenv("RETRIEVAL_MIN_SCORE", "0.15"))
