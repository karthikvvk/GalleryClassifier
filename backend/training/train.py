"""
train.py
────────
Two-stage fine-tuning pipeline for the GalleryClassifier.

Stage 1: Freeze backbone, train new head only  (fast, stabilises head).
Stage 2: Unfreeze, end-to-end fine-tune at low LR (extracts task-specific features).

Usage (Colab):
    !python backend/training/train.py
    !python backend/training/train.py --stage 1   # only Stage 1
    !python backend/training/train.py --stage 2   # only Stage 2 (needs stage1 checkpoint)
    !python backend/training/train.py --resume checkpoints/stage1_best.pt --stage 2

Outputs (written to backend/training/checkpoints/):
    stage1_best.pt     — best val-accuracy checkpoint from Stage 1
    stage2_best.pt     — best val-accuracy checkpoint from Stage 2  ← use this for export
    stage2_final.pt    — last epoch checkpoint from Stage 2
    training_log.csv   — epoch-level metrics for both stages
"""

import os
import sys
import csv
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime

import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR
from sklearn.metrics import confusion_matrix, classification_report

sys.path.insert(0, os.path.dirname(__file__))
import config as cfg
from dataset import get_dataloaders, dataset_summary
from model import build_model, freeze_backbone, unfreeze_backbone, count_parameters

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def get_device() -> torch.device:
    if torch.cuda.is_available():
        device = torch.device("cuda")
        log.info(f"GPU: {torch.cuda.get_device_name(0)}  "
                 f"({torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB VRAM)")
    else:
        device = torch.device("cpu")
        log.warning("No GPU found — training on CPU (will be slow).")
    return device


def compute_class_weights(train_loader, device: torch.device) -> torch.Tensor:
    """
    Compute inverse-frequency class weights for CrossEntropyLoss.
    Used only as a secondary safeguard; WeightedRandomSampler already
    balances batches, but weighted loss helps emphasise minority classes
    in gradient magnitude too.
    """
    from dataset import GalleryDataset
    ds: GalleryDataset = train_loader.dataset  # type: ignore
    counts = ds.class_counts()
    total  = sum(counts)
    weights = torch.tensor(
        [total / (cfg.NUM_CLASSES * max(c, 1)) for c in counts],
        dtype=torch.float,
        device=device,
    )
    log.info(f"  Class weights: { {cls: f'{w:.3f}' for cls, w in zip(cfg.CLASSES, weights.tolist())} }")
    return weights


# ─────────────────────────────────────────────────────────────────────────────
# EPOCH LOOP
# ─────────────────────────────────────────────────────────────────────────────

def run_epoch(
    model: nn.Module,
    loader,
    criterion: nn.Module,
    optimizer,
    device: torch.device,
    is_train: bool,
) -> tuple[float, float]:
    """
    Run one epoch.
    Returns (avg_loss, accuracy_percent).
    """
    model.train() if is_train else model.eval()

    total_loss = 0.0
    correct    = 0
    total      = 0

    ctx = torch.enable_grad() if is_train else torch.no_grad()

    with ctx:
        for images, labels in loader:
            images = images.to(device, non_blocking=True)
            labels = labels.to(device, non_blocking=True)

            logits = model(images)
            loss   = criterion(logits, labels)

            if is_train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            total_loss += loss.item() * images.size(0)
            preds       = logits.argmax(dim=1)
            correct    += (preds == labels).sum().item()
            total      += images.size(0)

    avg_loss = total_loss / max(total, 1)
    accuracy = 100.0 * correct / max(total, 1)
    return avg_loss, accuracy


# ─────────────────────────────────────────────────────────────────────────────
# EVALUATION  (detailed per-class report)
# ─────────────────────────────────────────────────────────────────────────────

def evaluate(model: nn.Module, loader, device: torch.device, split: str = "test") -> None:
    """
    Full evaluation with confusion matrix + classification report.
    Prints to stdout. Call after Stage 2 completes (or for the test set).
    """
    model.eval()
    all_preds  = []
    all_labels = []

    with torch.no_grad():
        for images, labels in loader:
            images = images.to(device, non_blocking=True)
            logits = model(images)
            preds  = logits.argmax(dim=1).cpu().tolist()
            all_preds.extend(preds)
            all_labels.extend(labels.tolist())

    print(f"\n{'═'*60}")
    print(f"  {split.upper()} SET EVALUATION")
    print(f"{'═'*60}")
    print(classification_report(
        all_labels, all_preds,
        target_names=cfg.CLASSES,
        digits=4,
    ))

    cm = confusion_matrix(all_labels, all_preds)
    print("Confusion matrix (rows=actual, cols=predicted):")
    header = "".join(f"{c[:6]:>8}" for c in cfg.CLASSES)
    print(f"{'':>10} {header}")
    for i, row in enumerate(cm):
        values = "".join(f"{v:>8}" for v in row)
        print(f"  {cfg.CLASSES[i]:<10}{values}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# CHECKPOINT HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def save_checkpoint(
    model: nn.Module,
    optimizer,
    epoch: int,
    val_acc: float,
    stage: int,
    filename: str,
) -> None:
    os.makedirs(cfg.CHECKPOINT_DIR, exist_ok=True)
    path = os.path.join(cfg.CHECKPOINT_DIR, filename)
    torch.save(
        {
            "epoch":    epoch,
            "stage":    stage,
            "val_acc":  val_acc,
            "classes":  cfg.CLASSES,
            "model_state_dict":     model.state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
        },
        path,
    )
    log.info(f"  Checkpoint saved → {path}  (val_acc={val_acc:.2f}%)")


def load_checkpoint(model: nn.Module, optimizer, path: str, device: torch.device):
    ckpt = torch.load(path, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    if optimizer is not None:
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
    log.info(
        f"  Loaded checkpoint: {path}  "
        f"(stage={ckpt.get('stage','?')}, epoch={ckpt.get('epoch','?')}, "
        f"val_acc={ckpt.get('val_acc', 0):.2f}%)"
    )
    return ckpt


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1
# ─────────────────────────────────────────────────────────────────────────────

def train_stage1(
    model: nn.Module,
    train_loader,
    val_loader,
    criterion: nn.Module,
    device: torch.device,
    csv_writer,
) -> str:
    """
    Stage 1: freeze backbone, train head only.
    Returns path to best checkpoint.
    """
    log.info(f"\n{'═'*60}")
    log.info("  STAGE 1  —  Head only (backbone frozen)")
    log.info(f"  Epochs={cfg.STAGE1_EPOCHS}  LR={cfg.STAGE1_LR}  Batch={cfg.STAGE1_BATCH}")
    log.info(f"{'═'*60}")

    freeze_backbone(model)
    count_parameters(model)

    # Only pass classifier parameters to optimizer (frozen params are excluded
    # but being explicit is safer and gives a cleaner optimizer state)
    optimizer = AdamW(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=cfg.STAGE1_LR,
        weight_decay=cfg.WEIGHT_DECAY,
    )

    best_val_acc   = 0.0
    best_ckpt_path = os.path.join(cfg.CHECKPOINT_DIR, "stage1_best.pt")

    for epoch in range(1, cfg.STAGE1_EPOCHS + 1):
        t0 = time.time()

        train_loss, train_acc = run_epoch(
            model, train_loader, criterion, optimizer, device, is_train=True
        )
        val_loss, val_acc = run_epoch(
            model, val_loader, criterion, optimizer=None, device=device, is_train=False
        )

        elapsed = time.time() - t0
        log.info(
            f"  [S1 E{epoch:02d}/{cfg.STAGE1_EPOCHS}]  "
            f"train_loss={train_loss:.4f}  train_acc={train_acc:.2f}%  "
            f"val_loss={val_loss:.4f}  val_acc={val_acc:.2f}%  "
            f"({elapsed:.0f}s)"
        )

        csv_writer.writerow({
            "stage": 1, "epoch": epoch,
            "train_loss": f"{train_loss:.6f}", "train_acc": f"{train_acc:.4f}",
            "val_loss":   f"{val_loss:.6f}",   "val_acc":   f"{val_acc:.4f}",
            "lr": cfg.STAGE1_LR,
        })

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            save_checkpoint(model, optimizer, epoch, val_acc, stage=1, filename="stage1_best.pt")

    log.info(f"  Stage 1 complete.  Best val_acc={best_val_acc:.2f}%")
    return best_ckpt_path


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2
# ─────────────────────────────────────────────────────────────────────────────

def train_stage2(
    model: nn.Module,
    train_loader,
    val_loader,
    criterion: nn.Module,
    device: torch.device,
    csv_writer,
) -> str:
    """
    Stage 2: unfreeze all, fine-tune end-to-end at low LR with cosine schedule.
    Returns path to best checkpoint.
    """
    log.info(f"\n{'═'*60}")
    log.info("  STAGE 2  —  Full fine-tune (backbone unfrozen)")
    log.info(f"  Epochs={cfg.STAGE2_EPOCHS}  LR={cfg.STAGE2_LR}  Batch={cfg.STAGE2_BATCH}")
    log.info(f"{'═'*60}")

    unfreeze_backbone(model)
    count_parameters(model)

    optimizer = AdamW(
        model.parameters(),
        lr=cfg.STAGE2_LR,
        weight_decay=cfg.WEIGHT_DECAY,
    )
    scheduler = CosineAnnealingLR(
        optimizer,
        T_max=cfg.STAGE2_EPOCHS,
        eta_min=cfg.STAGE2_LR_MIN,
    )

    best_val_acc    = 0.0
    best_ckpt_path  = os.path.join(cfg.CHECKPOINT_DIR, "stage2_best.pt")
    no_improve_cnt  = 0   # for early stopping

    for epoch in range(1, cfg.STAGE2_EPOCHS + 1):
        t0 = time.time()

        train_loss, train_acc = run_epoch(
            model, train_loader, criterion, optimizer, device, is_train=True
        )
        val_loss, val_acc = run_epoch(
            model, val_loader, criterion, optimizer=None, device=device, is_train=False
        )

        current_lr = scheduler.get_last_lr()[0]
        scheduler.step()

        elapsed = time.time() - t0
        log.info(
            f"  [S2 E{epoch:02d}/{cfg.STAGE2_EPOCHS}]  "
            f"train_loss={train_loss:.4f}  train_acc={train_acc:.2f}%  "
            f"val_loss={val_loss:.4f}  val_acc={val_acc:.2f}%  "
            f"lr={current_lr:.2e}  ({elapsed:.0f}s)"
        )

        csv_writer.writerow({
            "stage": 2, "epoch": epoch,
            "train_loss": f"{train_loss:.6f}", "train_acc": f"{train_acc:.4f}",
            "val_loss":   f"{val_loss:.6f}",   "val_acc":   f"{val_acc:.4f}",
            "lr": f"{current_lr:.2e}",
        })

        if val_acc > best_val_acc:
            best_val_acc   = val_acc
            no_improve_cnt = 0
            save_checkpoint(model, optimizer, epoch, val_acc, stage=2, filename="stage2_best.pt")
        else:
            no_improve_cnt += 1
            if no_improve_cnt >= cfg.EARLY_STOP_PATIENCE:
                log.info(
                    f"  Early stopping at epoch {epoch} "
                    f"(no improvement for {cfg.EARLY_STOP_PATIENCE} epochs)"
                )
                break

    # Always save final weights too (useful for comparison)
    save_checkpoint(
        model, optimizer, epoch, val_acc, stage=2, filename="stage2_final.pt"
    )

    log.info(f"  Stage 2 complete.  Best val_acc={best_val_acc:.2f}%")
    return best_ckpt_path


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GalleryClassifier Training")
    parser.add_argument(
        "--stage", type=int, choices=[1, 2], default=None,
        help="Run only Stage 1 or Stage 2. Default: run both sequentially.",
    )
    parser.add_argument(
        "--resume", type=str, default=None,
        help="Path to checkpoint to resume from (for Stage 2 standalone run).",
    )
    args = parser.parse_args()

    torch.manual_seed(cfg.RANDOM_SEED)
    device = get_device()

    # ── Data ───────────────────────────────────────────────────────────────
    log.info("\nLoading datasets...")
    # Stage 1 and Stage 2 may have different batch sizes (both 64 here, but
    # kept flexible through separate loader calls if needed)
    train_loader_s1, val_loader, test_loader = get_dataloaders(cfg.STAGE1_BATCH)
    train_loader_s2, _,          _           = get_dataloaders(cfg.STAGE2_BATCH)

    dataset_summary(train_loader_s1, "Train")
    dataset_summary(val_loader,      "Val")
    dataset_summary(test_loader,     "Test")

    # ── Model ──────────────────────────────────────────────────────────────
    log.info("\nBuilding model...")
    model = build_model(device)

    # ── Loss ───────────────────────────────────────────────────────────────
    class_weights = compute_class_weights(train_loader_s1, device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)

    # ── CSV log ────────────────────────────────────────────────────────────
    os.makedirs(cfg.LOG_DIR, exist_ok=True)
    log_path = os.path.join(
        cfg.LOG_DIR,
        f"training_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    log_fields = ["stage", "epoch", "train_loss", "train_acc", "val_loss", "val_acc", "lr"]

    with open(log_path, "w", newline="") as log_file:
        csv_writer = csv.DictWriter(log_file, fieldnames=log_fields)
        csv_writer.writeheader()

        # ── Stage 1 ────────────────────────────────────────────────────────
        if args.stage in (None, 1):
            s1_best = train_stage1(
                model, train_loader_s1, val_loader, criterion, device, csv_writer
            )
        elif args.stage == 2 and args.resume:
            # Load Stage 1 checkpoint before Stage 2
            load_checkpoint(model, optimizer=None, path=args.resume, device=device)

        # ── Stage 2 ────────────────────────────────────────────────────────
        if args.stage in (None, 2):
            if args.stage == 2 and not args.resume:
                # Load the best stage 1 checkpoint automatically
                s1_path = os.path.join(cfg.CHECKPOINT_DIR, "stage1_best.pt")
                if os.path.exists(s1_path):
                    load_checkpoint(model, optimizer=None, path=s1_path, device=device)
                else:
                    log.warning("No stage1_best.pt found — starting Stage 2 from pretrained weights")

            s2_best = train_stage2(
                model, train_loader_s2, val_loader, criterion, device, csv_writer
            )

    # ── Final test evaluation ───────────────────────────────────────────────
    if args.stage in (None, 2):
        best_path = os.path.join(cfg.CHECKPOINT_DIR, "stage2_best.pt")
        if os.path.exists(best_path):
            load_checkpoint(model, optimizer=None, path=best_path, device=device)
        evaluate(model, test_loader, device, split="test")

    log.info(f"\nTraining log saved → {log_path}")
    log.info("Run export.py to convert the best checkpoint to ONNX.")


if __name__ == "__main__":
    main()
