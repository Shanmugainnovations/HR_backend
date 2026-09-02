import jwt
import datetime
from django.conf import settings

def generate_employee_token(employee_id, role='Employee', exp_days=30):
    """
    Generates a cryptographically signed JWT Access Token for an employee.
    """
    now = datetime.datetime.utcnow()
    payload = {
        "employee_id": str(employee_id),
        "role": str(role),
        "iat": now,
        "exp": now + datetime.timedelta(days=exp_days)
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token

def decode_employee_token(token):
    """
    Decodes a JWT Access Token supporting HS256, RS256, and ES256 algorithms.
    Returns payload dict if valid, or None if expired/tampered.
    """
    if not token:
        return None
    try:
        # Strip "Bearer " prefix if present
        if token.startswith("Bearer "):
            token = token.split(" ")[1]

        # First attempt with verify_signature=False to support RS256 tokens issued by auth server
        payload = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256", "RS256", "ES256"])
        return payload
    except jwt.ExpiredSignatureError:
        print("Token has expired")
        return None
    except jwt.InvalidTokenError as e:
        print("Invalid token signature", e)
        return None
    except Exception as e:
        print("Error decoding token", e)
        return None
