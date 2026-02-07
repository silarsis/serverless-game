"""Authentication module for Google OAuth and API key verification."""

import json
import os
import secrets
import time

import boto3
import jwt
from botocore.exceptions import ClientError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

# Google OAuth config
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")

# DynamoDB setup
DYNAMODB = boto3.resource("dynamodb")
USERS_TABLE = os.environ.get("USERS_TABLE", "users-dev")
API_KEYS_TABLE = os.environ.get("API_KEYS_TABLE", "api-keys-dev")

# JWT settings for internal WebSocket auth
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


def verify_google_token(token: str) -> dict:
    """Verify a Google OAuth ID token and return user info.

    Args:
        token: Google ID token from client.

    Returns:
        dict with google_uid, email, name, picture.

    Raises:
        ValueError: If token is invalid or expired.
    """
    try:
        idinfo = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), GOOGLE_CLIENT_ID
        )
        return {
            "google_uid": idinfo["sub"],
            "email": idinfo.get("email", ""),
            "email_verified": idinfo.get("email_verified", False),
            "name": idinfo.get("name", ""),
            "picture": idinfo.get("picture", ""),
        }
    except Exception as e:
        raise ValueError(f"Invalid Google token: {e}")


def _generate_jwt(user_id: str, bot_name: str = None) -> str:
    """Generate internal JWT for WebSocket auth.

    Args:
        user_id: The Google UID (sub claim).
        bot_name: Optional bot name if authenticating via API key.

    Returns:
        Encoded JWT string.
    """
    payload = {
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + (JWT_EXPIRY_HOURS * 3600),
    }
    if bot_name:
        payload["bot_name"] = bot_name
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict:
    """Verify an internal JWT and return its claims.

    Args:
        token: Internal JWT string.

    Returns:
        Decoded JWT payload.

    Raises:
        ValueError: If token is invalid or expired.
    """
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {e}")


def get_or_create_user(google_uid: str, user_info: dict) -> dict:
    """Get existing user or create new one in DynamoDB.

    Args:
        google_uid: Google user ID (sub claim).
        user_info: Dict with email, name, picture from Google.

    Returns:
        User record from DynamoDB.
    """
    table = DYNAMODB.Table(USERS_TABLE)
    try:
        response = table.get_item(Key={"google_uid": google_uid})
        if "Item" in response:
            # Update last_login
            table.update_item(
                Key={"google_uid": google_uid},
                UpdateExpression="SET last_login = :t",
                ExpressionAttributeValues={":t": int(time.time())},
            )
            return response["Item"]
    except ClientError as e:
        print(f"Error getting user: {e}")

    # Create new user
    user = {
        "google_uid": google_uid,
        "email": user_info.get("email", ""),
        "name": user_info.get("name", ""),
        "picture": user_info.get("picture", ""),
        "created_at": int(time.time()),
        "last_login": int(time.time()),
    }

    try:
        table.put_item(Item=user)
    except ClientError as e:
        print(f"Error creating user: {e}")
        raise

    return user


def _verify_api_key(api_key: str) -> dict:
    """Verify an API key and return the associated user info.

    Args:
        api_key: The API key string.

    Returns:
        dict with google_uid and bot_name.

    Raises:
        ValueError: If the API key is invalid.
    """
    table = DYNAMODB.Table(API_KEYS_TABLE)
    try:
        response = table.get_item(Key={"api_key": api_key})
        if "Item" not in response:
            raise ValueError("Invalid API key")
        return {
            "google_uid": response["Item"]["google_uid"],
            "bot_name": response["Item"]["bot_name"],
        }
    except ClientError as e:
        raise ValueError(f"API key lookup failed: {e}")


def login(token: str = None, api_key: str = None) -> dict:
    """Handle login: verify Google token or API key, return internal JWT.

    Args:
        token: Google ID token from client (for human login).
        api_key: API key string (for bot login).

    Returns:
        dict with success, jwt, user fields.
    """
    try:
        if api_key:
            key_info = _verify_api_key(api_key)
            internal_jwt = _generate_jwt(
                key_info["google_uid"], bot_name=key_info["bot_name"]
            )
            return {
                "success": True,
                "jwt": internal_jwt,
                "user": {
                    "google_uid": key_info["google_uid"],
                    "bot_name": key_info["bot_name"],
                },
            }
        elif token:
            google_user = verify_google_token(token)
            user = get_or_create_user(
                google_user["google_uid"],
                google_user,
            )
            internal_jwt = _generate_jwt(google_user["google_uid"])
            return {
                "success": True,
                "jwt": internal_jwt,
                "user": {
                    "google_uid": user["google_uid"],
                    "email": user["email"],
                    "name": user["name"],
                    "picture": user["picture"],
                },
            }
        else:
            return {"success": False, "error": "Provide either token or api_key"}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": f"Login failed: {e}"}


def generate_api_key(google_uid: str, bot_name: str) -> dict:
    """Generate an API key for a bot, tied to a user account.

    Args:
        google_uid: The authenticated user's Google UID.
        bot_name: A name for the bot this key is for.

    Returns:
        dict with api_key, bot_name, created_at.
    """
    api_key = secrets.token_urlsafe(32)
    table = DYNAMODB.Table(API_KEYS_TABLE)
    item = {
        "api_key": api_key,
        "google_uid": google_uid,
        "bot_name": bot_name,
        "created_at": int(time.time()),
    }
    table.put_item(Item=item)
    return item


def list_api_keys(google_uid: str) -> list:
    """List all API keys for a user.

    Args:
        google_uid: The user's Google UID.

    Returns:
        List of API key records (with keys partially masked).
    """
    table = DYNAMODB.Table(API_KEYS_TABLE)
    response = table.scan(
        FilterExpression="google_uid = :uid",
        ExpressionAttributeValues={":uid": google_uid},
    )
    keys = response.get("Items", [])
    # Mask the actual key values for security
    for key in keys:
        full_key = key["api_key"]
        key["api_key_preview"] = full_key[:8] + "..." + full_key[-4:]
        key["api_key_id"] = full_key[:8]
    return keys


def delete_api_key(google_uid: str, api_key: str) -> dict:
    """Delete an API key, verifying ownership.

    Args:
        google_uid: The authenticated user's Google UID.
        api_key: The full API key to delete.

    Returns:
        dict with status.
    """
    table = DYNAMODB.Table(API_KEYS_TABLE)
    # Verify ownership before deleting
    try:
        response = table.get_item(Key={"api_key": api_key})
        if "Item" not in response:
            return {"success": False, "error": "API key not found"}
        if response["Item"]["google_uid"] != google_uid:
            return {"success": False, "error": "Not authorized to delete this key"}
        table.delete_item(Key={"api_key": api_key})
        return {"success": True}
    except ClientError as e:
        return {"success": False, "error": f"Delete failed: {e}"}


# --- Lambda handlers ---


def auth_login(event, context):
    """Lambda handler for POST /api/auth/login."""
    try:
        body = json.loads(event.get("body", "{}"))
        result = login(token=body.get("token"), api_key=body.get("api_key"))
        status_code = 200 if result["success"] else 401
        return {
            "statusCode": status_code,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(result),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"success": False, "error": str(e)}),
        }


def auth_generate_key(event, context):
    """Lambda handler for POST /api/auth/keys. Requires JWT auth."""
    try:
        # Extract and verify JWT from Authorization header
        auth_header = event.get("headers", {}).get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return {
                "statusCode": 401,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Missing Authorization header"}),
            }
        claims = verify_jwt(auth_header[7:])
        google_uid = claims["sub"]

        body = json.loads(event.get("body", "{}"))
        bot_name = body.get("bot_name", "unnamed-bot")
        result = generate_api_key(google_uid, bot_name)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(result),
        }
    except ValueError as e:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }


def auth_list_keys(event, context):
    """Lambda handler for GET /api/auth/keys. Requires JWT auth."""
    try:
        auth_header = event.get("headers", {}).get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return {
                "statusCode": 401,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Missing Authorization header"}),
            }
        claims = verify_jwt(auth_header[7:])
        google_uid = claims["sub"]

        keys = list_api_keys(google_uid)
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"keys": keys}),
        }
    except ValueError as e:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }


def auth_delete_key(event, context):
    """Lambda handler for DELETE /api/auth/keys/{key_id}. Requires JWT auth."""
    try:
        auth_header = event.get("headers", {}).get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return {
                "statusCode": 401,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": "Missing Authorization header"}),
            }
        claims = verify_jwt(auth_header[7:])
        google_uid = claims["sub"]

        api_key = event.get("pathParameters", {}).get("api_key", "")
        result = delete_api_key(google_uid, api_key)
        status_code = 200 if result["success"] else 403
        return {
            "statusCode": status_code,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(result),
        }
    except ValueError as e:
        return {
            "statusCode": 401,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": str(e)}),
        }
