from fastapi import FastAPI, Header, HTTPException, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from app.schemas import SystemInfoModel
from app.routers import rag
from typing import Optional
import hmac
from pathlib import Path
from app.config import RAG_API_KEY
from app.services import system_info

app = FastAPI(
    title="Lex.uz RAG API Specification Implementation",
    version="0.5.0",
    description="Lex.uz RAG evaluation API"
)

app.include_router(rag.router)

@app.get("/", include_in_schema=False)
def root():
    return FileResponse(
        Path(__file__).parent / "static" / "index.html",
        media_type="text/html; charset=utf-8",
    )

@app.exception_handler(RequestValidationError)
async def validation_error_as_400(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content=jsonable_encoder({"detail": exc.errors()}))

@app.middleware("http")
async def json_charset(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    if content_type.startswith("application/json"):
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

def verify_bearer_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    parts = authorization.split()
    if not RAG_API_KEY:
        raise HTTPException(status_code=503, detail="API authentication is not configured")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not hmac.compare_digest(parts[1], RAG_API_KEY):
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return parts[1]

@app.get("/v1/health", tags=["System"])
def health_check():
    return {"status": "healthy", "service": "lex-rag-eval-api"}

@app.get("/v1/meta", tags=["System"], response_model=SystemInfoModel)
def get_metadata(token: str = Depends(verify_bearer_token)):
    return system_info()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
