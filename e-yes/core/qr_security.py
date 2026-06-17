"""
하우스 약사 — QR 코드 보안 검증 모듈

처방전 QR 위변조 방지:
  QR 데이터 구조: {"payload": {...}, "hash": "hmac-sha256값"}
  발급 기관이 HMAC-SHA256으로 서명 → 장치가 동일 키로 재계산 후 비교
"""

import hmac
import hashlib
import json
from pathlib import Path

# 공유 비밀키 — 발급 기관(병원/약국)과 장치가 동일한 값을 가져야 함
# 실제 배포 시 config.json 또는 환경변수로 관리
_CONFIG_PATH = Path(__file__).parent.parent / "config.json"

def _load_secret_key() -> bytes:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        key = cfg.get("qr_secret_key", "house-pharmacist-default-secret")
        return key.encode("utf-8")
    except Exception:
        return b"house-pharmacist-default-secret"


def verify_qr(qr_raw: str) -> dict:
    """
    QR 스캔 원본 문자열을 검증.

    Returns:
        {
            "valid":    bool,       # 해시 검증 통과 여부
            "payload":  dict|None,  # 검증 통과 시 처방 데이터
            "hash_in_code":     str,  # QR에 들어있던 해시
            "hash_computed":    str,  # 장치가 계산한 해시
            "error":    str|None    # 실패 사유
        }
    """
    try:
        data = json.loads(qr_raw)
    except json.JSONDecodeError:
        return _fail("QR 데이터가 JSON 형식이 아닙니다.", "", "")

    if "payload" not in data or "hash" not in data:
        return _fail("QR 필수 필드(payload, hash) 누락", "", "")

    payload     = data["payload"]
    hash_in_qr  = data["hash"]
    computed    = _compute_hash(payload)

    if hmac.compare_digest(hash_in_qr, computed):
        return {
            "valid":         True,
            "payload":       payload,
            "hash_in_code":  hash_in_qr,
            "hash_computed": computed,
            "error":         None,
        }
    else:
        return {
            "valid":         False,
            "payload":       None,
            "hash_in_code":  hash_in_qr,
            "hash_computed": computed,
            "error":         "해시 불일치 — 위변조 의심",
        }


def generate_qr_data(payload: dict) -> str:
    """
    테스트/발급기관용: payload로 올바른 QR JSON 문자열 생성.
    실제 장치에서는 이 함수를 쓰지 않음 (발급 기관이 생성)
    """
    h = _compute_hash(payload)
    return json.dumps({"payload": payload, "hash": h}, ensure_ascii=False)


def _compute_hash(payload: dict) -> str:
    """payload dict를 정렬된 JSON 문자열로 직렬화 후 HMAC-SHA256 계산"""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        _load_secret_key(),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def _fail(error: str, hash_in: str, hash_comp: str) -> dict:
    return {
        "valid":         False,
        "payload":       None,
        "hash_in_code":  hash_in,
        "hash_computed": hash_comp,
        "error":         error,
    }
