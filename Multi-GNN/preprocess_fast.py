import pandas as pd
import sys
import os

"""
Fast preprocessing of Kaggle AML transaction data.
Converts raw transaction CSV to formatted_transactions.csv
"""

if len(sys.argv) < 2:
    print("Usage: python preprocess_fast.py <input_csv_path> <output_dir>")
    sys.exit(1)

input_file = sys.argv[1]
output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(input_file)

print(f"Reading {input_file}...")
df = pd.read_csv(input_file)

print(f"Processing {len(df)} transactions...")

# Create formatted transactions DataFrame
# Expected columns: EdgeID, from_id, to_id, Timestamp, Amount Sent, Sent Currency, 
#                   Amount Received, Received Currency, Payment Format, Is Laundering

try:
    # Map unique account IDs
    from_accounts = df['From Bank'].astype(str) + '_' + df.iloc[:, 2].astype(str)
    to_accounts = df['To Bank'].astype(str) + '_' + df.iloc[:, 4].astype(str)
    
    all_accounts = pd.concat([from_accounts, to_accounts]).unique()
    account_map = {acc: idx for idx, acc in enumerate(all_accounts)}
    
    # Map currencies and formats
    currencies = pd.concat([df['Receiving Currency'], df['Payment Currency']]).unique()
    currency_map = {curr: idx for idx, curr in enumerate(currencies)}
    
    payment_formats = df['Payment Format'].unique()
    format_map = {fmt: idx for idx, fmt in enumerate(payment_formats)}
    
    # Create formatted dataframe
    formatted_df = pd.DataFrame({
        'EdgeID': range(len(df)),
        'from_id': [account_map[acc] for acc in from_accounts],
        'to_id': [account_map[acc] for acc in to_accounts],
        'Timestamp': pd.to_datetime(df['Timestamp'], format='%Y/%m/%d %H:%M').astype('int64') // 10**9,
        'Amount Sent': df['Amount Paid'].astype(float),
        'Sent Currency': [currency_map[c] for c in df['Payment Currency']],
        'Amount Received': df['Amount Received'].astype(float),
        'Received Currency': [currency_map[c] for c in df['Receiving Currency']],
        'Payment Format': [format_map[f] for f in df['Payment Format']],
        'Is Laundering': df['Is Laundering'].astype(int)
    })
    
    # Normalize timestamps to start from 0
    min_ts = formatted_df['Timestamp'].min()
    formatted_df['Timestamp'] = formatted_df['Timestamp'] - min_ts
    
    # Sort by timestamp
    formatted_df = formatted_df.sort_values('Timestamp').reset_index(drop=True)
    
    # Save output
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, 'formatted_transactions.csv')
    formatted_df.to_csv(output_file, index=False)
    
    print(f"✓ Preprocessing complete!")
    print(f"  - Output: {output_file}")
    print(f"  - Transactions: {len(formatted_df)}")
    print(f"  - Nodes: {len(all_accounts)}")
    print(f"  - Illicit ratio: {formatted_df['Is Laundering'].mean():.2%}")
    
except Exception as e:
    print(f"Error processing data: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
