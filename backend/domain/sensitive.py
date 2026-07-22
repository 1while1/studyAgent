"""敏感文件判定（纯函数，零 IO）：.env/密钥/证书类文件禁止被读取、索引、解析。

供 code_browser（代码浏览/AI READ）与 materials_service（资料库扫描/解析）
共用，防密钥经界面或 LLM 注入外发。
"""

from __future__ import annotations

from pathlib import Path

SENSITIVE_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials",
}
SENSITIVE_EXTS = {".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".secret"}


def is_sensitive(name: str) -> bool:
    low = name.lower()
    if low in SENSITIVE_NAMES or low.startswith(".env."):
        return True
    return Path(low).suffix in SENSITIVE_EXTS
