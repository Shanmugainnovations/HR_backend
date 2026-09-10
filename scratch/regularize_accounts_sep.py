import os
from datetime import datetime
from pymongo import MongoClient
import pytz

IST = pytz.timezone('Asia/Kolkata')

def regularize_accounts():
    mongo_uri = os.environ.get("GLOBAL_DB_HOST", "mongodb://admin:SMRFT%40prod2026@45.252.190.162:27017/")
    client = MongoClient(mongo_uri)
    global_db = client["Global"]
    att_col = global_db["employees_employeeattendance"]
    schema_col = global_db["__schema__"]

    # 1. Define the missing punches for Accounts team on Sep 2 (OUT) and Sep 3 (IN)
    punches_to_regularize = [
        # --- Sep 2 OUT Punches ---
        {
            "employee_id": "50013",
            "name": "A Subashini",
            "attendence_type": "OUT",
            "device_id": "60267",
            # Exact time from spoofing attempt: 2026-09-02 19:31:58.258 IST
            "attendence_time": datetime(2026, 9, 2, 14, 1, 58, 258000),
            "confidence": 0.35,
            "reason": "Regularized from spoofing log false-positive"
        },
        {
            "employee_id": "60010",
            "name": "Mouli",
            "attendence_type": "OUT",
            "device_id": "60267",
            # Standard punch-out time ~ 07:18 PM IST
            "attendence_time": datetime(2026, 9, 2, 13, 48, 0),
            "confidence": 0.35,
            "reason": "Regularized Sep 2 OUT punch"
        },
        {
            "employee_id": "50047",
            "name": "S Karthick",
            "attendence_type": "OUT",
            "device_id": "60267",
            # Standard punch-out time ~ 07:18 PM IST
            "attendence_time": datetime(2026, 9, 2, 13, 48, 0),
            "confidence": 0.35,
            "reason": "Regularized Sep 2 OUT punch"
        },
        {
            "employee_id": "60145",
            "name": "S Prema",
            "attendence_type": "OUT",
            "device_id": "60267",
            # Standard punch-out time ~ 07:00 PM IST
            "attendence_time": datetime(2026, 9, 2, 13, 30, 0),
            "confidence": 0.35,
            "reason": "Regularized Sep 2 OUT punch"
        },

        # --- Sep 3 IN Punches ---
        {
            "employee_id": "60010",
            "name": "Mouli",
            "attendence_type": "IN",
            "device_id": "60267",
            # Exact time from spoofing attempt: 2026-09-03 10:32:18.594 IST
            "attendence_time": datetime(2026, 9, 3, 5, 2, 18, 594000),
            "confidence": 0.35,
            "reason": "Regularized from spoofing log false-positive"
        },
        {
            "employee_id": "50047",
            "name": "S Karthick",
            "attendence_type": "IN",
            "device_id": "ACCOUNTS",
            # Standard punch-in time ~ 10:09 AM IST
            "attendence_time": datetime(2026, 9, 3, 4, 39, 0),
            "confidence": 0.35,
            "reason": "Regularized Sep 3 IN punch"
        },
        {
            "employee_id": "60145",
            "name": "S Prema",
            "attendence_type": "IN",
            "device_id": "ACCOUNTS",
            # Standard punch-in time ~ 10:15 AM IST
            "attendence_time": datetime(2026, 9, 3, 4, 45, 0),
            "confidence": 0.35,
            "reason": "Regularized Sep 3 IN punch"
        }
    ]

    # 2. Check current max attendence_id and sequence
    max_doc = att_col.find_one({'attendence_id': {'$type': 'number'}}, sort=[('attendence_id', -1)])
    max_existing_id = max_doc.get('attendence_id', 0) if max_doc else 0

    schema_doc = schema_col.find_one({'name': 'employees_employeeattendance'})
    schema_seq = schema_doc.get('auto', {}).get('seq', 0) if schema_doc else 0

    current_seq = max(max_existing_id, schema_seq)
    print(f"Current Max attendence_id in Global: {max_existing_id}")
    print(f"Current Schema sequence in Global: {schema_seq}")
    print(f"Starting new attendence_id from: {current_seq + 1}")

    # 3. Insert records
    docs_to_insert = []
    for item in punches_to_regularize:
        # Check if identical record already exists
        existing = att_col.find_one({
            'employee_id': item['employee_id'],
            'attendence_time': item['attendence_time'],
            'attendence_type': item['attendence_type']
        })
        if existing:
            print(f"⚠️ Punch already exists for {item['name']} on {item['attendence_time']}, skipping.")
            continue

        current_seq += 1
        doc = {
            "attendence_id": current_seq,
            "employee_id": item["employee_id"],
            "device_id": item["device_id"],
            "attendence_time": item["attendence_time"],
            "attendence_type": item["attendence_type"],
            "confidence": item["confidence"],
            "is_regularized": True,
            "regularized_reason": item["reason"],
            "regularized_date": datetime.utcnow()
        }
        docs_to_insert.append(doc)
        dt_ist = pytz.utc.localize(item['attendence_time']).astimezone(IST).strftime('%Y-%m-%d %I:%M:%S %p')
        print(f"➕ Adding {item['attendence_type']} for {item['name']} ({item['employee_id']}) at {dt_ist} on {item['device_id']} (ID: {current_seq})")

    if docs_to_insert:
        att_col.insert_many(docs_to_insert, ordered=True)
        print(f"\n✅ Successfully regularized and inserted {len(docs_to_insert)} records.")

        # 4. Update __schema__ sequence
        schema_col.update_one(
            {'name': 'employees_employeeattendance'},
            {'$set': {'auto.seq': current_seq}}
        )
        print(f"✅ Updated Global.__schema__ seq to: {current_seq}")
    else:
        print("No new records to insert.")

if __name__ == "__main__":
    regularize_accounts()
