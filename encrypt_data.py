#!/usr/bin/env python3
"""Cifra data.json con la clave compartida para publicarlo en un sitio estático.

Formato de data.enc: salt(16) | iv(12) | AES-256-GCM(ciphertext+tag).
La clave se deriva con PBKDF2-HMAC-SHA256 (200.000 iteraciones). salt e iv se derivan del
contenido, así el archivo no cambia si los datos no cambian (evita commits vacíos).
Uso: encrypt_data.py data.json data.enc .password
"""
import hashlib, sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITER = 200_000
src, dst, pwfile = sys.argv[1], sys.argv[2], sys.argv[3]
plain = open(src, 'rb').read()
password = open(pwfile, encoding='utf-8').read().strip().encode('utf-8')
salt = hashlib.sha256(b'salt' + plain).digest()[:16]
iv = hashlib.sha256(b'iv' + salt + plain).digest()[:12]
key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(password)
ct = AESGCM(key).encrypt(iv, plain, None)
open(dst, 'wb').write(salt + iv + ct)
print(f'{dst}: {len(plain):,} bytes -> {len(salt)+len(iv)+len(ct):,} bytes')
