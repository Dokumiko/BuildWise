from fastapi import FastAPI

app = FastAPI(title="AI-Assisted PC Configuration System", version="0.1.0")


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}
