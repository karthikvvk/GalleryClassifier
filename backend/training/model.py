"""
model.py
────────
Builds the EfficientNet-B0 model with a custom 4-class head.

Two helpers:
  build_model()        — full model (both stages share this)
  freeze_backbone()    — call before Stage 1
  unfreeze_backbone()  — call before Stage 2
"""

import sys
import os

import torch
import torch.nn as nn
from torchvision.models import efficientnet_b0, EfficientNet_B0_Weights

sys.path.insert(0, os.path.dirname(__file__))
import config as cfg


def build_model(device: torch.device) -> nn.Module:
    """
    Load pretrained EfficientNet-B0 and replace the classifier head.

    EfficientNet-B0 architecture (relevant layers):
        features  →  Sequence of MBConv blocks (the backbone)
        avgpool   →  AdaptiveAvgPool2d
        classifier → Sequential(Dropout, Linear(1280, 1000))   ← we replace this

    Our replacement:
        classifier → Sequential(Dropout(p=DROPOUT_RATE), Linear(1280, NUM_CLASSES))
    """
    weights = EfficientNet_B0_Weights.IMAGENET1K_V1 if cfg.PRETRAINED else None
    model   = efficientnet_b0(weights=weights)

    # The in_features of the original classifier's Linear layer
    in_features = model.classifier[1].in_features   # 1280 for B0

    model.classifier = nn.Sequential(
        nn.Dropout(p=cfg.DROPOUT_RATE, inplace=True),
        nn.Linear(in_features, cfg.NUM_CLASSES),
    )

    return model.to(device)


def freeze_backbone(model: nn.Module) -> None:
    """
    Freeze all parameters except the classifier head.
    Called at the start of Stage 1 so only the new head trains.
    """
    for name, param in model.named_parameters():
        if "classifier" in name:
            param.requires_grad = True
        else:
            param.requires_grad = False

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total     = sum(p.numel() for p in model.parameters())
    print(f"  Backbone FROZEN  —  trainable params: {trainable:,} / {total:,}")


def unfreeze_backbone(model: nn.Module) -> None:
    """
    Unfreeze all parameters for Stage 2 end-to-end fine-tuning.
    """
    for param in model.parameters():
        param.requires_grad = True

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"  Backbone UNFROZEN  —  trainable params: {trainable:,}")


def count_parameters(model: nn.Module) -> None:
    """Print a parameter summary."""
    total     = sum(p.numel() for p in model.parameters())
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    frozen    = total - trainable
    print(f"\n{'─'*40}")
    print(f"  Total params:     {total:>10,}")
    print(f"  Trainable params: {trainable:>10,}")
    print(f"  Frozen params:    {frozen:>10,}")
    print(f"{'─'*40}\n")
