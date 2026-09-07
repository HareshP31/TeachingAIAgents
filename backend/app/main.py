from fastapi import FastAPI

app = FastAPI(title="Teaching AI Agents Backend")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
