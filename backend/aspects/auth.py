import os
import json
import time
import boto3
import jwt
import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from botocore.exceptions import ClientError

# Firebase Admin SDK initialization (singleton)
FIREBASE_APP = None
FIREBASE_CREDS_PATH = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "/tmp/firebase-service-account.json")
def _init_firebase():
    global FIREBASE_APP
    if not FIREBASE_APP:
        cred = credentials.Certificate(FIREBASE_CREDS_PATH)
        FIREBASE_APP = firebase_admin.initialize_app(cred, name="gameserver")

# DynamoDB setup
DYNAMODB = boto3.resource("dynamodb")
USERS_TABLE = os.environ.get("USERS_TABLE", "users-dev")
TABLE = DYNAMODB.Table(USERS_TABLE)

# JWT secret (use AWS SecretsManager/param store in prod)
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")

def verify_firebase_token(id_token):
    """Verify Firebase ID token, return claims."""
    _init_firebase()
    try:
        decoded = firebase_auth.verify_id_token(id_token, app=FIREBASE_APP)
        return {
            'uid': decoded['uid'],
            'email': decoded.get('email'),
            'name': decoded.get('name'),
            'picture': decoded.get('picture'),
        }
    except Exception as e:
        raise ValueError(f"Invalid token: {e}")

def get_or_create_user(firebase_uid, email, display_name, photo_url):
    """Get or create user record in DynamoDB."""
    now = int(time.time())
    key = {'firebase_uid': firebase_uid}
    try:
        resp = TABLE.get_item(Key=key)
        user = resp.get('Item')
        if user:
            # Update last_login
            TABLE.update_item(
                Key=key,
                UpdateExpression="set last_login = :ll",
                ExpressionAttributeValues={":ll": now}
            )
            return user
        else:
            # User does not exist. Create new.
            from .player import get_or_create_player_entity
            player_entity = get_or_create_player_entity(firebase_uid)
            new_user = {
                'firebase_uid': firebase_uid,
                'email': email,
                'display_name': display_name,
                'photo_url': photo_url,
                'entity_uuid': player_entity['uuid'],
                'entity_aspect': player_entity['aspect'],
                'created_at': now,
                'last_login': now
            }
            TABLE.put_item(Item=new_user)
            return new_user
    except ClientError as ce:
        raise RuntimeError(f"DynamoDB error: {ce}")

def create_jwt(payload, expiration=3600):
    """Create internal JWT for WebSocket auth."""
    now = int(time.time())
    payload = {
        **payload,
        'iat': now,
        'exp': now + expiration,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def auth_login(event, context):
    """Lambda handler for POST /api/auth/login."""
    # Extract Authorization header
    headers = event.get('headers', {})
    auth_header = headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return {'statusCode': 401, 'body': json.dumps({'error': 'Missing or invalid Authorization header'})}
    id_token = auth_header.replace('Bearer ', '')
    try:
        firebase_user = verify_firebase_token(id_token)
    except Exception as e:
        return {'statusCode': 401, 'body': json.dumps({'error': str(e)})}
    # Create/get user and entity
    user = get_or_create_user(
        firebase_uid=firebase_user['uid'],
        email=firebase_user.get('email'),
        display_name=firebase_user.get('name'),
        photo_url=firebase_user.get('picture'),
    )
    internal_token = create_jwt({
        'sub': user['firebase_uid'],
        'email': user['email'],
        'entity_uuid': user['entity_uuid'],
        'entity_aspect': user['entity_aspect'],
    })
    resp = {
        'token': internal_token,
        'entity': {
            'uuid': user['entity_uuid'],
            'aspect': user['entity_aspect'],
            # Optional: add location if needed
        },
    }
    return { 'statusCode': 200, 'body': json.dumps(resp) }
