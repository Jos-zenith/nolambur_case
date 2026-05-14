"""
Evaluation and comparison of two-stage fine-tuning approach.

Validates:
1. Pretrained model learns general fraud patterns (IBM AML)
2. Fine-tuned model specializes in Nolambur patterns
3. Transfer learning actually improves performance vs random init
"""

import torch
import logging
import json
import argparse
from pathlib import Path
from typing import Tuple, Dict
import pandas as pd

from models import GINe, GATe, PNA, RGCN
from train_util import get_loaders, evaluate_homo
from data_loading import get_data
import numpy as np
from sklearn.metrics import (
    f1_score, precision_score, recall_score, confusion_matrix,
    roc_auc_score, roc_curve, auc
)


def load_model_weights(model, checkpoint_path: str):
    """Load pretrained weights into model"""
    if not Path(checkpoint_path).exists():
        logging.warning(f"Checkpoint not found: {checkpoint_path}")
        return False
    
    checkpoint = torch.load(checkpoint_path, map_location='cpu')
    if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
        model.load_state_dict(checkpoint['model_state_dict'])
    else:
        model.load_state_dict(checkpoint)
    
    logging.info(f"✓ Loaded checkpoint: {checkpoint_path}")
    return True


def evaluate_model(model, loader, data, inds, device, name: str = "Model") -> Dict:
    """Comprehensive evaluation of model performance"""
    
    model.eval()
    all_preds = []
    all_probs = []
    all_labels = []
    
    with torch.no_grad():
        for batch in loader:
            inds_cpu = inds.detach().cpu()
            batch_edge_inds = inds_cpu[batch.input_id.detach().cpu()]
            batch_edge_ids = loader.data.edge_attr.detach().cpu()[batch_edge_inds, 0]
            mask = torch.isin(batch.edge_attr[:, 0].detach().cpu(), batch_edge_ids)
            
            batch.edge_attr = batch.edge_attr[:, 1:]
            batch.to(device)
            
            out = model(batch.x, batch.edge_index, batch.edge_attr)
            probs = torch.nn.functional.softmax(out[mask], dim=-1)
            preds = probs.argmax(dim=-1)
            labels = batch.y[mask]
            
            all_preds.append(preds.detach().cpu().numpy())
            all_probs.append(probs[:, 1].detach().cpu().numpy())  # Fraud probability
            all_labels.append(labels.detach().cpu().numpy())
    
    preds = np.concatenate(all_preds)
    probs = np.concatenate(all_probs)
    labels = np.concatenate(all_labels)
    
    # Calculate metrics
    metrics = {
        'f1': float(f1_score(labels, preds)),
        'precision': float(precision_score(labels, preds, zero_division=0)),
        'recall': float(recall_score(labels, preds, zero_division=0)),
        'accuracy': float((preds == labels).mean()),
        'roc_auc': float(roc_auc_score(labels, probs)) if len(np.unique(labels)) > 1 else 0,
    }
    
    # Confusion matrix
    tn, fp, fn, tp = confusion_matrix(labels, preds).ravel()
    metrics['confusion_matrix'] = {
        'true_negatives': int(tn),
        'false_positives': int(fp),
        'false_negatives': int(fn),
        'true_positives': int(tp),
    }
    
    # False positive/negative rates
    metrics['fpr'] = float(fp / (fp + tn)) if (fp + tn) > 0 else 0
    metrics['fnr'] = float(fn / (fn + tp)) if (fn + tp) > 0 else 0
    
    logging.info(f"\n{name} Performance:")
    logging.info(f"  F1-Score:     {metrics['f1']:.4f}")
    logging.info(f"  Precision:    {metrics['precision']:.4f}")
    logging.info(f"  Recall:       {metrics['recall']:.4f}")
    logging.info(f"  Accuracy:     {metrics['accuracy']:.4f}")
    logging.info(f"  ROC-AUC:      {metrics['roc_auc']:.4f}")
    logging.info(f"  FPR:          {metrics['fpr']:.4f}")
    logging.info(f"  FNR:          {metrics['fnr']:.4f}")
    
    return metrics


class ComparisonEvaluator:
    """Compare three approaches: Pretrained, Fine-tuned, and Random Init"""
    
    def __init__(self, args, data_config):
        self.args = args
        self.data_config = data_config
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        with open(args.model_config or 'model_settings.json', 'r') as f:
            self.model_configs = json.load(f)
    
    def initialize_model(self, num_features: int, num_edge_features: int):
        """Create fresh model instance"""
        config = self.model_configs[self.args.model.lower()]['params']
        
        if self.args.model.lower() == 'gin':
            model = GINe(
                num_features=num_features,
                num_gnn_layers=int(config['n_gnn_layers']),
                n_classes=2,
                n_hidden=int(config['n_hidden']),
                edge_dim=num_edge_features,
                dropout=config['dropout'],
                final_dropout=config['final_dropout']
            )
        elif self.args.model.lower() == 'gat':
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
        else:
            raise ValueError(f"Unsupported model: {self.args.model}")
        
        return model.to(self.device)
    
    def evaluate(self):
        """Run full evaluation comparing all three approaches"""
        
        logging.info("\n" + "="*60)
        logging.info("TWO-STAGE FINE-TUNING EVALUATION")
        logging.info("="*60)
        
        # Load Nolambur data for evaluation
        logging.info("\nLoading Nolambur test data...")
        self.args.data = 'nolambur'
        te_data, _, _, te_inds, _, _ = get_data(self.args, self.data_config)
        
        num_features = te_data.x.shape[1]
        num_edge_features = te_data.edge_attr.shape[1]
        batch_size = self.args.batch_size or 256
        te_loader = get_loaders(te_data, batch_size, 1)[0]
        
        results = {}
        
        # Approach 1: Pretrained only (no fine-tuning)
        if self.args.pretrained_path and Path(self.args.pretrained_path).exists():
            logging.info("\n" + "-"*60)
            logging.info("Approach 1: PRETRAINED ONLY (no fine-tuning)")
            logging.info("-"*60)
            
            model = self.initialize_model(num_features, num_edge_features)
            load_model_weights(model, self.args.pretrained_path)
            
            metrics = evaluate_model(
                model, te_loader, te_data, te_inds, self.device,
                name="Pretrained-Only Model"
            )
            results['pretrained_only'] = metrics
        
        # Approach 2: Fine-tuned (pretrain + finetune)
        if self.args.finetuned_path and Path(self.args.finetuned_path).exists():
            logging.info("\n" + "-"*60)
            logging.info("Approach 2: FINE-TUNED (pretrain + finetune)")
            logging.info("-"*60)
            
            model = self.initialize_model(num_features, num_edge_features)
            load_model_weights(model, self.args.finetuned_path)
            
            metrics = evaluate_model(
                model, te_loader, te_data, te_inds, self.device,
                name="Fine-Tuned Model"
            )
            results['fine_tuned'] = metrics
        
        # Approach 3: Random init (no pretraining)
        if self.args.compare_random:
            logging.info("\n" + "-"*60)
            logging.info("Approach 3: RANDOM INIT (baseline)")
            logging.info("-"*60)
            
            model = self.initialize_model(num_features, num_edge_features)
            # Don't load any weights - use random initialization
            
            metrics = evaluate_model(
                model, te_loader, te_data, te_inds, self.device,
                name="Random Init Model"
            )
            results['random_init'] = metrics
        
        # Summary and transfer learning validation
        self._print_comparison(results)
        
        return results
    
    def _print_comparison(self, results: Dict):
        """Print comparison and validate transfer learning"""
        
        logging.info("\n" + "="*60)
        logging.info("COMPARISON SUMMARY")
        logging.info("="*60)
        
        # Create comparison table
        metrics_to_compare = ['f1', 'precision', 'recall', 'roc_auc']
        
        comparison_data = []
        for approach, metrics in results.items():
            row = {'Approach': approach.replace('_', ' ').upper()}
            for metric in metrics_to_compare:
                if metric in metrics:
                    row[metric.upper()] = f"{metrics[metric]:.4f}"
            comparison_data.append(row)
        
        if comparison_data:
            df_comparison = pd.DataFrame(comparison_data)
            logging.info("\n" + df_comparison.to_string(index=False))
        
        # Transfer learning validation
        logging.info("\n" + "="*60)
        logging.info("TRANSFER LEARNING VALIDATION")
        logging.info("="*60)
        
        if 'fine_tuned' in results and 'random_init' in results:
            ft_f1 = results['fine_tuned']['f1']
            rand_f1 = results['random_init']['f1']
            improvement = ((ft_f1 - rand_f1) / rand_f1 * 100) if rand_f1 > 0 else 0
            
            logging.info(f"Fine-tuned F1:      {ft_f1:.4f}")
            logging.info(f"Random init F1:     {rand_f1:.4f}")
            logging.info(f"Improvement:        {improvement:+.1f}%")
            
            if ft_f1 > rand_f1 * 1.1:
                logging.info("✓ Transfer learning is WORKING (>10% improvement)")
            elif ft_f1 > rand_f1:
                logging.info("~ Transfer learning is MARGINAL (0-10% improvement)")
            else:
                logging.warning("✗ Transfer learning NOT helping (degradation)")
        
        if 'fine_tuned' in results and 'pretrained_only' in results:
            ft_f1 = results['fine_tuned']['f1']
            pt_f1 = results['pretrained_only']['f1']
            improvement = ((ft_f1 - pt_f1) / pt_f1 * 100) if pt_f1 > 0 else 0
            
            logging.info(f"\nFine-tuned F1:      {ft_f1:.4f}")
            logging.info(f"Pretrained F1:      {pt_f1:.4f}")
            logging.info(f"Fine-tuning gain:   {improvement:+.1f}%")
            
            if ft_f1 > pt_f1 * 1.05:
                logging.info("✓ Fine-tuning improved performance (>5% gain)")
            elif ft_f1 > pt_f1 * 0.95:
                logging.info("~ Fine-tuning maintained performance (within 5%)")
            else:
                logging.warning("✗ Fine-tuning degraded performance")
        
        # Save results
        if self.args.save_results:
            results_path = Path(self.args.output_dir or 'results') / 'comparison.json'
            results_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(results_path, 'w') as f:
                json.dump(results, f, indent=2)
            
            logging.info(f"\n✓ Results saved to: {results_path}")


def get_eval_parser():
    """Parser for evaluation script"""
    parser = argparse.ArgumentParser(description='Evaluate two-stage fine-tuning')
    
    parser.add_argument('--model', type=str, default='gin',
                       choices=['gin', 'gat', 'pna', 'rgcn'],
                       help='GNN architecture')
    
    parser.add_argument('--pretrained-path', type=str,
                       help='Path to pretrained model checkpoint')
    parser.add_argument('--finetuned-path', type=str,
                       help='Path to fine-tuned model checkpoint')
    
    parser.add_argument('--compare-random', action='store_true', default=False,
                       help='Also evaluate random init baseline')
    
    parser.add_argument('--batch-size', type=int, default=256,
                       help='Batch size for evaluation')
    
    parser.add_argument('--model-config', type=str, default='model_settings.json',
                       help='Model configuration file')
    
    parser.add_argument('--save-results', action='store_true', default=True,
                       help='Save results to JSON')
    parser.add_argument('--output-dir', type=str, default='results',
                       help='Output directory for results')
    
    return parser


if __name__ == '__main__':
    parser = get_eval_parser()
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    with open(args.model_config or 'model_settings.json', 'r') as f:
        data_config = json.load(f)
    
    evaluator = ComparisonEvaluator(args, data_config)
    results = evaluator.evaluate()
