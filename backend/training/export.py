"""
export.py
─────────
Converts the best training checkpoint (.pt) to ONNX format
for lightweight CPU inference on the local backend.

Usage:
    python backend/training/export.py
    python backend/training/export.py --checkpoint checkpoints/stage2_best.pt
    python backend/training/export.py --checkpoint checkpoints/stage2_best.pt --output backend/runtime/model.onnx

What this does:
    1. Loads the saved state_dict into a fresh EfficientNet-B0 model.
    2. Runs a dummy forward pass to trace the computation graph.
    3. Exports to ONNX with dynamic batch size axis.
    4. Verifies the ONNX graph is valid.
    5. Saves a companion metadata.json alongside the .onnx file
       (classes list, image size, normalization constants).
"""

import sys
import os
import json
import argparse
import logging
from pathlib import Path

import torch

sys.path.insert(0, os.path.dirname(__file__))
import config as cfg
from model import build_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def export(checkpoint_path: str, output_path: str) -> None:
    device = torch.device("cpu")   # Export on CPU for portability

    # ── Load model ──────────────────────────────────────────────────────────
    log.info(f"Loading checkpoint: {checkpoint_path}")
    model = build_model(device)

    ckpt = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    saved_classes = ckpt.get("classes", cfg.CLASSES)
    val_acc       = ckpt.get("val_acc", "unknown")
    log.info(f"  Classes: {saved_classes}")
    log.info(f"  Val accuracy at checkpoint: {val_acc}")

    # ── Dummy input ─────────────────────────────────────────────────────────
    # Batch size = 1 for the trace, but we export with dynamic batch axis
    dummy_input = torch.randn(1, 3, cfg.IMAGE_SIZE, cfg.IMAGE_SIZE, device=device)

    # ── Export ──────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    log.info(f"Exporting to ONNX: {output_path}")
    torch.onnx.export(
        model,
        dummy_input,
        output_path,
        export_params=True,
        opset_version=17,          # stable, widely supported opset
        do_constant_folding=True,  # fold constants for smaller model
        input_names=["image"],
        output_names=["logits"],
        dynamic_axes={
            "image":  {0: "batch_size"},   # variable batch size at runtime
            "logits": {0: "batch_size"},
        },
    )
    log.info("  ONNX export complete.")

    # ── Verify the graph ────────────────────────────────────────────────────
    try:
        import onnx
        model_onnx = onnx.load(output_path)
        onnx.checker.check_model(model_onnx)
        log.info("  ONNX graph verified ✓")
    except ImportError:
        log.warning("  onnx package not installed — skipping graph verification.")
        log.warning("  Run: pip install onnx")

    # ── Metadata sidecar ────────────────────────────────────────────────────
    # The runtime server reads this to know class names and preprocessing params
    from dataset import IMAGENET_MEAN, IMAGENET_STD

    metadata = {
        "classes":        saved_classes,
        "num_classes":    len(saved_classes),
        "image_size":     cfg.IMAGE_SIZE,
        "backbone":       cfg.BACKBONE,
        "imagenet_mean":  IMAGENET_MEAN,
        "imagenet_std":   IMAGENET_STD,
        "val_accuracy":   val_acc,
        "confidence_threshold": cfg.CONFIDENCE_THRESHOLD,
        "checkpoint":     os.path.basename(checkpoint_path),
    }

    meta_path = str(Path(output_path).with_suffix(".json"))
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    log.info(f"  Metadata saved → {meta_path}")

    # ── Size report ─────────────────────────────────────────────────────────
    onnx_mb = os.path.getsize(output_path) / 1e6
    log.info(f"\n  Model size: {onnx_mb:.1f} MB")
    log.info(f"  Ready for inference at: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Export GalleryClassifier to ONNX")
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=os.path.join(cfg.CHECKPOINT_DIR, "stage2_best.pt"),
        help="Path to .pt checkpoint (default: checkpoints/stage2_best.pt)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(cfg.EXPORT_DIR, "model.onnx"),
        help="Output .onnx path (default: backend/runtime/model.onnx)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.checkpoint):
        log.error(f"Checkpoint not found: {args.checkpoint}")
        log.error("Run train.py first, then export.")
        sys.exit(1)

    export(args.checkpoint, args.output)


if __name__ == "__main__":
    main()
