import pandas as pd
from datetime import datetime
import sys
import os

n = len(sys.argv)

if n == 1:
    print("No input path")
    sys.exit()

inPath = sys.argv[1]
outPath = os.path.dirname(inPath) + "/formatted_transactions.csv"

# Read the CSV file
raw = pd.read_csv(inPath)

currency = dict()
paymentFormat = dict()
bankAcc = dict()
account = dict()

def get_dict_val(name, collection):
    if name in collection:
        val = collection[name]
    else:
        val = len(collection)
        collection[name] = val
    return val

header = "EdgeID,from_id,to_id,Timestamp,Amount Sent,Sent Currency,Amount Received,Received Currency,Payment Format,Is Laundering\n"

firstTs = -1
rows = []

for i in range(len(raw)):
    try:
        datetime_object = datetime.strptime(raw.iloc[i]["Timestamp"], '%Y/%m/%d %H:%M')
        ts = datetime_object.timestamp()
        day = datetime_object.day
        month = datetime_object.month
        year = datetime_object.year

        if firstTs == -1:
            startTime = datetime(year, month, day)
            firstTs = startTime.timestamp() - 10

        ts = ts - firstTs

        cur1 = get_dict_val(raw.iloc[i]["Receiving Currency"], currency)
        cur2 = get_dict_val(raw.iloc[i]["Payment Currency"], currency)

        fmt = get_dict_val(raw.iloc[i]["Payment Format"], paymentFormat)

        fromAccIdStr = str(raw.iloc[i]["From Bank"]) + str(raw.iloc[i].iloc[2])
        fromId = get_dict_val(fromAccIdStr, account)

        toAccIdStr = str(raw.iloc[i]["To Bank"]) + str(raw.iloc[i].iloc[4])
        toId = get_dict_val(toAccIdStr, account)

        amountReceivedOrig = float(raw.iloc[i]["Amount Received"])
        amountPaidOrig = float(raw.iloc[i]["Amount Paid"])

        isl = int(raw.iloc[i]["Is Laundering"])

        rows.append({
            'EdgeID': i,
            'from_id': fromId,
            'to_id': toId,
            'Timestamp': ts,
            'Amount Sent': amountPaidOrig,
            'Sent Currency': cur2,
            'Amount Received': amountReceivedOrig,
            'Received Currency': cur1,
            'Payment Format': fmt,
            'Is Laundering': isl
        })
    except Exception as e:
        print(f"Error processing row {i}: {e}")
        continue

# Create DataFrame and sort by timestamp
formatted = pd.DataFrame(rows)
formatted = formatted.sort_values('Timestamp')

# Save to CSV
formatted.to_csv(outPath, index=False)
print(f"Preprocessing complete! Output saved to: {outPath}")
print(f"Processed {len(formatted)} transactions")
