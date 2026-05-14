import numpy as np
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

header = "EdgeID,from_id,to_id,Timestamp,\
Amount Sent,Sent Currency,Amount Received,Received Currency,\
Payment Format,Is Laundering\n"

firstTs = -1

with open(outPath, 'w') as writer:
    writer.write(header)
    for i in range(len(raw)):
        datetime_object = datetime.strptime(str(raw.at[i,"Timestamp"]), '%Y/%m/%d %H:%M')
        ts = datetime_object.timestamp()
        day = datetime_object.day
        month = datetime_object.month
        year = datetime_object.year
        hour = datetime_object.hour
        minute = datetime_object.minute

        if firstTs == -1:
            startTime = datetime(year, month, day)
            firstTs = startTime.timestamp() - 10

        ts = ts - firstTs

        cur1 = get_dict_val(str(raw.at[i,"Receiving Currency"]), currency)
        cur2 = get_dict_val(str(raw.at[i,"Payment Currency"]), currency)

        fmt = get_dict_val(str(raw.at[i,"Payment Format"]), paymentFormat)

        fromAccIdStr = str(raw.at[i,"From Bank"]) + str(raw.iloc[i, 2])
        fromId = get_dict_val(fromAccIdStr, account)

        toAccIdStr = str(raw.at[i,"To Bank"]) + str(raw.iloc[i, 4])
        toId = get_dict_val(toAccIdStr, account)

        amountReceivedOrig = float(str(raw.at[i,"Amount Received"]))
        amountPaidOrig = float(str(raw.at[i,"Amount Paid"]))

        isl = int(str(raw.at[i,"Is Laundering"]))

        line = '%d,%d,%d,%d,%f,%d,%f,%d,%d,%d\n' % \
                    (i,fromId,toId,ts,amountPaidOrig,cur2, amountReceivedOrig,cur1,fmt,isl)

        writer.write(line)

formatted = pd.read_csv(outPath)
formatted = formatted.sort_values(by=formatted.columns[3], ignore_index=True)

formatted.to_csv(outPath, index=False)