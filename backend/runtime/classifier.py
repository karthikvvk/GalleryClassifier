"""
classifier.py
─────────────
Pure-inference module.  No PyTorch — only onnxruntime, Pillow, and numpy.

Public API
──────────
    cls = Classifier()          # loads model.onnx + model.json from the same dir
    results = cls.classify(paths)
    # returns: dict[str, list[tuple[Path, int]]]
    #   key   = class name (as stored in model.json, e.g. "camera")
    #   value = list of (abs_path, size_in_bytes)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, UnidentifiedImageError

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
_RUNTIME_DIR = Path(__file__).parent
_ONNX_PATH   = _RUNTIME_DIR / "model.onnx"
_META_PATH   = _RUNTIME_DIR / "model.json"

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
INFERENCE_BATCH = 64   # images per ONNX forward pass


# ─────────────────────────────────────────────────────────────────────────────
# Classifier
# ─────────────────────────────────────────────────────────────────────────────

class Classifier:
    """
    Singleton-friendly ONNX inference wrapper.
    Instantiate once at server startup; call .classify() repeatedly.
    """

    def __init__(
        self,
        onnx_path: Path = _ONNX_PATH,
        meta_path: Path = _META_PATH,
    ) -> None:
        if not onnx_path.exists():
            raise FileNotFoundError(
                f"ONNX model not found at {onnx_path}. "
                "Run: python backend/training/export.py"
            )
        if not meta_path.exists():
            raise FileNotFoundError(
                f"Model metadata not found at {meta_path}."
            )

        with open(meta_path) as f:
            meta = json.load(f)

        self.classes:    list[str] = meta["classes"]          # e.g. ["camera", "memes", ...]
        self.image_size: int       = meta["image_size"]        # 224
        self.mean = np.array(meta["imagenet_mean"], dtype=np.float32)  # [0.485, 0.456, 0.406]
        self.std  = np.array(meta["imagenet_std"],  dtype=np.float32)  # [0.229, 0.224, 0.225]
        self.confidence_threshold: float = meta.get("confidence_threshold", 0.60)

        log.info("Loading ONNX model: %s", onnx_path)
        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = os.cpu_count() or 4
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            str(onnx_path),
            sess_options=sess_opts,
            providers=["CPUExecutionProvider"],
        )
        self._input_name = self._session.get_inputs()[0].name
        log.info(
            "Classifier ready — classes=%s  img_size=%d  threshold=%.2f",
            self.classes, self.image_size, self.confidence_threshold,
        )

    # ── Preprocessing ─────────────────────────────────────────────────────────

    def _preprocess(self, img: Image.Image) -> np.ndarray:
        """
        PIL Image → normalised float32 CHW tensor (no batch dim).
        Mirrors the EVAL_TRANSFORM used during training.
        """
        img = img.convert("RGB").resize(
            (self.image_size, self.image_size), Image.BILINEAR
        )
        arr = np.array(img, dtype=np.float32) / 255.0          # HWC, [0,1]
        arr = (arr - self.mean) / self.std                      # normalise
        arr = arr.transpose(2, 0, 1)                            # HWC → CHW
        return arr

    # ── Inference ─────────────────────────────────────────────────────────────

    def _run_batch(self, batch: list[np.ndarray]) -> list[int]:
        """Run one ONNX forward pass; return predicted class indices."""
        x = np.stack(batch, axis=0)                             # (B, C, H, W)
        logits = self._session.run(None, {self._input_name: x})[0]  # (B, num_classes)
        return logits.argmax(axis=1).tolist()

    # ── Public API ────────────────────────────────────────────────────────────

    def classify(
        self,
        paths: list[Path],
    ) -> dict[str, list[tuple[Path, int]]]:
        """
        Classify a list of image paths.

        Returns
        ───────
        dict[class_name, list[(path, size_bytes)]]
          "unknown" key is used for images below the confidence threshold.
        """
        results: dict[str, list[tuple[Path, int]]] = {c: [] for c in self.classes}
        results["unknown"] = []

        tensors: list[np.ndarray] = []
        meta_buf: list[tuple[Path, int]] = []   # (path, size) for the current batch window

        def _flush(t_batch: list[np.ndarray], m_batch: list[tuple[Path, int]]) -> None:
            if not t_batch:
                return
            preds = self._run_batch(t_batch)
            for pred_idx, (p, sz) in zip(preds, m_batch):
                cls = self.classes[pred_idx]
                results[cls].append((p, sz))

        for p in paths:
            try:
                sz = p.stat().st_size
                img = Image.open(p)
                arr = self._preprocess(img)
            except (UnidentifiedImageError, OSError, Exception) as exc:
                log.debug("Skipping %s: %s", p, exc)
                continue

            tensors.append(arr)
            meta_buf.append((p, sz))

            if len(tensors) >= INFERENCE_BATCH:
                _flush(tensors, meta_buf)
                tensors.clear()
                meta_buf.clear()

        _flush(tensors, meta_buf)   # remaining images

        return results
