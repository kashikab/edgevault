import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class VaultCrypto:
    def __init__(self, key_path: str = "camera_key.bin"):
        self.key_path = key_path
        self.key = self._load_or_generate_key()

    def _load_or_generate_key(self) -> bytes:
        """Loads the camera's master private key, or creates one if it doesn't exist."""
        if os.path.exists(self.key_path):
            with open(self.key_path, "rb") as f:
                return f.read()
        else:
            new_key = AESGCM.generate_key(bit_length=256)
            with open(self.key_path, "wb") as f:
                f.write(new_key)
            return new_key

    def encrypt(self, data: bytes) -> bytes:
        """Scrambles the data and attaches a GCM tamper-evident seal."""
        aesgcm = AESGCM(self.key)
        nonce = os.urandom(12)  # 12-byte standard GCM nonce
        ciphertext = aesgcm.encrypt(nonce, data, associated_data=None)
        return nonce + ciphertext

    def decrypt(self, encrypted_payload: bytes) -> bytes:
        """Verifies the seal and unscrambles the data back to the original bytes."""
        aesgcm = AESGCM(self.key)
        nonce = encrypted_payload[:12]
        ciphertext = encrypted_payload[12:]
        return aesgcm.decrypt(nonce, ciphertext, associated_data=None)