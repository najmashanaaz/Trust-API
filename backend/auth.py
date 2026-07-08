"""
backend/auth.py
───────────────
Handles password hashing, JWT token creation and verification.
"""

import os
import bcrypt
from datetime import datetime, timedelta
from jose import JWTError, jwt

# Change this to a long random string in production
SECRET_KEY = os.environ.get("SECRET_KEY", "trustapi-secret-key-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    """Hashes a plain password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Checks if a plain password matches the stored hash."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int, email: str) -> str:
    """Creates a JWT token that expires in TOKEN_EXPIRE_DAYS days."""
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    """
    Decodes and validates a JWT token.
    Returns the payload dict if valid, None if expired or invalid.
    """
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None