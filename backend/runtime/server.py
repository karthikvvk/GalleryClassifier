"""
server.py
─────────
FastAPI backend for GalleryClassifier.

Start with:
    uvicorn backend.runtime.server:app --port 8000 --reload

or from the project root:
    python -m backend.runtime.server

Endpoints
─────────
POST /runclassification          (desktop Flutter app)
  Request  : { "path": "<absolute directory path>" }
  Response : {
    "screenshot": { "count": 120, "size_bytes": 543210, "files": [...] },
    "memes":      { "count": 40,  "size_bytes": 123456, "files": [...] },
    "wallpaper":  { "count": 12,  "size_bytes": 987654, "files": [...] },
    "photos":     { "count": 300, "size_bytes": 5432100,"files": [...] }
  }

POST /classify-upload            (web UI — multipart/form-data)
  Request  : form field "files" — 1 to 20 image files
  Response : {
    "screenshot": { "count": 2, "size_bytes": 12300, "files": ["a.jpg", ...] },
    "memes":      { ... },
    "wallpaper":  { ... },
    "photos":     { ... }
  }
  Errors   : HTTP 422 if more than 20 files are submitted

Note: The model uses class names ["camera", "memes", "screenshots", "wallpapers"].
The Flutter frontend expects ["photos", "memes", "screenshot", "wallpaper"].
This server remaps them transparently.
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, HTTPException, UploadFile
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

# ── Add project root to sys.path if run directly ─────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
    log.info("Server ready — listening")
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
    files: list[str] = []


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
            files=[str(p) for p, _ in entries],
        )

    # Log unknown images (below confidence threshold)
    unknown = raw_results.get("unknown", [])
    if unknown:
        log.warning("%d image(s) classified as 'unknown' (low confidence)", len(unknown))

    return response


# ── Web upload endpoint ───────────────────────────────────────────────────────

MAX_UPLOAD_FILES = 20


@app.post("/classify-upload")
async def classify_upload(
    files: List[UploadFile] = File(...),
) -> dict[str, ClassSummary]:
    """
    Accept up to MAX_UPLOAD_FILES image files via multipart/form-data.

    Saves them to a temporary directory, classifies them with the same
    Classifier used by /runclassification, then returns per-class summaries
    where ``files`` contains the *original uploaded filenames* (not temp
    paths) so the browser can match results back to its local File objects.
    """
    if len(files) == 0:
        raise HTTPException(status_code=422, detail="No files uploaded.")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"Too many files: {len(files)} sent, maximum is {MAX_UPLOAD_FILES}.",
        )

    tmpdir = tempfile.mkdtemp(prefix="galleryclassifier_")
    try:
        # ── Save uploads to temp dir ──────────────────────────────────────────
        saved: list[tuple[Path, str]] = []   # (tmp_path, original_filename)
        for upload in files:
            original_name = Path(upload.filename).name  # strip any path component
            tmp_path = Path(tmpdir) / original_name
            # Handle duplicate filenames by appending an index
            if tmp_path.exists():
                stem = tmp_path.stem
                suffix = tmp_path.suffix
                tmp_path = Path(tmpdir) / f"{stem}_{len(saved)}{suffix}"
            with tmp_path.open("wb") as f:
                shutil.copyfileobj(upload.file, f)
            saved.append((tmp_path, original_name))

        log.info("classify-upload: saved %d files to %s", len(saved), tmpdir)

        # ── Run inference ─────────────────────────────────────────────────────
        t0 = time.perf_counter()
        clf = get_classifier()
        tmp_paths = [p for p, _ in saved]
        raw_results = clf.classify(tmp_paths)
        elapsed = time.perf_counter() - t0

        # Build a lookup: tmp_path → original_filename
        tmp_to_orig = {str(p): name for p, name in saved}

        total = sum(len(v) for v in raw_results.values())
        log.info(
            "classify-upload: classified %d images in %.1fs (%.0f img/s)",
            total, elapsed, total / max(elapsed, 1e-9),
        )

        # ── Aggregate ─────────────────────────────────────────────────────────
        response: dict[str, ClassSummary] = {}
        for model_cls, frontend_key in _CLASS_MAP.items():
            entries = raw_results.get(model_cls, [])
            response[frontend_key] = ClassSummary(
                count=len(entries),
                size_bytes=sum(sz for _, sz in entries),
                # Return original filenames so the browser can find its blobs
                files=[tmp_to_orig.get(str(p), p.name) for p, _ in entries],
            )

        unknown = raw_results.get("unknown", [])
        if unknown:
            log.warning(
                "classify-upload: %d image(s) below confidence threshold",
                len(unknown),
            )

        return response

    finally:
        # Always clean up temp files
        shutil.rmtree(tmpdir, ignore_errors=True)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)



