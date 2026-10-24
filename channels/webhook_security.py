"""Bounded decoding and freshness checks shared by signed platform callbacks."""
import time
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


def fresh_timestamp(value, *, scale=1, max_age=300):
    try:
        timestamp = int(value) / scale
    except (ValueError, TypeError, OverflowError):
        raise PermissionError("Invalid callback timestamp") from None
    if abs(time.time() - timestamp) > max_age:
        raise PermissionError("Expired callback timestamp")


def decrypt_cbc(ciphertext, key, iv, *, padding_bits=128):
    try:
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = PKCS7(padding_bits).unpadder()
        return unpadder.update(plaintext) + unpadder.finalize()
    except ValueError:
        raise PermissionError("Invalid encrypted callback") from None


def xml_fields(body):
    # These protocols require only flat UTF-8 XML; reject entity/DTD expansion.
    text = body.decode("utf-8")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("XML declarations are not supported")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise ValueError("Invalid callback XML") from None
    if root.tag != "xml" or any(len(child) for child in root):
        raise ValueError("Invalid callback XML structure")
    fields = {child.tag: child.text or "" for child in root}
    if len(fields) != len(root):
        raise ValueError("Duplicate callback fields")
    return fields
