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
import logging

# DeepFace expects a numeric logging level (e.g. str(logging.ERROR) == '40'), not the word 'error'.
# The previous value caused DeepFace to fail parsing it and fall back to INFO-level logging.
os.environ['DEEPFACE_LOG_LEVEL'] = str(logging.ERROR)

class SpoofingDetectedError(Exception):
    pass

def _reject_or_accept(is_real, score):
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


def check_liveness(img_rgb, face_locations=None):
    """
    Checks if the face is real using DeepFace's Anti-Spoofing (MiniFASNet/FasNet).
    Returns True if real, False if spoof.

    IMPORTANT: FasNet's model (see deepface/models/spoofing/FasNet.py `analyze()`) needs the
    FULL frame plus the face's bounding box - it crops two different margins (2.7x and 4x)
    around that box itself to compare the face against its surrounding background/context,
    which is precisely how it tells a live face from a screen/photo/paper spoof. Passing it an
    already-tightly-cropped face image (e.g. via detector_backend='skip', which treats the
    whole input as the "facial area") leaves no background for those margin crops to include -
    they collapse back to the same tight crop, starving the model of the signal it needs and
    making it prone to misclassifying real, live faces as spoofed.

    So when `face_locations` (from face_recognition's own HOG detector) is provided, we call
    the FasNet model directly on the FULL frame with that real bounding box - still avoiding a
    second full-frame MTCNN detection pass (the original optimization goal), but without
    breaking the model's expected input.
    """
    try:
        # Convert RGB to BGR for DeepFace/OpenCV
        img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)

        if face_locations:
            top, right, bottom, left = face_locations[0]
            x, y = max(0, left), max(0, top)
            w, h = max(1, right - left), max(1, bottom - top)

            try:
                from deepface.modules import modeling
                antispoof_model = modeling.build_model(task="spoofing", model_name="Fasnet")
                is_real, score = antispoof_model.analyze(img=img_bgr, facial_area=(x, y, w, h))
            except Exception as e:
                print(f"⚠️ DeepFace liveness check failed: {e}")
                return True  # Fail-open for usability if model fails

            return _reject_or_accept(is_real, score)

        # No prior detection available (defensive fallback) - let DeepFace detect + anti-spoof
        # together on the full frame. 'mtcnn' is much more robust for anti-spoofing than 'opencv'.
        try:
            faces = DeepFace.extract_faces(
                img_path=img_bgr,
                detector_backend='mtcnn',
                enforce_detection=False,
                align=True,
                anti_spoofing=True
            )
        except Exception as e:
            print(f"⚠️ DeepFace liveness check failed: {e}")
            return True  # Fail-open for usability if model fails

        if not faces:
            # If no face detected by DeepFace, we let face_recognition handle detection
            return True

        for face in faces:
            if not _reject_or_accept(face.get("is_real"), face.get("antispoof_score", None)):
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
        if max(h, w) > 800:
            scale = 800 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        # ✅ Detect the face location once (HOG) and reuse it for both the liveness
        # check and the encoding step below, instead of letting DeepFace (MTCNN)
        # and face_recognition each run their own independent full-frame detector.
        face_locations = face_recognition.face_locations(img, model='hog')

        # (CLAHE removed here to avoid double processing and to keep original image for liveness check)
        # ✅ Anti-Spoofing Check
        is_real = check_liveness(img, face_locations)
        if not is_real:
            print("⚠️ Spoofing attempt detected (flagged)!")

        # ✅ Lighting Correction: Apply CLAHE to improve accuracy in varied lighting
        # CLAHE operates on the L channel of LAB color space
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            cl = clahe.apply(l)
            limg = cv2.merge((cl,a,b))
            img = cv2.cvtColor(limg, cv2.COLOR_LAB2RGB)
        except Exception as e:
            print(f"⚠️ CLAHE processing error, continuing with original image: {e}")

        # ✅ Face Encoding — reuse the face_locations detected above instead of
        # letting face_encodings() re-run HOG detection internally.
        encodings = face_recognition.face_encodings(img, known_face_locations=face_locations)
        
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

def compare_encodings(known_encoding, unknown_encoding, threshold=0.45):
    """
    Return boolean match and distance (lower distance = better)
    """

    known = np.array(known_encoding)
    unknown = np.array(unknown_encoding)
    dist = np.linalg.norm(known - unknown)
    # Adjusted to 0.40 to ensure strict verification without false positives.
    return (dist <= threshold, float(dist))


def match_face_1_to_n(unknown_encoding, known_matrix, employee_meta, threshold=0.45, min_margin=0.05):
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
        return best_meta, best_dist, "User Not Found. Face match not confident enough."

    # Check Lowe's NNDR margin against the second closest DIFFERENT employee
    if len(sorted_emps) > 1:
        second_emp_id, second_dist = sorted_emps[1]
        margin = second_dist - best_dist
        ratio = best_dist / second_dist if second_dist > 0 else 1.0
        
        print(f"🔍 DEBUG Face Match: 1st={best_meta['name']} ({best_dist:.4f}) | 2nd={emp_meta_map[second_emp_id]['name']} ({second_dist:.4f}) | Margin={margin:.4f} | Ratio={ratio:.4f}")
        
        # If the second best employee is too close to the best match, it is ambiguous
        if margin < min_margin and ratio > 0.88:
            print(f"❌ Rejected: Ambiguous match between {best_meta['name']} and {emp_meta_map[second_emp_id]['name']} (Margin: {margin:.4f})")
            return best_meta, best_dist, "Face match ambiguous with another registered employee. Please ensure good lighting and face camera directly."
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
    file_obj.seek(0)  # Reset file pointer for reuse add
    return md5.hexdigest()
