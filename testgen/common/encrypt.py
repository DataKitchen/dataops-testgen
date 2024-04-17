import base64

import streamlit_authenticator as stauth
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Random import get_random_bytes

from testgen import settings


def EncryptText(strText):
    block_size = 16

    def pad(s):
        return s + (block_size - len(s) % block_size) * chr(block_size - len(s) % block_size)

    # Generate a random salt
    salt = settings.APP_ENCRYPTION_SALT.encode("ascii")
    strPassword = settings.APP_ENCRYPTION_SECRET.encode("ascii")

    # Derive the key using PBKDF2
    kdf = PBKDF2(strPassword, salt, 64, 1000)
    private_key = kdf[:32]

    # Initialize the cipher
    strText = pad(strText)
    strText = bytes(strText, "utf-8")
    iv = get_random_bytes(AES.block_size)
    cipher = AES.new(private_key, AES.MODE_CBC, iv)

    # Perform encryption
    encrypted_text = base64.b64encode(iv + cipher.encrypt(strText))
    return encrypted_text.decode("UTF-8")


def DecryptText(baEncrypted):
    def unpad(s):
        return s[: -ord(s[len(s) - 1 :])]

    # Calc Private Key from Password
    salt = settings.APP_ENCRYPTION_SALT.encode("ascii")
    strPassword = settings.APP_ENCRYPTION_SECRET.encode("ascii")
    kdf = PBKDF2(strPassword, salt, 64, 1000)
    private_key = kdf[:32]

    baEncrypted = base64.b64decode(baEncrypted)
    iv = baEncrypted[:16]
    cipher = AES.new(private_key, AES.MODE_CBC, iv)

    return bytes.decode(unpad(cipher.decrypt(baEncrypted[16:])))


def encrypt_ui_password(plain_password):
    hashed_passwords = stauth.Hasher([plain_password]).generate()
    return hashed_passwords.pop()
