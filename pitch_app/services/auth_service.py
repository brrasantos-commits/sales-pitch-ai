"""
Authentication service with password hashing and validation
"""
import logging
from typing import Optional
from datetime import datetime, timedelta
import uuid

from passlib.context import CryptContext
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)


def authenticate_user(db: Session, username_or_email: str, password: str) -> Optional[dict]:
    """
    Authenticate a user with username/email and password
    Returns user dict if successful, None otherwise
    """
    try:
        # Try to find user by username or email
        user = db.execute(text("""
            SELECT id, name, username, email, password, role, active
            FROM users
            WHERE (username = :identifier OR email = :identifier) AND active = 1
        """), {"identifier": username_or_email}).fetchone()

        if not user:
            logger.warning(f"Login attempt for non-existent user: {username_or_email}")
            return None

        if not verify_password(password, user.password):
            logger.warning(f"Failed login attempt for user: {username_or_email}")
            return None

        logger.info(f"Successful login for user: {username_or_email}")
        return {
            "id": user.id,
            "name": user.name,
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "active": bool(user.active)
        }
    except Exception as e:
        logger.error(f"Error authenticating user {username_or_email}: {e}")
        return None


def create_user(db: Session, name: str, username: str, password: str, 
                role: str = "seller", email: Optional[str] = None) -> int:
    """
    Create a new user with hashed password
    Returns the new user ID
    """
    hashed_password = hash_password(password)
    
    result = db.execute(text("""
        INSERT INTO users (name, username, password, role, email, active)
        VALUES (:name, :username, :password, :role, :email, 1)
    """), {
        "name": name,
        "username": username,
        "password": hashed_password,
        "role": role,
        "email": email
    })
    db.commit()
    
    logger.info(f"Created new user: {username} with role: {role}")
    return result.lastrowid


def update_password(db: Session, user_id: int, new_password: str) -> bool:
    """Update user password with hashed version"""
    try:
        hashed_password = hash_password(new_password)
        
        db.execute(text("""
            UPDATE users
            SET password = :password
            WHERE id = :id
        """), {
            "password": hashed_password,
            "id": user_id
        })
        db.commit()
        
        logger.info(f"Password updated for user ID: {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error updating password for user {user_id}: {e}")
        db.rollback()
        return False


def create_reset_token(db: Session, email: str) -> Optional[str]:
    """
    Create a password reset token for a user
    Returns the token if user exists, None otherwise
    """
    try:
        user = db.execute(text("""
            SELECT id FROM users WHERE email = :email AND active = 1
        """), {"email": email}).fetchone()

        if not user:
            logger.warning(f"Password reset requested for non-existent email: {email}")
            return None

        token = uuid.uuid4().hex
        expiry = datetime.utcnow() + timedelta(hours=1)

        db.execute(text("""
            UPDATE users
            SET reset_token = :token,
                reset_token_expiry = :expiry
            WHERE id = :id
        """), {
            "token": token,
            "expiry": expiry.isoformat(),
            "id": user.id
        })
        db.commit()

        logger.info(f"Password reset token created for user ID: {user.id}")
        return token
    except Exception as e:
        logger.error(f"Error creating reset token for email {email}: {e}")
        db.rollback()
        return None


def reset_password_with_token(db: Session, token: str, new_password: str) -> bool:
    """
    Reset password using a valid token
    Returns True if successful, False otherwise
    """
    try:
        user = db.execute(text("""
            SELECT id, reset_token_expiry
            FROM users
            WHERE reset_token = :token AND active = 1
        """), {"token": token}).fetchone()

        if not user:
            logger.warning(f"Invalid reset token used: {token}")
            return False

        expiry = datetime.fromisoformat(user.reset_token_expiry)
        if datetime.utcnow() > expiry:
            logger.warning(f"Expired reset token used for user ID: {user.id}")
            return False

        hashed_password = hash_password(new_password)

        db.execute(text("""
            UPDATE users
            SET password = :password,
                reset_token = NULL,
                reset_token_expiry = NULL
            WHERE id = :id
        """), {
            "password": hashed_password,
            "id": user.id
        })
        db.commit()

        logger.info(f"Password reset successful for user ID: {user.id}")
        return True
    except Exception as e:
        logger.error(f"Error resetting password with token: {e}")
        db.rollback()
        return False

# Made with Bob
