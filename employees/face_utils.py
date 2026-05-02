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
    Uses 'opencv' for speed as it's much faster than 'ssd'.
    """
    try:
        # Convert RGB to BGR for DeepFace/OpenCV
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        
        # Run Anti-Spoofing
        # 'opencv' is very fast. 'ssd' or 'mtcnn' are more accurate but slower.
        detector = 'opencv' 
        try:
            faces = DeepFace.extract_faces(
                img_path=img_bgr,
                detector_backend=detector, 
                enforce_detection=False,
                align=True,
                anti_spoofing=True
            )
        except Exception as e:
            print(f"⚠️ DeepFace liveness check failed: {e}")
            return True # Fail-open for usability if model fails
        
        if not faces:
            # If no face detected by DeepFace, we let face_recognition handle detection
            return True
            
        for face in faces:
            is_real = face.get("is_real")
            score = face.get("antispoof_score", None)
            
            print(f"🕵️ DEBUG: Anti-spoof check | Score: {score} | Is Real: {is_real}")

            if is_real is False:
                # Higher score override for edge cases
                if score is not None and score > 0.60:
                    continue
                return False
                
        return True
        
    except Exception as e:
        print(f"⚠️ Anti-spoofing error: {e}")
        return True # Fail-open to avoid blocking legit users on system errors


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

        # ✅ Optimization: Resize image if it's too large to speed up processing
        # Large images (e.g. 4K) take much longer to process without accuracy gain for face matching.
        h, w = img.shape[:2]
        if max(h, w) > 1024:
            scale = 1024 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        # ✅ Pre-processing: Apply Contrast Normalization (CLAHE)
        # This helps in consistent recognition across different lighting conditions
        img_yuv = cv2.cvtColor(img, cv2.COLOR_RGB2YUV)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        img_yuv[:,:,0] = clahe.apply(img_yuv[:,:,0])
        img = cv2.cvtColor(img_yuv, cv2.COLOR_YUV2RGB)

        # ✅ Anti-Spoofing Check
        is_real = check_liveness(img)
        if not is_real:
            print("⚠️ Spoofing attempt detected (flagged)!")

        # ✅ Face Encoding with model='hog' (Standard) or 'cnn' (Very Slow but Accurate)
        # We stick to HOG for speed but ensure we handle multiple faces
        encodings = face_recognition.face_encodings(img)
        
        if not encodings:
            return [], is_real
            
        # If multiple faces are detected, it's a security risk/mismatch risk
        if len(encodings) > 1:
            print(f"⚠️ Warning: {len(encodings)} faces detected. Using the most prominent one.")
            # Usually the first encoding is the largest face found
            
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


