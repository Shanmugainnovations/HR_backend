import face_recognition
import numpy as np
from io import BytesIO
from PIL import Image
import base64
import numpy as np
import face_recognition
from io import BytesIO
import cv2
from deepface import DeepFace
import os

os.environ['DEEPFACE_LOG_LEVEL'] = 'error'

class SpoofingDetectedError(Exception):
    pass

def check_liveness(img_rgb):
    """
    Checks if the face is real using DeepFace's Anti-Spoofing (MiniFASNet).
    Returns True if real, False if spoof.
    If no face is detected by DeepFace, currently returns True (fail-open) 
    or you can change to False (fail-closed).
    """
    try:
        # Convert RGB to BGR for DeepFace/OpenCV
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        
        # Run Anti-Spoofing
        # Use 'ssd' instead of 'opencv' for better face cropping/detection
        # enforce_detection=False allows silent return if no face (though we handle it)
        try:
            detector = 'ssd' 
            faces = DeepFace.extract_faces(
                img_path=img_bgr,
                detector_backend=detector, 
                enforce_detection=False,
                align=False,
                anti_spoofing=True
            )
        except Exception as e:
            # Fallback to opencv if ssd fails (e.g. weights missing/download error)
            print(f"⚠️ DeepFace SSD backend failed, falling back to opencv: {e}")
            detector = 'opencv'
            faces = DeepFace.extract_faces(
                img_path=img_bgr,
                detector_backend=detector, 
                enforce_detection=False,
                align=False,
                anti_spoofing=True
            )
        
        if not faces:
            # If DeepFace sees no face, we can't judge liveness.
            # Assuming safe or let face_recognition handle it.
            return True
            
        for face in faces:
            # 'is_real' is populated by anti_spoofing=True
            is_real = face.get("is_real")
            score = face.get("antispoof_score", None)
            
            print(f"🕵️ DEBUG: Anti-spoof check | Backend: {detector} | Is Real: {is_real} | Score: {score}")

            if is_real is False:
                # If Score > 0.65, we override the strict default (often 0.75+)
                if score is not None and score > 0.65:
                    print(f"⚠️ Overriding Spoof detection: Score {score} > 0.65. marked as REAL.")
                    continue

                # Found a spoofed face
                return False
                
        return True
        
    except Exception as e:
        print(f"⚠️ Anti-spoofing check error: {e}")
        # Identify if we should fail or pass on error.
        # For security, better to log and maybe return False?
        # But if model loading fails, we might block legit users.
        # Let's return False to be safe and see logs.
        return False


def imagefile_to_encoding(file_obj) -> tuple:
    """
    Accepts an image file object (InMemoryUploadedFile or bytes) and returns (encoding, is_real).
    Returns ([], is_real) if no face is found.
    """
    try:
        if isinstance(file_obj, (bytes, bytearray)):
            img = face_recognition.load_image_file(BytesIO(file_obj))
        else:
            img = face_recognition.load_image_file(file_obj)

        # ✅ Anti-Spoofing Check
        is_real = check_liveness(img)
        if not is_real:
            print("⚠️ Spoofing attempt detected (flagged)!")

        encodings = face_recognition.face_encodings(img)
        if not encodings:
            return [], is_real  # return empty list instead of None
        return encodings[0].tolist(), is_real

    except Exception as e:
        print(f"⚠️ Error during face encoding: {e}")
        return [], False


def base64_to_encoding(b64_string) -> tuple:
    header, data = (b64_string.split(',',1) if ',' in b64_string else (None, b64_string))
    imgbytes = base64.b64decode(data)
    return imagefile_to_encoding(imgbytes)

def compare_encodings(known_encoding, unknown_encoding):
    """
    Return boolean match and distance (lower distance = better)
    """

    known = np.array(known_encoding)
    unknown = np.array(unknown_encoding)
    dist = np.linalg.norm(known - unknown)
    # threshold typical ~0.6 for face_recognition. 
    # Adjusted to 0.5 to balance strictness and usability.
    return (dist <= 0.5, float(dist))


import hashlib

def compute_md5(file_obj):
    """Compute MD5 hash of an uploaded image or file."""
    md5 = hashlib.md5()
    for chunk in file_obj.chunks() if hasattr(file_obj, 'chunks') else iter(lambda: file_obj.read(4096), b""):
        md5.update(chunk)
    file_obj.seek(0)  # Reset file pointer for reuse
    return md5.hexdigest()


