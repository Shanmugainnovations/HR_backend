import os
import sys
from datetime import datetime
from pymongo import MongoClient

def sync_missing_attendance():
    mongo_uri = os.environ.get("GLOBAL_DB_HOST", "mongodb://admin:SMRFT%40prod2026@45.252.190.162:27017/")
    print(f"Connecting to MongoDB at: {mongo_uri}")
    client = MongoClient(mongo_uri)

    global_db = client["Global"]
    hr_db = client["HR"]

    global_col = global_db["employees_employeeattendance"]
    hr_col = hr_db["employees_employeeattendance"]
    schema_col = global_db["__schema__"]

    # 1. Date window for September 2026
    start_dt = datetime(2026, 9, 1)
    end_dt = datetime(2026, 10, 1)

    print("Fetching existing September _ids from Global...")
    global_oids = set(global_col.distinct('_id', {'attendence_time': {'$gte': start_dt, '$lt': end_dt}}))
    print(f"Found {len(global_oids)} existing September records in Global.")

    # 2. Find missing records from HR collection
    missing_records = list(hr_col.find({
        'attendence_time': {'$gte': start_dt, '$lt': end_dt},
        '_id': {'$nin': list(global_oids)}
    }))
    print(f"Found {len(missing_records)} records in HR that are MISSING in Global.")

    if not missing_records:
        print("✅ No missing records found. Everything is already in sync!")
        return

    # Sort chronologically by attendence_time ascending
    missing_records.sort(key=lambda x: x['attendence_time'])

    # 3. Determine safe starting attendence_id
    max_doc = global_col.find_one({'attendence_id': {'$type': 'number'}}, sort=[('attendence_id', -1)])
    max_existing_id = max_doc.get('attendence_id', 0) if max_doc else 0

    schema_doc = schema_col.find_one({'name': 'employees_employeeattendance'})
    schema_seq = schema_doc.get('auto', {}).get('seq', 0) if schema_doc else 0

    current_seq = max(max_existing_id, schema_seq)
    print(f"Current Max attendence_id in Global: {max_existing_id}")
    print(f"Current Schema sequence in Global: {schema_seq}")
    print(f"Starting new attendence_id from: {current_seq + 1}")

    # 4. Prepare docs with safe sequential attendence_id
    docs_to_insert = []
    for doc in missing_records:
        current_seq += 1
        new_doc = dict(doc)
        new_doc['old_attendence_id'] = doc.get('attendence_id')
        new_doc['attendence_id'] = current_seq
        docs_to_insert.append(new_doc)

    print(f"\nInserting {len(docs_to_insert)} records into Global.employees_employeeattendance...")
    insert_result = global_col.insert_many(docs_to_insert, ordered=True)
    print(f"✅ Successfully inserted {len(insert_result.inserted_ids)} documents.")

    # 5. Update __schema__ sequence so Django AutoField never collides
    new_final_seq = current_seq
    schema_col.update_one(
        {'name': 'employees_employeeattendance'},
        {'$set': {'auto.seq': new_final_seq}}
    )
    print(f"✅ Updated Global.__schema__ employees_employeeattendance seq to: {new_final_seq}")

    # 6. Verification
    verify_schema = schema_col.find_one({'name': 'employees_employeeattendance'})
    print("Verification __schema__ auto:", verify_schema.get('auto'))
    verify_max = global_col.find_one({'attendence_id': {'$type': 'number'}}, sort=[('attendence_id', -1)])
    print("Verification max attendence_id in Global:", verify_max.get('attendence_id'))

    new_global_count = global_col.count_documents({'attendence_time': {'$gte': start_dt, '$lt': end_dt}})
    print(f"New September total in Global: {new_global_count} records (was 4085, expected {4085 + len(docs_to_insert)})")

if __name__ == "__main__":
    sync_missing_attendance()
