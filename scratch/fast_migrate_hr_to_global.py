import os
import logging
from pymongo import MongoClient, ReplaceOne

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def fast_migrate_hr_to_global():
    mongo_uri = os.environ.get("GLOBAL_DB_HOST", "mongodb://admin:SMRFT%40test@45.120.136.230:27017/")
    logger.info(f"Connecting to MongoDB at: {mongo_uri}")

    client = MongoClient(mongo_uri)
    hr_db = client["HR"]
    global_db = client["Global"]

    hr_collections = hr_db.list_collection_names()
    logger.info(f"Found {len(hr_collections)} collections in 'HR' database.")

    skip_cols = {
        "system.views", "system.profile",
        "django_migrations", "django_content_type", "auth_permission",
        "auth_group", "auth_user", "django_session", "__schema__",
        "auth_user_user_permissions", "auth_group_permissions"
    }

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

        logger.info(f"Bulk migrating collection '{col_name}' ({doc_count} documents)...")

        batch_ops = []
        batch_size = 1000
        count = 0

        for doc in hr_col.find({}):
            doc_id = doc.get("_id")
            if doc_id is not None:
                batch_ops.append(ReplaceOne({"_id": doc_id}, doc, upsert=True))
            else:
                batch_ops.append(ReplaceOne(doc, doc, upsert=True))

            if len(batch_ops) >= batch_size:
                global_col.bulk_write(batch_ops, ordered=False)
                count += len(batch_ops)
                batch_ops = []

        if batch_ops:
            global_col.bulk_write(batch_ops, ordered=False)
            count += len(batch_ops)

        total_migrated_docs += count
        logger.info(f"  ✅ '{col_name}': {count} documents migrated cleanly.")

    logger.info(f"\n🎉 FAST Migration Complete! Total documents processed across all collections: {total_migrated_docs}")

if __name__ == "__main__":
    fast_migrate_hr_to_global()
