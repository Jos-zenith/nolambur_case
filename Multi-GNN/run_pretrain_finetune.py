#!/usr/bin/env python3
"""
Quick-start launcher for two-stage fine-tuning.
Simplifies common training scenarios.
"""

import subprocess
import sys
import argparse
import logging
from pathlib import Path


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )


def run_command(cmd, description):
    """Run shell command with logging"""
    logging.info(f"\n{'='*60}")
    logging.info(f"▶ {description}")
    logging.info(f"{'='*60}")
    logging.info(f"Command: {' '.join(cmd)}\n")
    
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    
    if result.returncode != 0:
        logging.error(f"❌ Failed: {description}")
        return False
    
    logging.info(f"✓ Success: {description}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Quick-start two-stage fine-tuning for T-GNN',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:

1. Full pipeline (default):
   python run_pretrain_finetune.py

2. Quick test (fewer epochs):
   python run_pretrain_finetune.py --quick

3. Skip pretraining and load a saved checkpoint:
    python run_pretrain_finetune.py --skip-pretrain --pretrain-checkpoint models/pretrained_gin_ibm.pt

4. Use GAT architecture:
   python run_pretrain_finetune.py --model gat

5. Different IBM dataset:
   python run_pretrain_finetune.py --ibm-variant HI-Medium

6. No saving:
   python run_pretrain_finetune.py --no-save

7. Verbose output:
   python run_pretrain_finetune.py --verbose
        """
    )
    
    # Presets
    parser.add_argument(
        '--quick', action='store_true',
        help='Quick test run: 10 pretrain epochs, 10 finetune epochs'
    )
    parser.add_argument(
        '--full', action='store_true', default=True,
        help='Full training run: 100 pretrain + 50 finetune epochs (default)'
    )
    parser.add_argument(
        '--skip-pretrain', action='store_true',
        help='Skip pretraining and load a saved checkpoint instead'
    )
    parser.add_argument(
        '--pretrain-checkpoint', type=str, default='',
        help='Path to a saved pretraining checkpoint to load when skipping pretraining'
    )
    
    # Model settings
    parser.add_argument(
        '--model', type=str, choices=['gin', 'gat', 'pna', 'rgcn'],
        default='gin',
        help='GNN architecture (default: gin)'
    )
    parser.add_argument(
        '--ibm-variant', type=str,
        choices=['HI-Large', 'HI-Medium', 'HI-Small', 'LI-Large'],
        default='HI-Small',
        help='IBM dataset variant for pretraining (default: HI-Small)'
    )
    
    # Training settings
    parser.add_argument(
        '--batch-size', type=int, default=256,
        help='Batch size (default: 256)'
    )
    parser.add_argument(
        '--seed', type=int, default=42,
        help='Random seed (default: 42)'
    )
    
    # Output
    parser.add_argument(
        '--no-save', action='store_true',
        help='Do not save model checkpoints'
    )
    parser.add_argument(
        '--output-dir', type=str, default='models',
        help='Directory for model outputs (default: models/)'
    )
    
    # Verbosity
    parser.add_argument(
        '--verbose', action='store_true',
        help='Verbose output with progress bars'
    )
    
    args = parser.parse_args()
    setup_logging()
    
    # Build command
    cmd = ['python', 'pretrain_finetune.py']
    
    # Add arguments
    cmd.extend(['--model', args.model])
    cmd.extend(['--data', args.ibm_variant])
    cmd.extend(['--batch-size', str(args.batch_size)])
    cmd.extend(['--seed', str(args.seed)])
    
    if args.quick:
        cmd.extend(['--pretrain-epochs', '10', '--finetune-epochs', '10'])
    elif args.full:
        cmd.extend(['--pretrain-epochs', '100', '--finetune-epochs', '50'])

    if args.skip_pretrain:
        cmd.append('--skip-pretrain')
        if args.pretrain_checkpoint:
            cmd.extend(['--pretrain-checkpoint', args.pretrain_checkpoint])
    
    if not args.no_save:
        cmd.append('--save-model')
        cmd.extend(['--save-dir', args.output_dir])
    
    if args.verbose:
        cmd.append('--tqdm')
    
    # Display settings
    logging.info("\n" + "="*60)
    logging.info("TWO-STAGE FINE-TUNING: Quick Start")
    logging.info("="*60)
    
    mode = "QUICK" if args.quick else "FULL"
    logging.info(f"Mode:              {mode}")
    logging.info(f"Model:             {args.model.upper()}")
    logging.info(f"Pretrain dataset:  IBM AML ({args.ibm_variant})")
    logging.info(f"Finetune dataset:  Nolambur (₹5L burst + TN→HR geo-mismatch)")
    logging.info(f"Batch size:        {args.batch_size}")
    logging.info(f"Seed:              {args.seed}")
    logging.info(f"Save checkpoints:  {'Yes' if not args.no_save else 'No'}")
    logging.info(f"Output dir:        {args.output_dir}")
    logging.info(f"Skip pretrain:     {'Yes' if args.skip_pretrain else 'No'}")
    if args.pretrain_checkpoint:
        logging.info(f"Pretrain ckpt:     {args.pretrain_checkpoint}")
    
    # Run training
    success = run_command(cmd, "Two-stage fine-tuning pipeline")
    
    if success:
        logging.info("\n" + "="*60)
        logging.info("✓ TRAINING COMPLETE")
        logging.info("="*60)
        
        if not args.no_save:
            logging.info(f"\nModel checkpoints saved to: {args.output_dir}/")
            logging.info(f"  - pretrained_{args.model}_ibm.pt")
            logging.info(f"  - finetuned_{args.model}_nolambur.pt")
        
        logging.info("\nNext steps:")
        logging.info("  1. Check validation metrics in logs/")
        logging.info("  2. Evaluate on Nolambur test set:")
        logging.info("     python inference.py --model models/finetuned_*.pt")
        logging.info("  3. Compare with baseline (no pretraining)")
        
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()
