"""
config.py
─────────
Single source of truth for all hyperparameters, paths, and class definitions.
Modify this file to change training behaviour — nothing else needs to change.
"""

import os

# ──────────────────────────────────────────────
# CLASSES
# ──────────────────────────────────────────────
# Order matters — index 0 = class 0 in the model output.
# Must match the folder names under data/train/, data/val/, data/test/
CLASSES = ["camera", "memes", "screenshots", "wallpapers"]
NUM_CLASSES = len(CLASSES)

# ──────────────────────────────────────────────
# PATHS
# ──────────────────────────────────────────────
# Root of the project (one level above backend/)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DATA_ROOT       = os.path.join(PROJECT_ROOT, "data")
RAW_DATA_DIR    = os.path.join(DATA_ROOT, "raw")
TRAIN_DIR       = os.path.join(DATA_ROOT, "train")
VAL_DIR         = os.path.join(DATA_ROOT, "val")
TEST_DIR        = os.path.join(DATA_ROOT, "test")

CHECKPOINT_DIR  = os.path.join(PROJECT_ROOT, "backend", "training", "checkpoints")
EXPORT_DIR      = os.path.join(PROJECT_ROOT, "backend", "runtime")
LOG_DIR         = os.path.join(PROJECT_ROOT, "backend", "training", "logs")

# ──────────────────────────────────────────────
# MODEL
# ──────────────────────────────────────────────
BACKBONE        = "efficientnet_b0"
PRETRAINED      = True
IMAGE_SIZE      = 224
DROPOUT_RATE    = 0.3

# ──────────────────────────────────────────────
# TRAINING — STAGE 1 (head only, backbone frozen)
# ──────────────────────────────────────────────
STAGE1_EPOCHS   = 5
STAGE1_LR       = 1e-3
STAGE1_BATCH    = 64

# ──────────────────────────────────────────────
# TRAINING — STAGE 2 (full fine-tune, low LR)
# ──────────────────────────────────────────────
STAGE2_EPOCHS   = 25
STAGE2_LR       = 1e-4
STAGE2_BATCH    = 64
STAGE2_LR_MIN   = 1e-6

# ──────────────────────────────────────────────
# REGULARISATION
# ──────────────────────────────────────────────
WEIGHT_DECAY    = 1e-4

# ──────────────────────────────────────────────
# AUGMENTATION
# Conservative: screenshots/memes are never rotated in real life.
# ──────────────────────────────────────────────
JITTER_BRIGHTNESS   = 0.2
JITTER_CONTRAST     = 0.2
JITTER_SATURATION   = 0.1
JITTER_HUE          = 0.05
CAMERA_MAX_ROTATION = 15   # degrees, applied only to camera class

# ──────────────────────────────────────────────
# DATA SPLIT RATIOS
# ──────────────────────────────────────────────
TRAIN_RATIO = 0.80
VAL_RATIO   = 0.10
TEST_RATIO  = 0.10

# ──────────────────────────────────────────────
# DEDUP
# ──────────────────────────────────────────────
DEDUP_HASH_SIZE     = 8
DEDUP_MAX_DISTANCE  = 10

# ──────────────────────────────────────────────
# MISC
# ──────────────────────────────────────────────
RANDOM_SEED          = 42
NUM_WORKERS          = 2
PIN_MEMORY           = True
EARLY_STOP_PATIENCE  = 7
CONFIDENCE_THRESHOLD = 0.60
