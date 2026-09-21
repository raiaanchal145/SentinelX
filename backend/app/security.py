import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.config import settings

ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


def generate_invitation_token() -> tuple[str, str]:
    """
    32 random urlsafe bytes for the link the invitee actually clicks,
    and its SHA-256 hex digest for what gets stored (invitations.token_hash).
    A raw token is never written to the database -- same principle as a
    password, deliberately a different, much cheaper mechanism than
    bcrypt above: a bare SHA-256 lookup key that's fine to hash on every
    read (validating a token on GET /invitations/{token}, potentially
    unauthenticated and rate-limited by nothing yet) as long as the raw
    value is unguessable, which 32 bytes of secrets.token_urlsafe is.
    """
    raw = secrets.token_urlsafe(32)
    return raw, hash_invitation_token(raw)


def hash_invitation_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
