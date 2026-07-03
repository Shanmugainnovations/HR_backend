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
        # 'mtcnn' is much more robust for anti-spoofing than 'opencv'
        detector = 'mtcnn' 
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
                # 🚨 Strict Enforcement: If model says spoof, we reject.
                # Score is probability of being real. 
                print(f"🚨 REJECTED: Anti-spoofing model flagged this as a spoof (Score: {score})")
                return False
            
            # Additional check: even if is_real is True, if score is very low, flag it
            if score is not None and score < 0.25:
                print(f"🚨 REJECTED: Low realness score despite 'is_real' flag (Score: {score})")
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

def compare_encodings(known_encoding, unknown_encoding, threshold=0.40):
    """
    Return boolean match and distance (lower distance = better)
    """

    known = np.array(known_encoding)
    unknown = np.array(unknown_encoding)
    dist = np.linalg.norm(known - unknown)
    # Adjusted to 0.40 to ensure strict verification without false positives.
    return (dist <= threshold, float(dist))


def match_face_1_to_n(unknown_encoding, known_matrix, employee_meta, threshold=0.40, min_margin=0.05):
    """
    Matches an unknown face encoding against a matrix of known encodings (1:N identification).
    Applies Lowe's Nearest Neighbor Distance Ratio (NNDR) / margin check to prevent false positives.
    
    Returns:
        tuple: (matched_meta, best_distance, error_reason)
        If matched_meta is None, verification failed for the reason in error_reason.
    """
    if unknown_encoding is None or len(unknown_encoding) == 0 or known_matrix is None or len(known_matrix) == 0 or not employee_meta:
        return None, 999.0, "No registered employees found or invalid encoding."

    unknown = np.array(unknown_encoding)
    distances = np.linalg.norm(known_matrix - unknown, axis=1)

    # Group minimum distance by unique employee_id
    emp_best_dist = {}
    emp_meta_map = {}
    for idx, dist in enumerate(distances):
        meta = employee_meta[idx]
        emp_id = meta['employee_id']
        if emp_id not in emp_best_dist or dist < emp_best_dist[emp_id]:
            emp_best_dist[emp_id] = float(dist)
            emp_meta_map[emp_id] = meta

    # Sort unique employees by best distance ascending
    sorted_emps = sorted(emp_best_dist.items(), key=lambda x: x[1])
    
    if not sorted_emps:
        return None, 999.0, "No valid employee comparisons possible."

    best_emp_id, best_dist = sorted_emps[0]
    best_meta = emp_meta_map[best_emp_id]

    # Check absolute threshold first
    if best_dist > threshold:
        print(f"❌ Rejected: Best distance {best_dist:.4f} exceeds threshold {threshold}")
        return None, best_dist, "User Not Found. Face match not confident enough."

    # Check Lowe's NNDR margin against the second closest DIFFERENT employee
    if len(sorted_emps) > 1:
        second_emp_id, second_dist = sorted_emps[1]
        margin = second_dist - best_dist
        ratio = best_dist / second_dist if second_dist > 0 else 1.0
        
        print(f"🔍 DEBUG Face Match: 1st={best_meta['name']} ({best_dist:.4f}) | 2nd={emp_meta_map[second_emp_id]['name']} ({second_dist:.4f}) | Margin={margin:.4f} | Ratio={ratio:.4f}")
        
        # If the second best employee is too close to the best match, it is ambiguous
        if margin < min_margin and ratio > 0.88:
            print(f"❌ Rejected: Ambiguous match between {best_meta['name']} and {emp_meta_map[second_emp_id]['name']} (Margin: {margin:.4f})")
            return None, best_dist, "Face match ambiguous with another registered employee. Please ensure good lighting and face camera directly."
    else:
        print(f"🔍 DEBUG Face Match: 1st={best_meta['name']} ({best_dist:.4f}) | Only 1 employee in database.")

    print(f"✅ Confident Match: {best_meta['name']} (ID: {best_emp_id}) with distance {best_dist:.4f}")
    return best_meta, best_dist, None


import hashlib

def compute_md5(file_obj):
    """Compute MD5 hash of an uploaded image or file."""
    md5 = hashlib.md5()
    for chunk in file_obj.chunks() if hasattr(file_obj, 'chunks') else iter(lambda: file_obj.read(4096), b""):
        md5.update(chunk)
    file_obj.seek(0)  # Reset file pointer for reuse
    return md5.hexdigest()


