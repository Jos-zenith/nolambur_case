#!/usr/bin/env python3
"""
Verification script for two-stage fine-tuning setup.
Checks data availability, dependencies, and configuration before training.
"""

import sys
import json
import logging
import ast
from pathlib import Path
import importlib.util

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def check_python_version():
    """Verify Python 3.8+"""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        logging.info(f"✓ Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        logging.error(f"✗ Python 3.8+ required (found {version.major}.{version.minor})")
        return False

def check_dependencies():
    """Verify required packages"""
    required = {
        'torch': 'PyTorch',
        'torch_geometric': 'PyTorch Geometric',
        'pandas': 'Pandas',
        'numpy': 'NumPy',
        'sklearn': 'Scikit-learn',
        'wandb': 'Weights & Biases',
        'tqdm': 'TQDM',
    }
    
    all_ok = True
    for module_name, display_name in required.items():
        spec = importlib.util.find_spec(module_name)
        if spec is not None:
            try:
                mod = importlib.import_module(module_name)
                version = getattr(mod, '__version__', 'unknown')
                logging.info(f"✓ {display_name}: {version}")
            except ImportError as e:
                logging.error(f"✗ {display_name}: Failed to import ({e})")
                all_ok = False
        else:
            logging.error(f"✗ {display_name}: Not installed")
            all_ok = False
    
    return all_ok

def check_configuration_files():
    """Verify configuration files exist"""
    required_configs = {
        'model_settings.json': 'Model configurations',
        'data_config.json': 'Data paths configuration',
    }
    
    all_ok = True
    for config_file, description in required_configs.items():
        config_path = Path(config_file)
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    json.load(f)
                logging.info(f"✓ {description}: {config_file}")
            except json.JSONDecodeError as e:
                logging.error(f"✗ {description}: Invalid JSON ({e})")
                all_ok = False
        else:
            logging.error(f"✗ {description}: {config_file} not found")
            all_ok = False
    
    return all_ok

def check_data_availability():
    """Verify IBM AML and Nolambur data exists"""
    
    logging.info("\nChecking data availability:")

    # IBM AML datasets (resolve from data_config.json)
    ibm_variants = ['HI-Large', 'HI-Medium', 'HI-Small', 'LI-Large', 'LI-Medium', 'LI-Small']
    try:
        with open('data_config.json', 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        ibm_base = Path(cfg['paths']['aml_data'])
    except (OSError, json.JSONDecodeError, KeyError) as e:
        logging.error(f"✗ Could not resolve IBM AML path from data_config.json ({e})")
        return False

    if not ibm_base.exists():
        logging.error(f"✗ Configured IBM AML path does not exist: {ibm_base}")
        return False
    logging.info(f"✓ IBM AML base path from config: {ibm_base}")
    
    ibm_available = False
    for variant in ibm_variants:
        # Support both folder layout (<variant>/formatted_transactions.csv)
        # and flat-file layout (<variant>_Trans.csv).
        variant_path = ibm_base / variant
        flat_trans_file = ibm_base / f"{variant}_Trans.csv"
        if (variant_path / 'formatted_transactions.csv').exists():
            logging.info(f"✓ IBM AML {variant}: formatted_transactions.csv")
            ibm_available = True
        elif variant_path.exists():
            files = list(variant_path.glob('*.csv'))
            if len(files) > 0:
                logging.info(f"✓ IBM AML {variant}: {len(files)} CSV files")
                ibm_available = True
            else:
                logging.warning(f"~ IBM AML {variant}: Directory exists but no CSV files")
        elif flat_trans_file.exists():
            logging.info(f"✓ IBM AML {variant}: flat transaction file {flat_trans_file.name}")
            ibm_available = True
        else:
            logging.warning(f"~ IBM AML {variant}: Not found")
    
    if not ibm_available:
        logging.error("✗ No IBM AML datasets found")
        logging.error(f"  Expected: {ibm_base}")
    
    # Nolambur dataset
    nolambur_files = {
        'nolambur_transactions.csv': 'Transaction data',
        'nolambur_stats.json': 'Statistics',
    }
    
    nolambur_available = True
    for filename, description in nolambur_files.items():
        nol_path = Path(filename)
        if nol_path.exists():
            logging.info(f"✓ Nolambur {description}: {filename}")
        else:
            logging.warning(f"~ Nolambur {description}: {filename} not found")
            nolambur_available = False

    # Account/label file may be named differently across repos.
    if Path('nolambur_accounts.csv').exists():
        logging.info("✓ Nolambur Account data: nolambur_accounts.csv")
    elif Path('nolambur_labels.csv').exists():
        logging.info("✓ Nolambur Account data: nolambur_labels.csv")
    else:
        logging.warning("~ Nolambur Account data: neither nolambur_accounts.csv nor nolambur_labels.csv found")
        nolambur_available = False
    
    return ibm_available and nolambur_available

def check_python_scripts():
    """Verify training scripts exist"""
    
    logging.info("\nChecking training scripts:")
    
    scripts = {
        'pretrain_finetune.py': 'Main trainer',
        'dataset_loaders.py': 'Dataset loaders',
        'run_pretrain_finetune.py': 'Quick launcher',
        'evaluate_finetuning.py': 'Evaluation script',
    }
    
    all_ok = True
    for script, description in scripts.items():
        script_path = Path(script)
        if script_path.exists():
            # Validate by parsing Python source (works without shebang and avoids locale decode issues).
            try:
                source = script_path.read_text(encoding='utf-8', errors='replace')
                ast.parse(source, filename=str(script_path))
                logging.info(f"✓ {description}: {script}")
            except SyntaxError as e:
                logging.error(f"✗ {description}: Syntax error in {script} ({e.msg} at line {e.lineno})")
                all_ok = False
            except OSError as e:
                logging.error(f"✗ {description}: Could not read {script} ({e})")
                all_ok = False
        else:
            logging.error(f"✗ {description}: {script} not found")
            all_ok = False
    
    return all_ok

def check_existing_models():
    """Check for existing pretrained models"""
    
    logging.info("\nChecking for existing models:")
    
    models_dir = Path('models')
    if models_dir.exists():
        models = list(models_dir.glob('*.pt'))
        if len(models) > 0:
            for model_path in models:
                size_mb = model_path.stat().st_size / (1024 * 1024)
                logging.info(f"~ Found existing model: {model_path.name} ({size_mb:.1f} MB)")
        else:
            logging.info("~ No existing models (will be generated)")
    else:
        logging.info("~ Models directory doesn't exist (will be created)")

def print_recommendations(checks):
    """Print recommendations based on checks"""
    
    logging.info("\n" + "="*60)
    logging.info("SETUP VERIFICATION SUMMARY")
    logging.info("="*60)
    
    all_passed = all(checks.values())
    
    if all_passed:
        logging.info("\n✓ ALL CHECKS PASSED")
        logging.info("\nYou can now run:")
        logging.info("  python run_pretrain_finetune.py")
        logging.info("\nFor quick test:")
        logging.info("  python run_pretrain_finetune.py --quick")
    else:
        logging.info("\n⚠ SOME CHECKS FAILED OR WARNINGS")
        
        if not checks.get('dependencies', False):
            logging.info("\nTo install dependencies:")
            logging.info("  pip install torch torch-geometric pandas scikit-learn wandb tqdm")
        
        if not checks.get('data', False):
            logging.info("\nTo set up data:")
            logging.info("  1. Verify IBM AML path in data_config.json")
            logging.info("  2. Verify Nolambur CSV files location")
            logging.info("  3. Check data_config.json for correct paths")
        
        if not checks.get('config', False):
            logging.info("\nTo fix configuration:")
            logging.info("  1. Verify model_settings.json exists and is valid JSON")
            logging.info("  2. Verify data_config.json exists and contains paths")

def main():
    setup_logging()
    
    logging.info("\n" + "="*60)
    logging.info("TWO-STAGE FINE-TUNING SETUP VERIFICATION")
    logging.info("="*60)
    
    # Run all checks
    checks = {
        'python': check_python_version(),
        'dependencies': check_dependencies(),
        'config': check_configuration_files(),
        'data': check_data_availability(),
        'scripts': check_python_scripts(),
    }
    
    check_existing_models()
    print_recommendations(checks)
    
    # Exit code
    if all(checks.values()):
        logging.info("\n✓ Setup is ready to go!")
        return 0
    else:
        logging.warning("\n⚠ Some issues found - please review above")
        return 1

if __name__ == '__main__':
    sys.exit(main())
