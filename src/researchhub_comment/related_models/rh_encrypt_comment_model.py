from cryptography.fernet import Fernet
import base64
from django.db import models

class EncryptComment(models.Model):
    key = 'encrypt_key'
    cipher_suite = None
    encryption_key = models.CharField(max_length=44)

    def __init__(self):
        self.cipher_suite = Fernet(base64.urlsafe_b64encode(self.key.encode('utf-8')))

    def encrypt(self, data):
        encrypted_data = self.cipher_suite.encrypt(data.encode('utf-8'))
        return encrypted_data.decode('utf-8')

    def decrypt(self, encrypted_data):
        decrypted_data = self.cipher_suite.decrypt(encrypted_data.encode('utf-8'))
        return decrypted_data.decode('utf-8')