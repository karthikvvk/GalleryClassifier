"""
prepare_data.py
───────────────
Run this ONCE before training to:
  1. Deduplicate images in data/raw/ using perceptual hashing (dHash).
  2. Split each class into train / val / test folders (80/10/10).

Expected input structure:
    data/raw/
        camera/       *.jpg *.jpeg *.png *.webp
        memes/
        screenshots/
        wallpapers/

Output structure:
    data/
        train/  val/  test/
            camera/  memes/  screenshots/  wallpapers/

Usage:
    python prepare_data.py [--dry-run]
"""

import os
import sys
import shutil
import random
import argparse
import logging
from pathlib import Path
from collections import defaultdict

import imagehash
from PIL import Image, UnidentifiedImageError

# Allow running from any directory
sys.path.insert(0, os.path.dirname(__file__))
import config as cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


# ─────────────────────────────────────────────────────────────────────────────
# DEDUP
# ─────────────────────────────────────────────────────────────────────────────

def compute_hash(path: Path) -> imagehash.ImageHash | None:
    """Return dHash for image at path, or None if unreadable."""
    try:
        with Image.open(path) as img:
            return imagehash.dhash(img, hash_size=cfg.DEDUP_HASH_SIZE)
    except (UnidentifiedImageError, Exception) as e:
        log.warning(f"Cannot hash {path.name}: {e}")
        return None


def deduplicate(class_dir: Path, dry_run: bool = False) -> list[Path]:
    """
    Remove near-duplicate images from class_dir in-place.
    Returns list of kept image paths (deduplicated).

    Algorithm:
        - Hash every image.
        - Build a list of 'groups' where all images within Hamming distance
          <= DEDUP_MAX_DISTANCE of the group representative are grouped together.
        - Keep only the first image (largest file size as tiebreaker) per group.
    """
    images = sorted(
        [p for p in class_dir.iterdir() if p.suffix.lower() in SUPPORTED_EXTS]
    )
    log.info(f"  [{class_dir.name}] {len(images)} images before dedup")

    hashes: list[tuple[Path, imagehash.ImageHash]] = []
    for img_path in images:
        h = compute_hash(img_path)
        if h is not None:
            hashes.append((img_path, h))

    kept: list[Path] = []
    removed: list[Path] = []
    assigned: set[int] = set()   # indices already assigned to a group

    for i, (path_i, hash_i) in enumerate(hashes):
        if i in assigned:
            continue
        group = [path_i]
        assigned.add(i)
        for j, (path_j, hash_j) in enumerate(hashes):
            if j in assigned:
                continue
            if (hash_i - hash_j) <= cfg.DEDUP_MAX_DISTANCE:
                group.append(path_j)
                assigned.add(j)

        # Keep the image with the largest file size (highest quality)
        best = max(group, key=lambda p: p.stat().st_size)
        kept.append(best)
        for dup in group:
            if dup != best:
                removed.append(dup)
                if not dry_run:
                    dup.unlink()

    log.info(
        f"  [{class_dir.name}] {len(kept)} kept, {len(removed)} removed "
        f"{'(dry run)' if dry_run else ''}"
    )
    return kept


# ─────────────────────────────────────────────────────────────────────────────
# SPLIT
# ─────────────────────────────────────────────────────────────────────────────

def split_and_copy(
    class_name: str,
    image_paths: list[Path],
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Shuffle image_paths and copy them into train/val/test subdirs.
    Returns a dict with counts per split.
    """
    random.shuffle(image_paths)
    n = len(image_paths)
    n_train = int(n * cfg.TRAIN_RATIO)
    n_val   = int(n * cfg.VAL_RATIO)
    # All remaining go to test to avoid rounding loss
    splits = {
        "train": image_paths[:n_train],
        "val":   image_paths[n_train : n_train + n_val],
        "test":  image_paths[n_train + n_val :],
    }

    dir_map = {
        "train": Path(cfg.TRAIN_DIR),
        "val":   Path(cfg.VAL_DIR),
        "test":  Path(cfg.TEST_DIR),
    }

    counts = {}
    for split_name, paths in splits.items():
        dest_dir = dir_map[split_name] / class_name
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
        for src in paths:
            dest = dest_dir / src.name
            if not dry_run:
                shutil.copy2(src, dest)
        counts[split_name] = len(paths)

    return counts


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Dedup + split gallery data")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without moving/deleting any files",
    )
    args = parser.parse_args()

    random.seed(cfg.RANDOM_SEED)

    raw_root = Path(cfg.RAW_DATA_DIR)
    if not raw_root.exists():
        log.error(f"Raw data directory not found: {raw_root}")
        sys.exit(1)

    # Verify expected class folders exist (using RAW_FOLDER_MAP for actual folder names)
    missing = [
        c for c in cfg.CLASSES
        if not (raw_root / cfg.RAW_FOLDER_MAP.get(c, c)).is_dir()
    ]
    if missing:
        log.warning(f"Missing class folders in raw/: {missing}. Will skip them.")

    total_stats = {}
    for class_name in cfg.CLASSES:
        # Resolve the actual folder name on disk via the map (fallback to canonical)
        raw_folder = cfg.RAW_FOLDER_MAP.get(class_name, class_name)
        class_dir  = raw_root / raw_folder
        if not class_dir.is_dir():
            log.warning(f"Folder not found, skipping: {class_dir}")
            continue

        log.info(f"\n{'─'*50}")
        log.info(f"Processing class: {class_name}")

        kept = deduplicate(class_dir, dry_run=args.dry_run)

        if len(kept) < 30:
            log.warning(
                f"[{class_name}] Only {len(kept)} images after dedup — "
                "consider collecting more data before training."
            )

        counts = split_and_copy(class_name, kept, dry_run=args.dry_run)
        total_stats[class_name] = counts

        log.info(
            f"  [{class_name}] split → "
            f"train={counts['train']}, val={counts['val']}, test={counts['test']}"
        )

    log.info(f"\n{'═'*50}")
    log.info("SUMMARY")
    log.info(f"{'═'*50}")
    for cls, counts in total_stats.items():
        total = sum(counts.values())
        log.info(
            f"  {cls:<15} total={total:>4}  "
            f"train={counts['train']:>4}  "
            f"val={counts['val']:>4}  "
            f"test={counts['test']:>4}"
        )
    log.info(f"{'═'*50}")
    if args.dry_run:
        log.info("DRY RUN — no files were modified.")
    else:
        log.info(f"Data written to split folders in: {cfg.TRAINING_DIR}/dataset")


if __name__ == "__main__":
    main()
