import os
import sys

from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'employees'

    def ready(self):
        # Skip warm-up for management commands (migrate, makemigrations, shell, etc.)
        # so we don't pay the model-load cost when we're not actually serving requests.
        if len(sys.argv) > 1 and sys.argv[1] not in ('runserver', 'run_gunicorn'):
            return
        if os.environ.get('RUN_MAIN') == 'false':
            return

        try:
            self._warm_up_face_models()
        except Exception as e:
            print(f"⚠️ Face model warm-up skipped: {e}")

    def _warm_up_face_models(self):
        """
        Loads the DeepFace anti-spoofing/detector models into memory once at process
        startup, instead of lazily on the first verify/mark-attendance request. Without
        this, each gunicorn worker pays this load cost on its first real request.
        """
        import numpy as np
        from deepface import DeepFace

        os.environ.setdefault('DEEPFACE_LOG_LEVEL', 'error')
        dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
        DeepFace.extract_faces(
            img_path=dummy_img,
            detector_backend='skip',
            enforce_detection=False,
            align=False,
            anti_spoofing=True,
        )
        print("✅ Face recognition models warmed up.")
