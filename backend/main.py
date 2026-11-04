# FastAPI app: serves frontend/ at / and GET /health, on one port.
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn

    load_dotenv()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
