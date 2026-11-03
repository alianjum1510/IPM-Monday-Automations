"""
monday tokens for tests - like the ones monday sends.

  monday_auth(path)   an Automation Block's JWT for `path` (Signing Secret)
  session_auth()      a View page's session token (Client Secret)

Every feature's tests use these, so a new feature's route tests need no token
code of their own. app/conftest.py sets the matching settings.
"""
import time

import jwt

TEST_SIGNING_SECRET = 'test-signing-secret-0123456789abcdef'
TEST_BASE_URL = 'https://test-deployment.us.monday.app'
TEST_CLIENT_SECRET = 'test-client-secret-0123456789abcdef'
TEST_APP_ID = 11727119


def monday_token(path='/', secret=TEST_SIGNING_SECRET, base_url=TEST_BASE_URL, expires_in=300, **claims):
    """A token for `path` on the test deployment; claims=... overrides or removes (None) any claim."""
    now = int(time.time())
    payload = {
        'accountId': 1,
        'userId': 2,
        'aud': base_url.rstrip('/') + path,
        'iat': now,
        'exp': now + expires_in,
        'shortLivedToken': 'short-lived-token-never-logged',
        **claims,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    return jwt.encode(payload, secret, algorithm='HS256')


def monday_auth(path='/', **kwargs):
    return {'Authorization': monday_token(path, **kwargs)}


def session_token(secret=TEST_CLIENT_SECRET, app_id=TEST_APP_ID, expires_in=300, user_id=2, **claims):
    """A View page's session token; claims=... overrides or removes (None) any claim, dat=... replaces dat."""
    now = int(time.time())
    payload = {
        'dat': {'client_id': 'test-client-id', 'user_id': user_id, 'account_id': 1, 'app_id': app_id,
                'app_version_id': 1, 'install_id': 1, 'is_admin': True, 'is_view_only': False, 'is_guest': False},
        'iat': now,
        'exp': now + expires_in,
        **claims,
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    return jwt.encode(payload, secret, algorithm='HS256')


def session_auth(**kwargs):
    return {'Authorization': session_token(**kwargs)}
