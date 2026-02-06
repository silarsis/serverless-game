"""Firebase authentication module for verifying tokens and managing users."""

import os
import time

import boto3
import firebase_admin
import jwt
from botocore.exceptions import ClientError
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials

# Firebase Admin SDK initialization (singleton)
FIREBASE_APP = None
FIREBASE_CREDS_PATH = os.environ.get(
    "FIREBASE_SERVICE_ACCOUNT", "/tmp/firebase-service-account.json"
)


def _init_firebase():
    """Initialize Firebase Admin SDK singleton."""
    global FIREBASE_APP
    if not FIREBASE_APP:
        cred = credentials.Certificate(FIREBASE_CREDS_PATH)
        FIREBASE_APP = firebase_admin.initialize_app(cred, name="gameserver")


# DynamoDB setup
DYNAMODB = boto3.resource("dynamodb")
USERS_TABLE = os.environ.get("USERS_TABLE", "users-dev")
TABLE = DYNAMODB.Table(USERS_TABLE)

# JWT settings for WebSocket auth
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


def verify_firebase_token(token: str) -> dict:
    """Verify a Firebase ID token and return user info.

    Args:
        token: Firebase ID token from client.

    Returns:
        dict with firebase_uid, email, name, picture.

    Raises:
        ValueError: If token is invalid or expired.
    """
    _init_firebase()
    try:
        decoded = firebase_auth.verify_id_token(token)
        return {
            "firebase_uid": decoded["uid"],
            "email": decoded.get("email", ""),
            "email_verified": decoded.get("email_verified", False),
            "name": decoded.get("name", ""),
            "picture": decoded.get("picture", ""),
        }
    except Exception as e:
        raise ValueError(f"Invalid Firebase token: {e}")


def _generate_jwt(user_id: str) -> str:
    """Generate internal JWT for WebSocket auth."""
    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + (JWT_EXPIRY_HOURS * 3600),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_or_create_user(firebase_uid: str, user_info: dict) -> dict:
    """Get existing user or create new one in DynamoDB.

    Args:
        firebase_uid: Firebase user ID.
        user_info: Dict with email, name, picture from Firebase.

    Returns:
        User record from DynamoDB.
    """
    try:
        response = TABLE.get_item(Key={"firebase_uid": firebase_uid})
        if "Item" in response:
            return response["Item"]
    except ClientError as e:
        print(f"Error getting user: {e}")

    # Create new user
    user = {
        "firebase_uid": firebase_uid,
        "email": user_info.get("email", ""),
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "created_at": int(time.time()),
        "last_login": int(time.time()),
    }

    try:
        TABLE.put_item(Item=user)
    except ClientError as e:
        print(f"Error creating user: {e}")
        raise

    return user


def login(token: str) -> dict:
    """Handle login flow: verify Firebase token, get/create user, return JWT.

    Args:
        token: Firebase ID token from client.

    Returns:
        dict with success, jwt, user fields.
    """
    try:
        firebase_user = verify_firebase_token(token)
        user = get_or_create_user(
            firebase_user["firebase_uid"],
            firebase_user,
        )
        internal_jwt = _generate_jwt(firebase_user["firebase_uid"])

        return {
            "success": True,
            "jwt": internal_jwt,
            "user": {
                "firebase_uid": user["firebase_uid"],
                "email": user["email"],
                "name": user["name"],
                "picture": user["picture"],
            },
        }
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Login failed: {e}"}
