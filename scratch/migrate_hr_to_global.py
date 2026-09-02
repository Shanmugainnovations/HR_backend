import os
import sys
import logging
from pymongo import MongoClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def migrate_hr_to_global():
    mongo_uri = os.environ.get("GLOBAL_DB_HOST", "mongodb://admin:SMRFT%40test@45.120.136.230:27017/")
    logger.info(f"Connecting to MongoDB at: {mongo_uri}")

    client = MongoClient(mongo_uri)
    hr_db = client["HR"]
    global_db = client["Global"]

    hr_collections = hr_db.list_collection_names()
    logger.info(f"Found {len(hr_collections)} collections in 'HR' database.")

    # Skip internal system collections
    skip_cols = {"system.views", "system.profile"}

    total_migrated_docs = 0

    for col_name in hr_collections:
        if col_name in skip_cols:
            continue

        hr_col = hr_db[col_name]
        global_col = global_db[col_name]

        doc_count = hr_col.count_documents({})
        if doc_count == 0:
            logger.info(f"Skipping empty collection: '{col_name}'")
            continue

        logger.info(f"Migrating collection '{col_name}' ({doc_count} documents)...")

        docs = list(hr_col.find({}))
        inserted_count = 0
        skipped_count = 0

        for doc in docs:
            doc_id = doc.get("_id")
            if doc_id is not None:
                # Upsert document into Global DB by _id
                res = global_col.replace_one({"_id": doc_id}, doc, upsert=True)
                if res.upserted_id or res.modified_count:
                    inserted_count += 1
                else:
                    skipped_count += 1
            else:
                global_col.insert_one(doc)
                inserted_count += 1

        total_migrated_docs += (inserted_count + skipped_count)
        logger.info(f"  ✅ '{col_name}': {inserted_count} updated/inserted, {skipped_count} existing.")

    logger.info(f"\n🎉 Migration Complete! Total documents processed across all HR collections: {total_migrated_docs}")

if __name__ == "__main__":
    migrate_hr_to_global()
