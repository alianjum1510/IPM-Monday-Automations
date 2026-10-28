"""
monday JWTs for tests - a token like the ones monday sends, for any route.

Every feature's tests use these, so a new feature's route tests need no token
code of their own. app/conftest.py sets the matching settings.
"""
import time

import jwt

TEST_SIGNING_SECRET = 'test-signing-secret-0123456789abcdef'
TEST_BASE_URL = 'https://test-deployment.us.monday.app'


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
