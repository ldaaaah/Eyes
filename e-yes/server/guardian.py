"""
하우스 약사 — 보호자 앱 서버 전송 모듈

스캔 완료 후 로그를 JSON으로 POST 전송.
실패 시 DB에 미전송 상태로 보관 → 재연결되면 자동 재전송.
"""

import json
import requests
from datetime import datetime
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"
with open(_CONFIG_PATH, encoding="utf-8") as f:
    _SERVER_URL = json.load(f)["server"]["guardian_app_url"]

TIMEOUT_SEC = 8


def send_scan_log(log_id: int, user_name: str, scan_time: str,
                  drug_name: str, recognition_mode: str,
                  conflict_detected: bool, conflict_details: list,
                  tts_script: str) -> bool:
    """
    스캔 로그 1건을 보호자 앱 서버로 POST 전송.
    성공 시 DB의 sent_to_server 플래그 업데이트.

    Returns:
        True = 전송 성공, False = 실패 (나중에 재전송 예약)
    """
    payload = {
        "log_id":            log_id,
        "user_name":         user_name,
        "scan_time":         scan_time,
        "drug_name":         drug_name,
        "recognition_mode":  recognition_mode,
        "conflict_detected": conflict_detected,
        "conflict_details":  conflict_details,
        "tts_script":        tts_script,
        "device_id":         "house-pharmacist-001",
        "sent_at":           datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    try:
        resp = requests.post(
            _SERVER_URL,
            json=payload,
            timeout=TIMEOUT_SEC,
            headers={"Content-Type": "application/json"}
        )
        resp.raise_for_status()

        from db import mark_log_sent
        mark_log_sent(log_id, server_response=str(resp.status_code))
        print(f"[SERVER] 전송 성공: log_id={log_id}, status={resp.status_code}")
        return True

    except requests.exceptions.ConnectionError:
        print(f"[SERVER] 서버 연결 실패: 나중에 재전송 예약 (log_id={log_id})")
    except requests.exceptions.Timeout:
        print(f"[SERVER] 전송 타임아웃 (log_id={log_id})")
    except Exception as e:
        print(f"[SERVER] 전송 오류: {e}")

    return False


def retry_unsent_logs() -> int:
    """
    미전송 로그 전부 재전송 시도.
    (WiFi 재연결 시 또는 주기적으로 호출)
    Returns: 성공적으로 전송된 건수
    """
    from db import get_unsent_logs
    logs   = get_unsent_logs()
    if not logs:
        return 0

    print(f"[SERVER] 미전송 로그 {len(logs)}건 재전송 시도")
    success = 0
    for log in logs:
        ok = send_scan_log(
            log_id            = log["log_id"],
            user_name         = log.get("user_name", "알 수 없음"),
            scan_time         = log["scan_time"],
            drug_name         = log.get("recognized_drug", ""),
            recognition_mode  = log["recognition_mode"],
            conflict_detected = bool(log["conflict_detected"]),
            conflict_details  = json.loads(log.get("conflict_details") or "[]"),
            tts_script        = log.get("tts_script", ""),
        )
        if ok:
            success += 1

    print(f"[SERVER] 재전송 완료: {success}/{len(logs)}건 성공")
    return success
