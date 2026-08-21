"""钉钉事件订阅回调加解密工具。

钉钉回调加密规范：
- AES-256-CBC，PKCS7 填充
- 密钥：AES Key（43 位 Base64）解码 → 32 字节
- IV：密钥的前 16 字节
- 加密体格式：random(16B) + msg_len(4B 大端) + msg + corp_id
- 签名：SHA1(sort(timestamp, nonce, token, encrypted))
"""

import base64
import hashlib
import os
import secrets
import struct
import time

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7


class DingCallbackCrypto:
    """钉钉回调加解密器。"""

    def __init__(self, token: str, aes_key: str, corp_id: str = ""):
        if not token or not aes_key:
            raise ValueError("token 和 aes_key 不能为空")
        self.token = token
        self.corp_id = corp_id
        # 43 位 Base64 → 32 字节 AES key
        self.aes_key = base64.b64decode(aes_key + "=")
        if len(self.aes_key) != 32:
            raise ValueError(f"aes_key 解码后应为 32 字节，实际 {len(self.aes_key)}")

    def _pkcs7_unpad(self, data: bytes) -> bytes:
        unpadder = PKCS7(128).unpadder()
        return unpadder.update(data) + unpadder.finalize()

    def _pkcs7_pad(self, data: bytes) -> bytes:
        padder = PKCS7(128).padder()
        return padder.update(data) + padder.finalize()

    def _decrypt(self, encrypted: bytes) -> bytes:
        """AES-256-CBC 解密，IV = key 前 16 字节。"""
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.aes_key[:16]))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(encrypted) + decryptor.finalize()
        return self._pkcs7_unpad(decrypted)

    def _encrypt(self, plain: bytes) -> bytes:
        """AES-256-CBC 加密，IV = key 前 16 字节。"""
        padded = self._pkcs7_pad(plain)
        cipher = Cipher(algorithms.AES(self.aes_key), modes.CBC(self.aes_key[:16]))
        encryptor = cipher.encryptor()
        return encryptor.update(padded) + encryptor.finalize()

    def get_signature(self, timestamp: str, nonce: str, encrypted: str) -> str:
        """计算签名：SHA1(sort(timestamp, nonce, token, encrypted))。"""
        raw = "".join(sorted([timestamp, nonce, self.token, encrypted]))
        return hashlib.sha1(raw.encode()).hexdigest()

    def decrypt_msg(self, encrypted: str) -> str:
        """解密回调消息 → 返回明文字符串。"""
        raw = self._decrypt(base64.b64decode(encrypted))
        # 格式：random(16) + msg_len(4) + msg + corp_id
        msg_len = struct.unpack("!I", raw[16:20])[0]
        msg = raw[20:20 + msg_len].decode("utf-8")
        received_corp_id = raw[20 + msg_len:].decode("utf-8")
        if self.corp_id and received_corp_id != self.corp_id:
            raise ValueError(f"corp_id 不匹配: 期望 {self.corp_id}, 收到 {received_corp_id}")
        return msg

    def encrypt_msg(self, msg: str) -> str:
        """加密消息 → 返回 Base64 密文。"""
        # 16 字节随机 + 4 字节长度 + 消息 + corp_id
        rand = os.urandom(16)
        msg_bytes = msg.encode("utf-8")
        length = struct.pack("!I", len(msg_bytes))
        plain = rand + length + msg_bytes + self.corp_id.encode("utf-8")
        encrypted = self._encrypt(plain)
        return base64.b64encode(encrypted).decode()

    def get_encrypted_map(self, msg: str) -> dict:
        """返回给钉钉的加密响应：{msg_signature, timestamp, nonce, encrypt}。

        用于 URL 校验（echostr 解密后加密返回）和回复消息。
        """
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(8)
        encrypt = self.encrypt_msg(msg)
        signature = self.get_signature(timestamp, nonce, encrypt)
        return {
            "msg_signature": signature,
            "timeStamp": timestamp,
            "nonce": nonce,
            "encrypt": encrypt,
        }