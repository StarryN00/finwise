import base64
import hashlib

import pytest

from app.auth import verify_password
from test_access_control import secured


def legacy_hash(password):
    salt = bytes(range(16))
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 260000)
    enc = lambda v: base64.urlsafe_b64encode(v).decode().rstrip('=')
    return 'pbkdf2_sha256$260000$' + enc(salt) + '$' + enc(digest)


def test_migrated_password_is_upgraded_only_after_success(secured):
    encoded = legacy_hash('unchanged-production-test-password')
    db = secured.app.state.database
    with db.connect() as con:
        con.execute('UPDATE auth_users SET password_hash=? WHERE user_id=?', (encoded, 'reader'))
    assert secured.post('/api/v1/auth/login', json=dict(username='reader', password='wrong')).status_code == 401
    with db.connect() as con:
        assert con.execute('SELECT password_hash FROM auth_users WHERE user_id=?', ('reader',)).fetchone()[0] == encoded
    response = secured.post('/api/v1/auth/login', json=dict(username='reader', password='unchanged-production-test-password'))
    assert response.status_code == 200
    assert response.json()['role'] == 'viewer'
    with db.connect() as con:
        upgraded = con.execute('SELECT password_hash FROM auth_users WHERE user_id=?', ('reader',)).fetchone()[0]
    assert not upgraded.startswith('pbkdf2_sha256$')
    assert verify_password('unchanged-production-test-password', upgraded)
    assert secured.post('/api/v1/auth/login', json=dict(username='reader', password='unchanged-production-test-password')).status_code == 200


@pytest.mark.parametrize('encoded', ['broken', 'pbkdf2_sha256$999999999$AA$AA', 'pbkdf2_sha256$260000$!!$!!',
    'pbkdf2_sha256$260000$AA$AA', 'pbkdf2_sha256$260000$AA$AA$extra', 'pbkdf2_sha256$-1$AA$AA'])
def test_malformed_legacy_hashes_fail_closed(encoded):
    assert not verify_password('password', encoded)


def test_disabled_migrated_account_cannot_log_in(secured):
    with secured.app.state.database.connect() as con:
        con.execute('UPDATE auth_users SET enabled=0,password_hash=? WHERE user_id=?', (legacy_hash('unchanged-test-password'), 'reader'))
    assert secured.post('/api/v1/auth/login', json=dict(username='reader', password='unchanged-test-password')).status_code == 401
