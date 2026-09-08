"""
dataset.py
──────────
Custom dataset with per-class augmentation policies.

Key design decisions:
  - Screenshots / wallpapers get NO rotation (they're never rotated in a gallery).
  - Camera photos get mild rotation (real-world orientation variance).
  - Memes get NO rotation but ARE colour-jitter eligible (covers filter-heavy posts).
  - Global conservative jitter is applied to all classes.
  - WeightedRandomSampler weights are computed from class frequencies.
"""

import os
import sys
from pathlib import Path

import torch
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from torchvision import transforms
from PIL import Image, UnidentifiedImageError

sys.path.insert(0, os.path.dirname(__file__))
import config as cfg

# ─────────────────────────────────────────────────────────────────────────────
# NORMALISATION CONSTANTS  (ImageNet mean/std — must match backbone pretraining)
# ─────────────────────────────────────────────────────────────────────────────
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD  = [0.229, 0.224, 0.225]


# ─────────────────────────────────────────────────────────────────────────────
# AUGMENTATION PIPELINES
# ─────────────────────────────────────────────────────────────────────────────

def _base_jitter() -> transforms.ColorJitter:
    return transforms.ColorJitter(
        brightness=cfg.JITTER_BRIGHTNESS,
        contrast=cfg.JITTER_CONTRAST,
        saturation=cfg.JITTER_SATURATION,
        hue=cfg.JITTER_HUE,
    )


def _normalize() -> transforms.Normalize:
    return transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD)


# Per-class train-time augmentation transforms
CLASS_TRAIN_TRANSFORMS: dict[str, transforms.Compose] = {

    "camera": transforms.Compose([
        transforms.Resize((cfg.IMAGE_SIZE, cfg.IMAGE_SIZE)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(cfg.CAMERA_MAX_ROTATION),  # real-world rotation
        _base_jitter(),
        transforms.ToTensor(),
        _normalize(),
    ]),

    "memes": transforms.Compose([
        transforms.Resize((cfg.IMAGE_SIZE, cfg.IMAGE_SIZE)),
        transforms.RandomHorizontalFlip(),
        # No rotation — memes have fixed text orientation
        _base_jitter(),
        transforms.ToTensor(),
        _normalize(),
    ]),

    "screenshots": transforms.Compose([
        transforms.Resize((cfg.IMAGE_SIZE, cfg.IMAGE_SIZE)),
        # No flip or rotation — UI chrome is orientation-specific
        # Mild jitter only (covers dark-mode / light-mode variation)
        transforms.ColorJitter(brightness=0.1, contrast=0.1),
        transforms.ToTensor(),
        _normalize(),
    ]),

    "wallpapers": transforms.Compose([
        transforms.Resize((cfg.IMAGE_SIZE, cfg.IMAGE_SIZE)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomCrop(cfg.IMAGE_SIZE, padding=4),   # simulates wallpaper pan/zoom
        _base_jitter(),
        transforms.ToTensor(),
        _normalize(),
    ]),
}

# Validation / test — deterministic, no augmentation
EVAL_TRANSFORM = transforms.Compose([
    transforms.Resize((cfg.IMAGE_SIZE, cfg.IMAGE_SIZE)),
    transforms.ToTensor(),
    _normalize(),
])


# ─────────────────────────────────────────────────────────────────────────────
# DATASET
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class GalleryDataset(Dataset):
    """
    Loads images from a directory structured as:
        root/
            camera/   img1.jpg ...
            memes/    img1.jpg ...
            ...

    Applies per-class augmentation when is_train=True, otherwise uses
    the deterministic EVAL_TRANSFORM.
    """

    def __init__(self, root: str, is_train: bool = True):
        self.root     = Path(root)
        self.is_train = is_train
        self.class_to_idx = {c: i for i, c in enumerate(cfg.CLASSES)}

        self.samples: list[tuple[Path, int]] = []  # (image_path, class_idx)

        for class_name in cfg.CLASSES:
            class_dir = self.root / class_name
            if not class_dir.is_dir():
                continue
            idx = self.class_to_idx[class_name]
            for img_path in sorted(class_dir.iterdir()):
                if img_path.suffix.lower() in SUPPORTED_EXTS:
                    self.samples.append((img_path, idx))

        if len(self.samples) == 0:
            raise RuntimeError(
                f"No images found in {root}. "
                "Run prepare_data.py first to create the split folders."
            )

    # ── map class index → class name (reverse lookup) ──────────────────────
    def idx_to_class(self, idx: int) -> str:
        return cfg.CLASSES[idx]

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        img_path, label = self.samples[index]
        class_name = cfg.CLASSES[label]

        try:
            img = Image.open(img_path).convert("RGB")
        except (UnidentifiedImageError, Exception):
            # Return a black image so one bad file doesn't crash training
            img = Image.new("RGB", (cfg.IMAGE_SIZE, cfg.IMAGE_SIZE), (0, 0, 0))

        if self.is_train:
            transform = CLASS_TRAIN_TRANSFORMS[class_name]
        else:
            transform = EVAL_TRANSFORM

        return transform(img), label

    # ── helper: class counts (for WeightedRandomSampler) ───────────────────
    def class_counts(self) -> list[int]:
        counts = [0] * cfg.NUM_CLASSES
        for _, label in self.samples:
            counts[label] += 1
        return counts


# ─────────────────────────────────────────────────────────────────────────────
# DATALOADER FACTORY
# ─────────────────────────────────────────────────────────────────────────────

def make_weighted_sampler(dataset: GalleryDataset) -> WeightedRandomSampler:
    """
    Build a WeightedRandomSampler so every batch is roughly class-balanced.
    Each image gets weight = 1 / count_of_its_class.
    """
    counts = dataset.class_counts()
    # Avoid division by zero for missing classes
    weights_per_class = [
        1.0 / c if c > 0 else 0.0 for c in counts
    ]
    sample_weights = torch.tensor(
        [weights_per_class[label] for _, label in dataset.samples],
        dtype=torch.float,
    )
    return WeightedRandomSampler(
        weights=sample_weights,
        num_samples=len(sample_weights),
        replacement=True,
    )


def get_dataloaders(
    batch_size: int,
) -> tuple[DataLoader, DataLoader, DataLoader]:
    """
    Returns (train_loader, val_loader, test_loader).
    Train loader uses WeightedRandomSampler for class balance.
    Val and test loaders are sequential (no shuffle, no sampler).
    """
    train_ds = GalleryDataset(cfg.TRAIN_DIR, is_train=True)
    val_ds   = GalleryDataset(cfg.VAL_DIR,   is_train=False)
    test_ds  = GalleryDataset(cfg.TEST_DIR,  is_train=False)

    sampler = make_weighted_sampler(train_ds)

    train_loader = DataLoader(
        train_ds,
        batch_size=batch_size,
        sampler=sampler,           # mutually exclusive with shuffle=True
        num_workers=cfg.NUM_WORKERS,
        pin_memory=cfg.PIN_MEMORY,
        drop_last=True,
    )
    val_loader = DataLoader(
        val_ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=cfg.NUM_WORKERS,
        pin_memory=cfg.PIN_MEMORY,
    )
    test_loader = DataLoader(
        test_ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=cfg.NUM_WORKERS,
        pin_memory=cfg.PIN_MEMORY,
    )

    return train_loader, val_loader, test_loader


def dataset_summary(loader: DataLoader, split: str) -> None:
    """Print class distribution for a dataloader's underlying dataset."""
    ds: GalleryDataset = loader.dataset  # type: ignore[assignment]
    counts = ds.class_counts()
    total  = sum(counts)
    print(f"\n{split} split  ({total} images)")
    for cls, cnt in zip(cfg.CLASSES, counts):
        bar = "█" * int(30 * cnt / max(total, 1))
        print(f"  {cls:<15} {cnt:>5}  {bar}")
