from fastapi import FastAPI

from app.api.analysis import router as analysis_router
from app.api.recommendations import router as recommendations_router

app = FastAPI(title="AI-Assisted PC Configuration System", version="0.1.0")
app.include_router(analysis_router)
app.include_router(recommendations_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}
