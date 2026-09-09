"""
server.py
─────────
FastAPI backend for GalleryClassifier.

Start with:
    uvicorn backend.runtime.server:app --port 8000 --reload

or from the project root:
    python -m backend.runtime.server

Endpoint
────────
POST /runclassification
  Request  : { "path": "<absolute directory path>" }
  Response : {
    "screenshot": { "count": 120, "size_bytes": 543210 },
    "memes":      { "count": 40,  "size_bytes": 123456 },
    "wallpaper":  { "count": 12,  "size_bytes": 987654 },
    "photos":     { "count": 300, "size_bytes": 5432100 }
  }

Note: The model uses class names ["camera", "memes", "screenshots", "wallpapers"].
The Flutter frontend expects ["photos", "memes", "screenshot", "wallpaper"].
This server remaps them transparently.
"""

from __future__ import annotations

import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Bootstrap logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ── Classifier (loaded once at startup) ──────────────────────────────────────
from backend.runtime.classifier import Classifier, SUPPORTED_EXTS  # noqa: E402

_classifier: Classifier | None = None


def get_classifier() -> Classifier:
    global _classifier
    if _classifier is None:
        _classifier = Classifier()
    return _classifier


# ── Model class → frontend key mapping ───────────────────────────────────────
# Model outputs           → Flutter frontend key
_CLASS_MAP: dict[str, str] = {
    "camera":      "photos",
    "memes":       "memes",
    "screenshots": "screenshot",
    "wallpapers":  "wallpaper",
}


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-load the ONNX model so the first request isn't slow."""
    get_classifier()
    log.info("Server ready — listening on http://localhost:8000")
    yield


app = FastAPI(
    title="GalleryClassifier API",
    description="Classify images in a directory into camera/memes/screenshots/wallpapers.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Flutter desktop app on localhost
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / response schemas ────────────────────────────────────────────────

class ClassifyRequest(BaseModel):
    path: str


class ClassSummary(BaseModel):
    count: int
    size_bytes: int


# ── Endpoint ──────────────────────────────────────────────────────────────────

@app.post("/runclassification")
def run_classification(req: ClassifyRequest) -> dict[str, ClassSummary]:
    """
    Scan *req.path* recursively, classify every image, and return
    per-class counts and total byte sizes.
    """
    root = Path(req.path).expanduser()
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {root}")
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {root}")

    # ── Gather all image paths ────────────────────────────────────────────────
    t0 = time.perf_counter()
    image_paths: list[Path] = [
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    ]
    log.info("Found %d images in %s", len(image_paths), root)

    if not image_paths:
        # Return zero counts — not an error
        return {
            frontend_key: ClassSummary(count=0, size_bytes=0)
            for frontend_key in _CLASS_MAP.values()
        }

    # ── Run inference ─────────────────────────────────────────────────────────
    clf = get_classifier()
    raw_results = clf.classify(image_paths)
    elapsed = time.perf_counter() - t0

    total = sum(len(v) for v in raw_results.values())
    log.info(
        "Classified %d images in %.1fs  (%.0f img/s)",
        total, elapsed, total / max(elapsed, 1e-9),
    )

    # ── Aggregate ─────────────────────────────────────────────────────────────
    response: dict[str, ClassSummary] = {}
    for model_cls, frontend_key in _CLASS_MAP.items():
        entries = raw_results.get(model_cls, [])
        response[frontend_key] = ClassSummary(
            count=len(entries),
            size_bytes=sum(sz for _, sz in entries),
        )

    # Log unknown images (below confidence threshold)
            files=[str(p) for p, _ in entries],
    unknown = raw_results.get("unknown", [])
    if unknown:
        log.warning("%d image(s) classified as 'unknown' (low confidence)", len(unknown))

    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


