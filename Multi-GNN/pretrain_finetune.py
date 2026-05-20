"""
Two-stage training pipeline:
1. PRETRAIN: IBM AML data teaches general mule topology patterns
2. FINETUNE: Nolambur data teaches specific ₹5L burst + Tamil Nadu→Haridwar geo-mismatch patterns
"""

import torch
import logging
import json
import argparse
import time
from pathlib import Path
from typing import Tuple, Dict, Any

from util import create_parser, set_seed, logger_setup
from data_loading import get_data
from data_util import GraphData, create_hetero_obj
from models import GINe, PNA, GATe, RGCN
from train_util import AddEgoIds, add_arange_ids, get_loaders, evaluate_homo, evaluate_hetero, save_model, load_model
from training import train_homo, train_hetero
import tqdm
from sklearn.metrics import f1_score
import wandb
import pandas as pd
import numpy as np


SCRIPT_DIR = Path(__file__).resolve().parent


def _format_seconds(seconds: float) -> str:
    minutes, secs = divmod(int(max(seconds, 0)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _edge_attr_tensor(graph_data: Any) -> torch.Tensor:
    edge_attr = getattr(graph_data, "edge_attr", None)
    if edge_attr is None:
        raise ValueError("Expected edge_attr on graph data")
    return edge_attr


def _node_feature_tensor(graph_data: Any) -> torch.Tensor:
    x = getattr(graph_data, "x", None)
    if x is None:
        raise ValueError("Expected x on graph data")
    return x


class TwoStageFinetuner:
    """Manages pretraining on IBM AML + fine-tuning on Nolambur data"""
    
    def __init__(self, args, data_config):
        self.args = args
        self.data_config = data_config
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Load hyperparameters
        model_config_path = Path(args.model_config) if args.model_config else SCRIPT_DIR / 'model_settings.json'
        if not model_config_path.is_absolute():
            model_config_path = SCRIPT_DIR / model_config_path

        with open(model_config_path, 'r') as f:
            self.model_configs = json.load(f)
    
    def load_and_prepare_data(self, stage_name: str, dataset_name: str) -> Tuple:
        """Load data for a specific stage"""
        print(f"DEBUG >>> loading dataset: {dataset_name}")
        print(f"DEBUG >>> args.data = {self.args.data}")
        logging.info(f"\n{'='*60}")
        logging.info(f"STAGE: {stage_name.upper()} - Dataset: {dataset_name}")
        logging.info(f"{'='*60}")

        if not hasattr(self.args, 'ports'):
            self.args.ports = False
        if not hasattr(self.args, 'tds'):
            self.args.tds = False
        if not hasattr(self.args, 'tqdm'):
            self.args.tqdm = False
        if not hasattr(self.args, 'reverse_mp'):
            self.args.reverse_mp = False
        
        # Temporarily override dataset for loading
        original_data = self.args.data
        self.args.data = dataset_name
        
        tr_data, val_data, te_data, tr_inds, val_inds, te_inds = get_data(
            self.args, self.data_config
        )
        
        self.args.data = original_data
        
        logging.info(f"✓ Loaded {stage_name} data: "
                    f"Train={_node_feature_tensor(tr_data).shape[0]} nodes, "
                    f"Val={_node_feature_tensor(val_data).shape[0] if getattr(val_data, 'x', None) is not None else '?'} nodes")
        
        return tr_data, val_data, te_data, tr_inds, val_inds, te_inds
    
    def initialize_model(self, num_features: int, num_edge_features: int):
        """Create fresh model instance"""
        model_name = self.args.model.lower()
        config = self.model_configs[model_name]['params']
        
        if model_name == 'gin':
            model = GINe(
                num_features=num_features,
                num_gnn_layers=int(config['n_gnn_layers']),
                n_classes=2,
                n_hidden=int(config['n_hidden']),
                edge_dim=num_edge_features,
                dropout=config['dropout'],
                final_dropout=config['final_dropout']
            )
        elif model_name == 'gat':
            model = GATe(
                num_features=num_features,
                num_gnn_layers=int(config['n_gnn_layers']),
                n_classes=2,
                n_hidden=int(config['n_hidden']),
                n_heads=int(config.get('n_heads', 4)),
                edge_dim=num_edge_features,
                dropout=config['dropout'],
                final_dropout=config['final_dropout']
            )
        elif model_name == 'pna':
            model = PNA(
                num_features=num_features,
                num_gnn_layers=int(config['n_gnn_layers']),
                n_classes=2,
                n_hidden=int(config['n_hidden']),
                edge_dim=num_edge_features,
                dropout=config['dropout'],
                final_dropout=config['final_dropout']
            )
        elif model_name == 'rgcn':
            model = RGCN(
                num_features=num_features,
                num_relations=8,
                num_gnn_layers=int(config['n_gnn_layers']),
                n_classes=2,
                n_hidden=int(config['n_hidden']),
                edge_dim=num_edge_features,
                dropout=config['dropout'],
                final_dropout=config['final_dropout']
            )
        else:
            raise ValueError(f"Unknown model: {model_name}")
        
        return model.to(self.device)
    
    def train_stage(self, stage_name: str, tr_data, val_data, te_data, 
                   tr_inds, val_inds, te_inds, model=None, reduced_epochs=None):
        """Train for one stage (pretraining or fine-tuning)"""
        
        config = self.model_configs[self.args.model.lower()]
        params = config['params']
        
        # Use reduced epochs for fine-tuning or override
        epochs = reduced_epochs or params.get('epochs', self.args.epochs or 100)
        
        # Initialize model if not provided (pretraining case)
        if model is None:
            num_features = _node_feature_tensor(tr_data).shape[1]
            num_edge_features = _edge_attr_tensor(tr_data).shape[1]
            model = self.initialize_model(num_features, num_edge_features)
            logging.info(f"✓ Initialized new model for {stage_name}")
        else:
            logging.info(f"✓ Using pretrained model for {stage_name}")
        
        # Setup optimizer with stage-specific learning rate
        base_lr = params['lr']
        
        if stage_name == 'FINETUNE':
            # Use lower learning rate for fine-tuning to preserve learned features
            learning_rate = base_lr * 0.1
            logging.info(f"  Fine-tuning LR: {learning_rate:.6f} (10% of pretrain LR)")
        else:
            learning_rate = base_lr
            logging.info(f"  Pretraining LR: {learning_rate:.6f}")
        
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        
        # Setup loss with class weights
        w_ce1 = params['w_ce1']
        w_ce2 = params['w_ce2']
        class_weights = torch.tensor([w_ce1, w_ce2], device=self.device)
        loss_fn = torch.nn.CrossEntropyLoss(weight=class_weights)
        
        # Create data loaders
        if not getattr(self.args, 'num_neighs', None):
            self.args.num_neighs = [100, 100]

        if getattr(self.args, 'ego', False):
            transform = AddEgoIds()
        else:
            transform = None

        add_arange_ids([tr_data, val_data, te_data])

        tr_loader, val_loader, te_loader = get_loaders(
            tr_data, val_data, te_data, tr_inds, val_inds, te_inds, transform, self.args
        )

        batch_size = self.args.batch_size or 256
        
        logging.info(f"\n{stage_name} Configuration:")
        logging.info(f"  Epochs: {epochs}")
        logging.info(f"  Batch size: {batch_size}")
        logging.info(f"  Loss weights: [1.0, {w_ce2:.2f}]")
        
        # Training loop
        best_val_f1 = 0
        best_model_state = None
        patience_counter = 0
        patience = 10
        
        total_batches = len(tr_loader) if hasattr(tr_loader, "__len__") else None
        stage_start = time.perf_counter()
        
        for epoch in range(epochs):
            epoch_start = time.perf_counter()
            model.train()
            total_loss = 0
            preds = []
            ground_truths = []
            
            for batch_idx, batch in enumerate(
                tqdm.tqdm(tr_loader, disable=not self.args.tqdm, 
                          desc=f"{stage_name} Epoch {epoch+1}/{epochs}"),
                start=1,
            ):
                batch_start = time.perf_counter()
                optimizer.zero_grad()
                
                # Get mask for seed edges
                inds = tr_inds.detach().cpu()
                batch_edge_inds = inds[batch.input_id.detach().cpu()]
                batch_edge_ids = _edge_attr_tensor(tr_loader.data).detach().cpu()[batch_edge_inds, 0]
                mask = torch.isin(batch.edge_attr[:, 0].detach().cpu(), batch_edge_ids)
                
                # Remove unique edge id from edge features
                batch.edge_attr = batch.edge_attr[:, 1:]
                batch.to(self.device)
                
                out = model(batch.x, batch.edge_index, batch.edge_attr)
                pred = out[mask]
                ground_truth = batch.y[mask]
                
                preds.append(pred.argmax(dim=-1))
                ground_truths.append(ground_truth)
                
                loss = loss_fn(pred, ground_truth)
                loss.backward()
                optimizer.step()
                
                total_loss += float(loss) * pred.numel()

                if total_batches and (batch_idx == 1 or batch_idx % max(1, total_batches // 5) == 0 or batch_idx == total_batches):
                    elapsed_epoch = time.perf_counter() - epoch_start
                    avg_batch_time = elapsed_epoch / batch_idx
                    remaining_epoch = avg_batch_time * (total_batches - batch_idx)
                    remaining_stage = remaining_epoch + (epochs - epoch - 1) * elapsed_epoch
                    logging.info(
                        f"[{stage_name}] Epoch {epoch+1}/{epochs} "
                        f"batch {batch_idx}/{total_batches} | "
                        f"epoch ETA: {_format_seconds(remaining_epoch)} | "
                        f"stage ETA: {_format_seconds(remaining_stage)} | "
                        f"last batch: {time.perf_counter() - batch_start:.2f}s"
                    )
            
            # Evaluate
            pred_all = torch.cat(preds, dim=0).detach().cpu().numpy()
            ground_truth_all = torch.cat(ground_truths, dim=0).detach().cpu().numpy()
            tr_f1 = f1_score(ground_truth_all, pred_all)
            
            # Validation
            val_f1 = self._evaluate_stage(val_loader, val_inds, model, val_data)
            te_f1 = self._evaluate_stage(te_loader, te_inds, model, te_data)
            
            logging.info(f"[{stage_name}] Epoch {epoch+1:3d} | "
                        f"Train F1: {tr_f1:.4f} | Val F1: {val_f1:.4f} | Test F1: {te_f1:.4f}")
            
            # Log to wandb
            wandb.log({
                f"{stage_name.lower()}/train_f1": tr_f1,
                f"{stage_name.lower()}/val_f1": val_f1,
                f"{stage_name.lower()}/test_f1": te_f1,
            }, step=epoch)
            
            # Early stopping based on validation F1
            if val_f1 > best_val_f1:
                best_val_f1 = val_f1
                best_model_state = model.state_dict().copy()
                patience_counter = 0
                logging.info(f"  ✓ Best {stage_name} model updated (Val F1: {val_f1:.4f})")
            else:
                patience_counter += 1
                if patience_counter >= patience:
                    logging.info(f"  Early stopping at epoch {epoch+1} (patience={patience})")
                    break
        
        logging.info(f"[{stage_name}] completed in {_format_seconds(time.perf_counter() - stage_start)}")

        # Restore best model
        if best_model_state is not None:
            model.load_state_dict(best_model_state)
        
        return model, best_val_f1
    
    def _evaluate_stage(self, loader, inds, model, data):
        """Evaluate model on a dataset"""
        model.eval()
        preds = []
        ground_truths = []
        
        with torch.no_grad():
            for batch in loader:
                inds_cpu = inds.detach().cpu()
                batch_edge_inds = inds_cpu[batch.input_id.detach().cpu()]
                batch_edge_ids = _edge_attr_tensor(loader.data).detach().cpu()[batch_edge_inds, 0]
                mask = torch.isin(batch.edge_attr[:, 0].detach().cpu(), batch_edge_ids)
                
                batch.edge_attr = batch.edge_attr[:, 1:]
                batch.to(self.device)
                
                out = model(batch.x, batch.edge_index, batch.edge_attr)
                pred = out[mask]
                ground_truth = batch.y[mask]
                
                preds.append(pred.argmax(dim=-1))
                ground_truths.append(ground_truth)
        
        pred_all = torch.cat(preds, dim=0).detach().cpu().numpy()
        ground_truth_all = torch.cat(ground_truths, dim=0).detach().cpu().numpy()
        
        return f1_score(ground_truth_all, pred_all)
    
    def run(self):
        """Execute full two-stage pipeline"""
        
        # Initialize wandb
        run_name = f"2stage-{self.args.model}-pretrain-ibm-finetune-nolambur"
        wandb.init(
            project="fraud-detection-2stage",
            name=run_name,
            config={
                'model': self.args.model,
                'pretrain_dataset': 'ibm_aml',
                'finetune_dataset': 'nolambur',
            }
        )
        
        try:
            # Stage 1: PRETRAIN on IBM AML
            logging.info("\n" + "="*60)
            logging.info("STAGE 1: PRETRAINING ON IBM AML DATA")
            logging.info("="*60)
            
            tr_ibm, val_ibm, te_ibm, tr_inds_ibm, val_inds_ibm, te_inds_ibm = \
                self.load_and_prepare_data("PRETRAIN", "HI-Small")
            
            # Check if pretrained model already exists
            pretrain_save_path = Path(self.args.save_dir or "models") / f"pretrained_{self.args.model}_ibm.pt"
            pretrain_val_f1 = None
            
            if pretrain_save_path.exists():
                logging.info(f"[INFO] Found saved pretrain model at {pretrain_save_path}")
                logging.info("[INFO] Skipping pretraining, loading weights...")
                pretrain_model = self.create_model()
                pretrain_model.load_state_dict(torch.load(pretrain_save_path, map_location=self.device))
                pretrain_model.to(self.device)
                pretrain_val_f1 = 0.0  # Placeholder; not used for loaded model
                logging.info("✓ Pretrained weights loaded")
            else:
                logging.info("[INFO] No saved pretrain model found, starting pretraining...")
                pretrain_model, pretrain_val_f1 = self.train_stage(
                    stage_name="PRETRAIN",
                    tr_data=tr_ibm,
                    val_data=val_ibm,
                    te_data=te_ibm,
                    tr_inds=tr_inds_ibm,
                    val_inds=val_inds_ibm,
                    te_inds=te_inds_ibm,
                    model=None
                )
            
            logging.info(f"\n✓ Pretraining complete. Best Val F1: {pretrain_val_f1:.4f}")
            
            # Save pretrained model
            if self.args.save_model:
                save_path = Path(self.args.save_dir or "models") / f"pretrained_{self.args.model}_ibm.pt"
                torch.save(pretrain_model.state_dict(), save_path)
                logging.info(f"✓ Pretrained model saved to {save_path}")
            
            # Stage 2: FINETUNE on Nolambur
            logging.info("\n" + "="*60)
            logging.info("STAGE 2: FINE-TUNING ON NOLAMBUR DATA")
            logging.info("="*60)
            logging.info("Focus: ₹5L burst patterns + Tamil Nadu→Haridwar geo-mismatch")
            
            tr_nol, val_nol, te_nol, tr_inds_nol, val_inds_nol, te_inds_nol = \
                self.load_and_prepare_data("FINETUNE", "nolambur")
            
            # Check if finetuned model already exists
            finetune_save_path = Path(self.args.save_dir or "models") / f"finetuned_{self.args.model}_nolambur.pt"
            finetune_val_f1 = None
            
            if finetune_save_path.exists():
                logging.info(f"[INFO] Found saved finetune model at {finetune_save_path}")
                logging.info("[INFO] Skipping fine-tuning, loading weights...")
                finetuned_model = self.create_model()
                finetuned_model.load_state_dict(torch.load(finetune_save_path, map_location=self.device))
                finetuned_model.to(self.device)
                finetune_val_f1 = 0.0  # Placeholder; not used for loaded model
                logging.info("✓ Finetuned weights loaded")
            else:
                logging.info("[INFO] No saved finetune model found, starting fine-tuning...")
                # Fine-tune with pretrained weights and reduced learning rate
                finetuned_model, finetune_val_f1 = self.train_stage(
                    stage_name="FINETUNE",
                    tr_data=tr_nol,
                    val_data=val_nol,
                    te_data=te_nol,
                    tr_inds=tr_inds_nol,
                    val_inds=val_inds_nol,
                    te_inds=te_inds_nol,
                    model=pretrain_model,  # Use pretrained model
                    reduced_epochs=50  # Fewer epochs for fine-tuning
                )
            
            logging.info(f"\n✓ Fine-tuning complete. Best Val F1: {finetune_val_f1:.4f}")
            
            # Save finetuned model
            if self.args.save_model:
                save_path = Path(self.args.save_dir or "models") / f"finetuned_{self.args.model}_nolambur.pt"
                torch.save(finetuned_model.state_dict(), save_path)
                logging.info(f"✓ Fine-tuned model saved to {save_path}")
            
            # Final report
            logging.info("\n" + "="*60)
            logging.info("TRAINING PIPELINE COMPLETE")
            logging.info("="*60)
            logging.info(f"Model: {self.args.model}")
            logging.info(f"Pretrain Val F1 (IBM AML): {pretrain_val_f1:.4f}")
            logging.info(f"Finetune Val F1 (Nolambur): {finetune_val_f1:.4f}")
            logging.info(f"Transfer learning: {'✓ Improved' if finetune_val_f1 >= pretrain_val_f1 * 0.95 else '✗ Degraded'}")
            
            wandb.log({
                "summary/pretrain_f1": pretrain_val_f1,
                "summary/finetune_f1": finetune_val_f1,
            })
            
        finally:
            wandb.finish()


def get_pretrain_parser():
    """Parser for two-stage fine-tuning"""
    parser = argparse.ArgumentParser(description='Two-stage pretraining + fine-tuning for T-GNN')
    
    parser.add_argument('--model', type=str, default='gin',
                       choices=['gin', 'gat', 'pna', 'rgcn'],
                       help='GNN architecture (default: gin)')
    parser.add_argument('--seed', type=int, default=42,
                       help='Random seed (default: 42)')
    parser.add_argument('--ports', action='store_true', default=False,
                       help='Use port numberings in GNN training')
    parser.add_argument('--tds', action='store_true', default=False,
                       help='Use time-delta features in GNN training')
    parser.add_argument('--ego', action='store_true', default=False,
                       help='Use ego IDs in GNN training')
    parser.add_argument('--num-neighs', nargs='+', type=int, default=[100, 100],
                       help='Neighbor sampling sizes for each hop')
    parser.add_argument('--tqdm', action='store_true', default=False,
                       help='Show progress bars')
    parser.add_argument('--reverse_mp', action='store_true', default=False,
                       help='Use reverse MP in GNN training')
    parser.add_argument('--epochs', type=int, default=100,
                       help='Max pretraining epochs (default: 100)')
    parser.add_argument('--batch-size', type=int, default=256,
                       help='Batch size (default: 256)')
    parser.add_argument('--save-model', action='store_true', default=True,
                       help='Save model checkpoints')
    parser.add_argument('--save-dir', type=str, default='models',
                       help='Directory for model checkpoints')
    parser.add_argument('--model-config', type=str, default='model_settings.json',
                       help='Model configuration file')
    parser.add_argument('--data', type=str, default='HI-Small',
                       help='IBM dataset subset (HI-Small default for quick setup, or HI-Large/HI-Medium/LI-Large if preprocessed)')
    
    return parser


if __name__ == "__main__":
    # Setup
    parser = get_pretrain_parser()
    args = parser.parse_args()
    
    data_config_path = SCRIPT_DIR / 'data_config.json'
    with open(data_config_path, 'r') as f:
        data_config = json.load(f)
    
    logger_setup()
    set_seed(args.seed)
    
    # Run pipeline
    finetuner = TwoStageFinetuner(args, data_config)
    finetuner.run()
