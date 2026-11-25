"""Validate the two public values allowed in the generated student config."""
import re


def public_config(url, key):
    url = url.strip().rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", url) or not re.fullmatch(r"sb_publishable_[A-Za-z0-9_-]+", key.strip()):
        raise ValueError("請設定測試 Supabase URL 與 publishable key")
    return {"projectUrl": url, "publishableKey": key.strip()}
