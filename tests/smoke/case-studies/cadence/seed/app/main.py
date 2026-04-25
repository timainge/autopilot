from fastapi import FastAPI

app = FastAPI(title="Cadence", description="Time-tracking API.")


@app.get("/")
def root() -> dict[str, bool]:
    return {"ok": True}
