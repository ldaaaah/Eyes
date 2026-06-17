"""보호자 앱 전송 테스트 — Mock 서버로 검증"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from db.schema import init_db, DB_PATH
from db import create_user, add_medication, insert_scan_log, get_unsent_logs
from server.guardian import send_scan_log, retry_unsent_logs


def run():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    uid = create_user("홍길동", birth_year=1948)
    log_id = insert_scan_log(
        user_id=uid, recognition_mode="OCR",
        raw_text="복합위장약", recognized_drug="복합위장약",
        api_fetch_success=True,
        tts_script="복합위장약입니다. 위통, 속쓰림에 복용하세요.",
        conflict_detected=False,
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = lambda: None

    print("=" * 45)
    print("1. 전송 성공 케이스")
    print("=" * 45)
    with patch("requests.post", return_value=mock_resp) as mock_post:
        ok = send_scan_log(
            log_id=log_id, user_name="홍길동",
            scan_time="2026-05-19 14:30:00",
            drug_name="복합위장약", recognition_mode="OCR",
            conflict_detected=False, conflict_details=[],
            tts_script="복합위장약입니다."
        )
        assert ok is True
        sent_payload = mock_post.call_args[1]["json"]
        print(f"  ✓ 전송 성공")
        print(f"  전송 데이터 미리보기:")
        for k, v in sent_payload.items():
            print(f"    {k}: {v}")

    print()
    print("=" * 45)
    print("2. 서버 오프라인 → 미전송 보관")
    print("=" * 45)

    log_id2 = insert_scan_log(
        user_id=uid, recognition_mode="QR",
        raw_text="QR데이터", recognized_drug="와파린",
        api_fetch_success=True,
        tts_script="와파린입니다.",
    )
    with patch("requests.post", side_effect=Exception("연결 거부")):
        ok2 = send_scan_log(
            log_id=log_id2, user_name="홍길동",
            scan_time="2026-05-19 14:31:00",
            drug_name="와파린", recognition_mode="QR",
            conflict_detected=False, conflict_details=[],
            tts_script="와파린입니다."
        )
        assert ok2 is False
        unsent = get_unsent_logs()
        assert len(unsent) == 1
        print(f"  ✓ 전송 실패 → DB 미전송 보관 ({len(unsent)}건)")

    print()
    print("=" * 45)
    print("3. WiFi 복구 후 자동 재전송")
    print("=" * 45)
    with patch("requests.post", return_value=mock_resp):
        count = retry_unsent_logs()
        assert count == 1
        print(f"  ✓ 재전송 성공: {count}건")
        unsent_after = get_unsent_logs()
        assert len(unsent_after) == 0
        print(f"  ✓ 미전송 대기열 비워짐")

    print()
    print("모든 테스트 통과")


if __name__ == "__main__":
    run()
