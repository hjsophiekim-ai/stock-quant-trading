"""KIS JSON 로그용 마스킹."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

_SENSITIVE_KEY_SUBSTR = (
    "cano",
    "appkey",
    "appsecret",
    "app_key",
    "app_secret",
    "token",
    "authorization",
    "hash",
    "hashkey",
    "pwd",
    "password",
)


def mask_kis_payload_for_log(obj: Any, *, mask: str = "***") -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if any(s in lk for s in _SENSITIVE_KEY_SUBSTR):
                out[k] = mask
            else:
                out[k] = mask_kis_payload_for_log(v, mask=mask)
        return out
    if isinstance(obj, list):
        return [mask_kis_payload_for_log(x, mask=mask) for x in obj]
    if isinstance(obj, str) and re.fullmatch(r"\d{8,12}", obj):
        return mask if len(obj) >= 8 else obj
    return copy.deepcopy(obj)


def format_masked_payload_json(payload: Any) -> str:
    try:
        return json.dumps(mask_kis_payload_for_log(payload), ensure_ascii=False, default=str)[:8000]
    except (TypeError, ValueError):
        return str(payload)[:2000]
