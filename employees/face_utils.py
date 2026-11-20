"""
Stub module for face_utils.
Facial recognition and heavy ML dependencies (dlib, face_recognition, deepface)
have been decommissioned.
"""
import hashlib

class SpoofingDetectedError(Exception):
    pass

def compute_md5(file_obj):
    """Compute MD5 hash of an uploaded image or file."""
    md5 = hashlib.md5()
    for chunk in file_obj.chunks() if hasattr(file_obj, 'chunks') else iter(lambda: file_obj.read(4096), b""):
        md5.update(chunk)
    file_obj.seek(0)
    return md5.hexdigest()

def imagefile_to_encoding(file_obj) -> tuple:
    return [], False

def base64_to_encoding(b64_string) -> tuple:
    return [], False

def compare_encodings(known_encoding, unknown_encoding, threshold=0.45):
    return False, 999.0

def match_face_1_to_n(unknown_encoding, known_matrix, employee_meta, threshold=0.45, min_margin=0.05):
    return None, 999.0, "Face recognition has been disabled."

def check_liveness(img_rgb, face_locations=None):
    return True
