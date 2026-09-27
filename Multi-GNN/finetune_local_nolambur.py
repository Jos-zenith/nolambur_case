"""
Local, CPU-only, finetune-ONLY training run on the Nolambur synthetic dataset.

This intentionally skips Stage 1 (pretraining on IBM AML) because that dataset
(millions of transactions) and a GPU are not available on this machine — a
real local attempt at that stage was previously logged at ~150-190 hours per
epoch (see Multi-GNN/logs/logs.log). It reuses the exact same TwoStageFinetuner
training code (real GINe/GATe/PNA/RGCN model classes, real data loaders, real
loss/early-stopping) that produced the official Colab two-stage numbers in the
README -- nothing here is mocked or shortcut. It only skips a stage that isn't
locally runnable.

The resulting checkpoint is NOT the same model as the README's headline
numbers (0.0764 pretrain / 0.0667 finetune) -- it has no IBM AML pretraining
behind it, so treat its F1 as a *lower bound* / pipeline-sanity number, not a
replacement for the official two-stage result. Reproducing the official
numbers still requires a GPU run (see Multi-GNN/PRETRAIN_FINETUNE_GUIDE.md).

Usage:
    python finetune_local_nolambur.py [--epochs 30] [--model gin]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import torch
import wandb

from util import set_seed, logger_setup
from pretrain_finetune import TwoStageFinetuner, get_pretrain_parser
from train_util import get_loaders

SCRIPT_DIR = Path(__file__).resolve().parent


def main() -> None:
    base_parser = get_pretrain_parser()
    parser = argparse.ArgumentParser(parents=[base_parser], add_help=False,
                                      description="Local finetune-only run on Nolambur data")
    parser.add_argument("--finetune-epochs", type=int, default=30,
                         help="Epochs for the (only) training stage (default: 30)")
    parser.add_argument("--loss-w-ce2", type=float, default=None,
                         help="Override the fraud-class loss weight instead of the config default "
                              "(150, tuned for IBM AML's 0.10%% imbalance). Default: auto-derive "
                              "inverse-frequency weight from the actual training split.")
    args = parser.parse_args()
    args.data = "nolambur"

    with open(SCRIPT_DIR / "data_config.json", "r") as f:
        data_config = json.load(f)

    logger_setup()
    set_seed(args.seed)

    # train_stage() calls wandb.log() unconditionally (it's shared with the
    # full two-stage run, which does wandb.init() itself). This script skips
    # that -- no need for a W&B account for a local sanity-check run -- so
    # initialize in local-only "disabled" mode instead, which makes wandb.log
    # a safe no-op rather than an AttributeError.
    wandb.init(mode="disabled")

    logging.info("=" * 60)
    logging.info("LOCAL FINETUNE-ONLY RUN (no IBM AML pretrain -- see module docstring)")
    logging.info("=" * 60)

    finetuner = TwoStageFinetuner(args, data_config)

    tr, val, te, tr_inds, val_inds, te_inds = finetuner.load_and_prepare_data("FINETUNE", "nolambur")

    # model_settings.json's w_ce2=150 was tuned for IBM AML pretraining's much
    # more extreme 0.10% imbalance. Applied unchanged to Nolambur's ~1.16%
    # imbalance it over-corrects: the loss rewards flagging almost everything
    # as fraud, which is exactly what a fresh replay sample showed (clean
    # transactions scored 0.83-0.99 "fraud probability"). Auto-derive the
    # inverse-frequency weight from the actual training split instead, unless
    # the caller explicitly overrides it.
    n_train = tr.y.numel()
    n_train_pos = int(tr.y.sum().item())
    auto_w_ce2 = (n_train - n_train_pos) / max(n_train_pos, 1)
    w_ce2 = args.loss_w_ce2 if args.loss_w_ce2 is not None else auto_w_ce2
    logging.info(f"Train split: {n_train} edges, {n_train_pos} positive ({n_train_pos/n_train*100:.2f}%) "
                 f"-> loss weight [1.0, {w_ce2:.2f}] (config default was 150.0)")

    model, best_val_f1 = finetuner.train_stage(
        stage_name="FINETUNE",
        tr_data=tr, val_data=val, te_data=te,
        tr_inds=tr_inds, val_inds=val_inds, te_inds=te_inds,
        model=None,  # fresh init -- no pretrained weights available locally
        reduced_epochs=args.finetune_epochs,
        class_weight_override=(1.0, w_ce2),
    )

    # Re-verify on the held-out test split (a real, random, stratified sample
    # at the true ~1.16% base rate -- not cherry-picked) with precision and
    # recall broken out, not just F1, so an over-prediction bias like the one
    # found via bridge_api's replay feed would actually be visible here.
    te_loader = get_loaders(tr, val, te, tr_inds, val_inds, te_inds, None, args)[2]
    test_details = finetuner._evaluate_stage(te_loader, te_inds, model, te, return_details=True)
    logging.info(
        f"Test split ({test_details['n']} edges, {test_details['n_positive']} actually fraud, "
        f"{test_details['n_flagged']} flagged): "
        f"F1={test_details['f1']:.4f} Precision={test_details['precision']:.4f} Recall={test_details['recall']:.4f}"
    )

    save_dir = SCRIPT_DIR / (args.save_dir or "models")
    save_dir.mkdir(parents=True, exist_ok=True)
    save_path = save_dir / f"local_finetuned_{args.model}_nolambur.pt"
    torch.save(model.state_dict(), save_path)

    # The model was trained on z-normalized edge features (see
    # data_loading.get_data), but a checkpoint only stores weights -- it
    # cannot reproduce that normalization on its own. Persist the *train*
    # split's per-column mean/std alongside it so the serving side
    # (bridge_api.py) can normalize incoming requests the same way, instead
    # of silently feeding the model raw-scale values it was never trained on.
    norm_path = save_dir / f"local_finetuned_{args.model}_nolambur.norm.json"
    edge_attr_mean = getattr(tr, "edge_attr_mean", None)
    edge_attr_std = getattr(tr, "edge_attr_std", None)
    if edge_attr_mean is not None and edge_attr_std is not None:
        with open(norm_path, "w") as f:
            json.dump({
                "edge_features": ["Timestamp", "Amount Received", "Received Currency", "Payment Format"],
                "edge_attr_mean": edge_attr_mean.tolist(),
                "edge_attr_std": edge_attr_std.tolist(),
            }, f, indent=2)
        logging.info(f"Normalization stats saved to: {norm_path}")
    else:
        logging.warning("No edge_attr_mean/std found on train data -- normalization stats NOT saved. "
                         "/predict will be fed raw-scale features the model wasn't trained on.")

    logging.info("=" * 60)
    logging.info(f"Best Val F1 (local, no pretrain): {best_val_f1:.4f}")
    logging.info(f"Checkpoint saved to: {save_path}")
    logging.info("This is NOT the official two-stage number -- no IBM AML pretrain behind it.")
    logging.info("=" * 60)


if __name__ == "__main__":
    main()
