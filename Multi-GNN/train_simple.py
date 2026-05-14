"""
Simplified T-GNN Training Script for Fraud Detection
This version works with standard PyTorch and PyG without requiring neighbor sampling libraries.
"""

import torch
import torch.nn.functional as F
from torch_geometric.nn import GINConv, GATConv, GraphConv
from torch.optim import Adam
import pandas as pd
import numpy as np
from datetime import datetime
import logging
import json
import argparse

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

class SimpleGIN(torch.nn.Module):
    """Simple Graph Isomorphism Network"""
    def __init__(self, in_channels, hidden_channels, out_channels, num_layers=2):
        super().__init__()
        self.convs = torch.nn.ModuleList()
        self.bns = torch.nn.ModuleList()
        
        for i in range(num_layers):
            in_ch = in_channels if i == 0 else hidden_channels
            self.convs.append(GraphConv(in_ch, hidden_channels))
            self.bns.append(torch.nn.BatchNorm1d(hidden_channels))
        
        self.mlp = torch.nn.Sequential(
            torch.nn.Linear(hidden_channels, hidden_channels),
            torch.nn.ReLU(),
            torch.nn.Linear(hidden_channels, out_channels)
        )
        
    def forward(self, x, edge_index):
        for conv, bn in zip(self.convs, self.bns):
            x = conv(x, edge_index)
            x = bn(x)
            x = F.relu(x)
        x = self.mlp(x)
        return x

class EdgeClassifier(torch.nn.Module):
    """Edge-level classifier for fraud detection"""
    def __init__(self, node_dim, hidden_dim=64):
        super().__init__()
        self.node_encoder = torch.nn.Sequential(
            torch.nn.Linear(node_dim, hidden_dim),
            torch.nn.ReLU(),
            torch.nn.Linear(hidden_dim, hidden_dim)
        )
        
        # Concatenate node embeddings from source and target
        self.edge_classifier = torch.nn.Sequential(
            torch.nn.Linear(hidden_dim * 2, hidden_dim),
            torch.nn.ReLU(),
            torch.nn.Linear(hidden_dim, 2)
        )
        
    def forward(self, node_embeddings, edge_index, edge_features=None):
        src, dst = edge_index
        src_emb = node_embeddings[src]
        dst_emb = node_embeddings[dst]
        
        # Concatenate source and destination embeddings
        edge_emb = torch.cat([src_emb, dst_emb], dim=1)
        logits = self.edge_classifier(edge_emb)
        return logits

def train_simple_gnn():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="HI-Small", type=str, help="Dataset name")
    parser.add_argument("--n_epochs", default=5, type=int, help="Number of epochs")
    parser.add_argument("--batch_size", default=512, type=int, help="Batch size")
    parser.add_argument("--lr", default=0.001, type=float, help="Learning rate")
    parser.add_argument("--hidden_dim", default=64, type=int, help="Hidden dimension")
    args = parser.parse_args()
    
    # Load config
    with open('data_config.json') as f:
        data_config = json.load(f)
    
    # Load data
    data_path = f"{data_config['paths']['aml_data']}/{args.data}/formatted_transactions.csv"
    logging.info(f"Loading data from {data_path}")
    df = pd.read_csv(data_path)
    
    # Prepare tensors
    edge_index = torch.LongTensor(df[['from_id', 'to_id']].values.T)
    edge_attr = torch.FloatTensor(df[['Timestamp', 'Amount Received', 'Received Currency', 'Payment Format']].values)
    y = torch.LongTensor(df['Is Laundering'].values)
    
    num_nodes = max(edge_index.max().item() + 1, df['from_id'].max() + 1, df['to_id'].max() + 1)
    node_feat = torch.ones((num_nodes, 1))
    
    # Normalize timestamp
    edge_attr[:, 0] = (edge_attr[:, 0] - edge_attr[:, 0].min()) / (edge_attr[:, 0].max() - edge_attr[:, 0].min() + 1e-8)
    
    logging.info(f"Dataset: {len(df)} edges, {num_nodes} nodes")
    logging.info(f"Illicit ratio: {y.float().mean():.2%}")
    
    # Data split
    n_train = int(0.6 * len(df))
    n_val = int(0.2 * len(df))
    
    train_idx = torch.arange(n_train)
    val_idx = torch.arange(n_train, n_train + n_val)
    test_idx = torch.arange(n_train + n_val, len(df))
    
    # Initialize model
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    logging.info(f"Using device: {device}")
    
    model = torch.nn.Sequential(
        torch.nn.Linear(1 + edge_attr.shape[1], 128),
        torch.nn.ReLU(),
        torch.nn.Linear(128, 64),
        torch.nn.ReLU(),
        torch.nn.Linear(64, 2)
    ).to(device)
    
    optimizer = Adam(model.parameters(), lr=args.lr)
    criterion = torch.nn.CrossEntropyLoss(weight=torch.tensor([1.0, 10.0]).to(device))  # Weight for class imbalance
    
    # Training loop
    logging.info(f"Starting training for {args.n_epochs} epochs...")
    
    for epoch in range(args.n_epochs):
        model.train()
        total_loss = 0
        total_acc = 0
        num_batches = 0
        
        # Train batches
        for i in range(0, len(train_idx), args.batch_size):
            batch_idx = train_idx[i:i+args.batch_size]
            
            # Prepare batch
            batch_src = edge_index[0, batch_idx]
            batch_dst = edge_index[1, batch_idx]
            batch_attr = edge_attr[batch_idx]
            batch_y = y[batch_idx]
            
            # Combine node features with edge attributes
            batch_feat = torch.cat([
                node_feat[batch_src],
                batch_attr
            ], dim=1).to(device)
            
            batch_y = batch_y.to(device)
            
            # Forward pass
            logits = model(batch_feat)
            loss = criterion(logits, batch_y)
            
            # Backward pass
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            
            # Metrics
            preds = logits.argmax(dim=1)
            acc = (preds == batch_y).float().mean()
            
            total_loss += loss.item()
            total_acc += acc.item()
            num_batches += 1
        
        avg_loss = total_loss / num_batches
        avg_acc = total_acc / num_batches
        
        # Validation
        model.eval()
        with torch.no_grad():
            val_loss = 0
            val_acc = 0
            val_batches = 0
            
            for i in range(0, len(val_idx), args.batch_size):
                batch_idx = val_idx[i:i+args.batch_size]
                
                batch_src = edge_index[0, batch_idx]
                batch_dst = edge_index[1, batch_idx]
                batch_attr = edge_attr[batch_idx]
                batch_y = y[batch_idx]
                
                batch_feat = torch.cat([
                    node_feat[batch_src],
                    batch_attr
                ], dim=1).to(device)
                
                batch_y = batch_y.to(device)
                
                logits = model(batch_feat)
                loss = criterion(logits, batch_y)
                preds = logits.argmax(dim=1)
                acc = (preds == batch_y).float().mean()
                
                val_loss += loss.item()
                val_acc += acc.item()
                val_batches += 1
            
            avg_val_loss = val_loss / val_batches
            avg_val_acc = val_acc / val_batches
        
        logging.info(f"Epoch {epoch+1}/{args.n_epochs} | "
                    f"Train Loss: {avg_loss:.4f}, Acc: {avg_acc:.4f} | "
                    f"Val Loss: {avg_val_loss:.4f}, Acc: {avg_val_acc:.4f}")
    
    # Test evaluation
    model.eval()
    with torch.no_grad():
        test_loss = 0
        test_acc = 0
        test_batches = 0
        
        for i in range(0, len(test_idx), args.batch_size):
            batch_idx = test_idx[i:i+args.batch_size]
            
            batch_src = edge_index[0, batch_idx]
            batch_dst = edge_index[1, batch_idx]
            batch_attr = edge_attr[batch_idx]
            batch_y = y[batch_idx]
            
            batch_feat = torch.cat([
                node_feat[batch_src],
                batch_attr
            ], dim=1).to(device)
            
            batch_y = batch_y.to(device)
            
            logits = model(batch_feat)
            loss = criterion(logits, batch_y)
            preds = logits.argmax(dim=1)
            acc = (preds == batch_y).float().mean()
            
            test_loss += loss.item()
            test_acc += acc.item()
            test_batches += 1
        
        avg_test_loss = test_loss / test_batches
        avg_test_acc = test_acc / test_batches
    
    logging.info(f"\nTest Results:")
    logging.info(f"Test Loss: {avg_test_loss:.4f}, Test Accuracy: {avg_test_acc:.4f}")
    
    # Save model
    model_path = data_config['paths']['model_to_save']
    torch.save(model.state_dict(), model_path)
    logging.info(f"Model saved to {model_path}")

if __name__ == "__main__":
    train_simple_gnn()
