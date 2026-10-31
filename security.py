import hashlib
import hmac
import secrets
import time
from threading import Lock

ITERATIONS = 600_000

def hash_password(password):
    if not isinstance(password,str) or not 12 <= len(password) <= 128:
        raise ValueError('La contraseña debe tener entre 12 y 128 caracteres.')
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'

def verify_password(password, encoded):
    try:
        algorithm, count, salt, digest = encoded.split('$')
        if algorithm != 'pbkdf2_sha256' or not 100_000 <= int(count) <= 2_000_000:
            return False
        actual = hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),int(count)).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError,AttributeError):
        return False

class Sessions:
    def __init__(self):
        self.items = {}
        self.lock = Lock()

    def create(self, user_id, credential=None):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.lock:
            self.items = {k:v for k,v in self.items.items() if v['expires'] > time.time()}
            self.items[token] = dict(user_id=user_id,csrf=csrf,expires=time.time()+3600,credential=credential)
        return token,csrf

    def get(self, token):
        with self.lock:
            value = self.items.get(token)
            if not value or value['expires'] <= time.time():
                self.items.pop(token,None)
                return None
            return dict(value)

    def remove(self, token):
        with self.lock:
            self.items.pop(token,None)

    def revoke_user(self, user_id):
        with self.lock:
            self.items = {k:v for k,v in self.items.items() if v['user_id'] != user_id}
