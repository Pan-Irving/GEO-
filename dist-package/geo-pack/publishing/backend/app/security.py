import hashlib
import hmac
import secrets


def hash_password(password: str, salt: str | None = None) -> str:
    current_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), current_salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${current_salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        method, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    if method != "pbkdf2_sha256":
        return False
    return hmac.compare_digest(hash_password(password, salt), f"{method}${salt}${digest}")


def new_token() -> str:
    return secrets.token_urlsafe(32)
