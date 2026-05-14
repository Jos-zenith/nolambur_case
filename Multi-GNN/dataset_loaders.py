"""
Dataset loaders for two-stage training:
- IBM AML: General mule topology patterns
- Nolambur: Specific ₹5L burst + geographic mismatch patterns
"""

import pandas as pd
import numpy as np
import torch
import logging
import json
from pathlib import Path
from typing import Tuple, Optional, Dict, Any


def load_nolambur_data(data_path: str = "Multi-GNN/", 
                       normalize: bool = True) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    """
    Load Nolambur dataset specialized for ₹5L burst + Tamil Nadu→Haridwar pattern detection.
    
    Returns:
        - accounts_df: Account metadata including state information
        - transactions_df: Transaction data with temporal and geographic features
        - stats: Dataset statistics
    """
    
    logging.info("\n" + "="*60)
    logging.info("LOADING NOLAMBUR DATASET")
    logging.info("="*60)
    
    # Load accounts
    accounts_path = Path(data_path) / "nolambur_accounts.csv"
    if not accounts_path.exists():
        raise FileNotFoundError(f"Nolambur accounts not found: {accounts_path}")
    
    accounts_df = pd.read_csv(accounts_path)
    logging.info(f"✓ Loaded {len(accounts_df)} accounts")
    
    # Load transactions
    trans_path = Path(data_path) / "nolambur_transactions.csv"
    if not trans_path.exists():
        raise FileNotFoundError(f"Nolambur transactions not found: {trans_path}")
    
    transactions_df = pd.read_csv(trans_path)
    logging.info(f"✓ Loaded {len(transactions_df)} transactions")
    
    # Normalize amounts (₹5L = 500,000)
    if normalize and 'Amount' in transactions_df.columns:
        transactions_df['Amount_normalized'] = transactions_df['Amount'] / 500000  # Normalize by ₹5L
        transactions_df['Is_Burst'] = transactions_df['Amount'] >= 500000
        logging.info(f"✓ Identified {transactions_df['Is_Burst'].sum()} burst transactions (≥₹5L)")
    
    # Detect geographic mismatches (Tamil Nadu → other states)
    if 'Source_State' in transactions_df.columns and 'Destination_State' in transactions_df.columns:
        transactions_df['Has_Geo_Mismatch'] = (
            (transactions_df['Source_State'].str.contains('Tamil Nadu', case=False, na=False)) &
            (~transactions_df['Destination_State'].str.contains('Tamil Nadu', case=False, na=False))
        )
        logging.info(f"✓ Identified {transactions_df['Has_Geo_Mismatch'].sum()} "
                    f"geographic mismatches (TN → other states)")
    
    # Load stats
    stats_path = Path(data_path) / "nolambur_stats.json"
    if stats_path.exists():
        with open(stats_path, 'r') as f:
            stats = json.load(f)
    else:
        stats = {
            'total_accounts': len(accounts_df),
            'total_transactions': len(transactions_df),
            'fraud_transactions': transactions_df.get('Is_Laundering', transactions_df.get('Label', pd.Series([0]))).sum(),
        }
    
    logging.info(f"\nNolambur Dataset Summary:")
    logging.info(f"  Total accounts: {stats.get('total_accounts', len(accounts_df))}")
    logging.info(f"  Total transactions: {stats.get('total_transactions', len(transactions_df))}")
    logging.info(f"  Fraud transactions: {stats.get('fraud_transactions', 0)}")
    logging.info(f"  Illicit ratio: {stats.get('illicit_ratio_pct', 0):.2f}%")
    if 'mule_accounts' in stats:
        logging.info(f"  Mule accounts: {stats['mule_accounts']}")
    if 'victim_accounts' in stats:
        logging.info(f"  Victim accounts: {stats['victim_accounts']}")
    
    return accounts_df, transactions_df, stats


def analyze_ibm_topology(accounts_df: pd.DataFrame, 
                        transactions_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyze IBM AML dataset to extract mule topology patterns.
    
    Learns:
    - Node centrality patterns (mule accounts have high degree)
    - Transaction frequency patterns
    - Amount distribution patterns
    - Layering patterns (intermediate nodes in path)
    """
    
    analysis = {
        'node_degree_dist': None,
        'amount_distribution': None,
        'transaction_patterns': None,
        'layering_score': None,
    }
    
    if len(transactions_df) > 0:
        # Degree distribution (mules typically have high in/out degree)
        out_degree = transactions_df['from_id'].value_counts()
        in_degree = transactions_df['to_id'].value_counts()
        
        analysis['node_degree_dist'] = {
            'out_degree_median': float(out_degree.median()),
            'out_degree_max': float(out_degree.max()),
            'in_degree_median': float(in_degree.median()),
            'in_degree_max': float(in_degree.max()),
        }
        
        # Amount statistics
        if 'Amount Received' in transactions_df.columns:
            amount_col = 'Amount Received'
        elif 'Amount' in transactions_df.columns:
            amount_col = 'Amount'
        else:
            amount_col = None
        
        if amount_col:
            analysis['amount_distribution'] = {
                'median': float(transactions_df[amount_col].median()),
                'mean': float(transactions_df[amount_col].mean()),
                'std': float(transactions_df[amount_col].std()),
            }
    
    return analysis


def analyze_nolambur_signature(transactions_df: pd.DataFrame) -> Dict[str, Any]:
    """
    Analyze Nolambur dataset signature patterns.
    
    Learns:
    - ₹5L burst characteristics
    - Tamil Nadu → other state flows
    - Temporal concentration
    - Account velocity
    """
    
    signature = {
        'burst_statistics': {},
        'geographic_signature': {},
        'temporal_signature': {},
        'velocity_signature': {},
    }
    
    # Burst patterns (₹5L = 500,000)
    if 'Amount' in transactions_df.columns:
        burst_threshold = 500000
        burst_txns = transactions_df[transactions_df['Amount'] >= burst_threshold]
        
        signature['burst_statistics'] = {
            'burst_count': int(len(burst_txns)),
            'burst_ratio': float(len(burst_txns) / len(transactions_df)) if len(transactions_df) > 0 else 0,
            'median_burst_amount': float(burst_txns['Amount'].median()) if len(burst_txns) > 0 else 0,
            'mean_burst_amount': float(burst_txns['Amount'].mean()) if len(burst_txns) > 0 else 0,
        }
    
    # Geographic signature
    if 'Source_State' in transactions_df.columns and 'Destination_State' in transactions_df.columns:
        tn_txns = transactions_df[transactions_df['Source_State'].str.contains('Tamil Nadu', case=False, na=False)]
        tn_to_other = tn_txns[~tn_txns['Destination_State'].str.contains('Tamil Nadu', case=False, na=False)]
        
        signature['geographic_signature'] = {
            'tn_source_count': int(len(tn_txns)),
            'tn_to_other_count': int(len(tn_to_other)),
            'top_destinations': list(tn_to_other['Destination_State'].value_counts().head(5).index.tolist()),
        }
    
    # Temporal concentration
    if 'Timestamp' in transactions_df.columns:
        timestamps = pd.to_datetime(transactions_df['Timestamp'], errors='coerce')
        if len(timestamps.dropna()) > 0:
            time_span_days = (timestamps.max() - timestamps.min()).days
            signature['temporal_signature'] = {
                'time_span_days': int(time_span_days) if time_span_days > 0 else 1,
                'txns_per_day': float(len(transactions_df) / max(time_span_days, 1)),
            }
    
    # Account velocity
    if 'from_id' in transactions_df.columns:
        out_degree = transactions_df['from_id'].value_counts()
        signature['velocity_signature'] = {
            'max_account_out_degree': int(out_degree.max()),
            'median_account_out_degree': float(out_degree.median()),
            'high_velocity_accounts': int(len(out_degree[out_degree > out_degree.quantile(0.9)])),
        }
    
    return signature


def create_graph_features_for_stage(stage: str, 
                                    transactions_df: pd.DataFrame,
                                    accounts_df: Optional[pd.DataFrame] = None) -> Tuple[torch.Tensor, torch.Tensor]:
    """
    Create features optimized for each training stage.
    
    Pretraining (IBM): General topology features
    Fine-tuning (Nolambur): Burst + geographic features
    """
    
    if stage.lower() == 'pretrain':
        # IBM AML: Focus on general transaction features
        feature_cols = []
        if 'Amount Received' in transactions_df.columns:
            feature_cols.append('Amount Received')
        elif 'Amount' in transactions_df.columns:
            feature_cols.append('Amount')
        
        if 'Timestamp' in transactions_df.columns:
            feature_cols.append('Timestamp')
        
        # Normalize timestamp to [0, 1]
        if len(feature_cols) > 1 and 'Timestamp' in transactions_df.columns:
            df_copy = transactions_df.copy()
            max_time = df_copy['Timestamp'].max()
            if max_time > 0:
                df_copy['Timestamp'] = df_copy['Timestamp'] / max_time
            edge_attr = torch.tensor(df_copy[feature_cols].fillna(0).values, dtype=torch.float32)
        else:
            edge_attr = torch.tensor(transactions_df[feature_cols].fillna(0).values, dtype=torch.float32)
        
    else:  # finetune
        # Nolambur: Focus on burst + geographic features
        feature_cols = []
        
        if 'Amount' in transactions_df.columns:
            # Normalize amount by ₹5L threshold
            feature_cols.append('Amount_normalized')
            if 'Amount_normalized' not in transactions_df.columns:
                transactions_df = transactions_df.copy()
                transactions_df['Amount_normalized'] = transactions_df['Amount'] / 500000
        
        if 'Is_Burst' in transactions_df.columns:
            feature_cols.append('Is_Burst')
        
        if 'Has_Geo_Mismatch' in transactions_df.columns:
            feature_cols.append('Has_Geo_Mismatch')
        
        if 'Timestamp' in transactions_df.columns:
            feature_cols.append('Timestamp')
        
        # Normalize timestamp
        if len(feature_cols) > 0 and 'Timestamp' in transactions_df.columns:
            df_copy = transactions_df.copy()
            max_time = df_copy['Timestamp'].max()
            if max_time > 0:
                df_copy['Timestamp'] = df_copy['Timestamp'] / max_time
            edge_attr = torch.tensor(df_copy[feature_cols].fillna(0).values, dtype=torch.float32)
        else:
            edge_attr = torch.tensor(transactions_df[feature_cols].fillna(0).values, dtype=torch.float32)
    
    logging.info(f"✓ Created {stage.upper()} edge features: {edge_attr.shape}")
    logging.info(f"  Feature dimensions: {list(transactions_df[feature_cols].columns)}")
    
    # Node features (simple: all ones as placeholder)
    max_node_id = max(
        transactions_df['from_id'].max() if 'from_id' in transactions_df.columns else 0,
        transactions_df['to_id'].max() if 'to_id' in transactions_df.columns else 0,
    ) + 1
    
    node_attr = torch.ones((int(max_node_id), 1), dtype=torch.float32)
    
    return node_attr, edge_attr


if __name__ == "__main__":
    # Test data loading
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Load Nolambur
    accounts, transactions, stats = load_nolambur_data()
    print(f"\nNolambur Transactions shape: {transactions.shape}")
    print(f"Nolambur columns: {transactions.columns.tolist()}")
    
    # Analyze signatures
    nol_sig = analyze_nolambur_signature(transactions)
    print(f"\nNolambur Signature: {json.dumps(nol_sig, indent=2)}")
