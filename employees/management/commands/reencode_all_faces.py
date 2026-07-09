"""
Management command: reencode_all_faces
=======================================
Re-encodes face encodings for all active employees using the latest
imagefile_to_encoding() pipeline (explicit face detect, CLAHE, num_jitters=2).

Image source: HR DB → GridFS (fetched via employee's image_md5 stored in Employee model).

Usage:
    python3.11 manage.py reencode_all_faces
    python3.11 manage.py reencode_all_faces --dry-run          # preview only
    python3.11 manage.py reencode_all_faces --employee EMP001  # single employee
"""

import hashlib
import os
from io import BytesIO

import gridfs
from django.core.management.base import BaseCommand
from pymongo import MongoClient

from employees.face_utils import imagefile_to_encoding
from employees.models import Employee
from employees.views.utils import save_or_update_encoding


class Command(BaseCommand):
    help = "Batch re-encode face encodings for all active employees (uses HR DB GridFS)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without saving anything.",
        )
        parser.add_argument(
            "--employee",
            type=str,
            default=None,
            help="Re-encode a single employee by employee_id.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        single_emp = options["employee"]

        # HR DB GridFS connection
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        hr_db_name = os.getenv("HR_DB_NAME", "HR")

        if not mongo_uri:
            self.stderr.write(self.style.ERROR("GLOBAL_DB_HOST not set in environment."))
            return

        client = MongoClient(mongo_uri)
        fs = gridfs.GridFS(client[hr_db_name])

        # Load employees (Python filter — avoids Djongo SQL issues)
        all_employees = list(Employee.objects.all())
        if single_emp:
            employees = [e for e in all_employees if e.employee_id == single_emp]
        else:
            employees = [e for e in all_employees if e.is_active]

        total = len(employees)
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n{'[DRY RUN] ' if dry_run else ''}Re-encoding {total} employee(s) from HR DB...\n"
            )
        )

        success = 0
        skipped = 0
        failed = 0

        for emp in employees:
            emp_id = emp.employee_id
            prefix = f"  [{emp_id}] {emp.name}"

            # Check image_md5 exists
            if not emp.image_md5:
                self.stdout.write(f"{prefix} -> SKIP (no image_md5 — not registered via face upload)")
                skipped += 1
                continue

            # Fetch image from HR GridFS using MD5
            try:
                file_obj = fs.find_one({"md5": emp.image_md5})
                if not file_obj:
                    self.stdout.write(f"{prefix} -> SKIP (image not found in HR GridFS for md5={emp.image_md5[:8]}...)")
                    skipped += 1
                    continue

                raw_bytes = file_obj.read()
                img_bytes = BytesIO(raw_bytes)

            except Exception as e:
                self.stdout.write(self.style.WARNING(f"{prefix} -> FAIL (image fetch: {e})"))
                failed += 1
                continue

            # Re-encode with new pipeline (liveness skipped — static photo)
            try:
                encoding, _ = imagefile_to_encoding(img_bytes)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"{prefix} -> FAIL (encoding: {e})"))
                failed += 1
                continue

            if not encoding:
                self.stdout.write(f"{prefix} -> SKIP (no face detected in stored image)")
                skipped += 1
                continue

            # Save
            if dry_run:
                self.stdout.write(self.style.SUCCESS(f"{prefix} -> WOULD UPDATE"))
            else:
                try:
                    save_or_update_encoding(
                        emp_id,
                        encoding,
                        created_by=None,
                        name=emp.name,
                        image_md5=emp.image_md5,
                        refresh_cache=False,  # skip per-save refresh; do one at the end
                    )
                    self.stdout.write(self.style.SUCCESS(f"{prefix} -> UPDATED"))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"{prefix} -> FAIL (save: {e})"))
                    failed += 1
                    continue

            success += 1

        # Summary
        self.stdout.write("\n" + "-" * 50)
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Done.  Updated: {success}  |  Skipped: {skipped}  |  Failed: {failed}"
            )
        )
        if not dry_run and success > 0:
            # Single cache refresh after all updates
            try:
                from employees.views.attendance import get_optimized_encodings
                get_optimized_encodings(force_refresh=True)
                self.stdout.write(self.style.NOTICE("\nFace encoding cache refreshed."))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Cache refresh failed: {e}. Call POST /refresh-face-cache/ manually."))
