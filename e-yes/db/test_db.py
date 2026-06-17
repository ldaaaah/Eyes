"""DB 스키마 & DAO 동작 검증 테스트"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import init_db, DB_PATH
from db import (
    get_user_by_pin, create_user,
    get_user_medications, add_medication,
    get_cached_drug_info, upsert_drug_cache,
    check_contraindications, add_contraindication_pair,
    insert_scan_log, mark_log_sent, get_unsent_logs,
)

def run():
    # 기존 테스트 DB 초기화
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    print("✓ DB 초기화 완료\n")

    # ── 사용자 ──────────────────────────────────
    uid = create_user("홍길동", dial_pin=1111, birth_year=1948)
    print(f"✓ 사용자 생성: user_id={uid}")

    user = get_user_by_pin(1111)
    assert user is not None and user["name"] == "홍길동"
    print(f"✓ PIN 로그인: {user['name']}\n")

    wrong = get_user_by_pin(9999)
    assert wrong is None
    print("✓ 잘못된 PIN 거부\n")

    # ── 장기복용 약물 ────────────────────────────
    add_medication(uid, "아스피린", drug_code="A001",
                   dosage="100mg", frequency="1일 1회 아침 식후",
                   start_date="2024-01-01")
    add_medication(uid, "메트포르민", drug_code="M002",
                   dosage="500mg", frequency="1일 2회 식후",
                   start_date="2023-06-01")
    meds = get_user_medications(uid)
    assert len(meds) == 2
    print(f"✓ 장기복용 약물 {len(meds)}건 등록: {[m['drug_name'] for m in meds]}\n")

    # ── 금기 약물 쌍 등록 ────────────────────────
    add_contraindication_pair(
        "아스피린", "와파린", severity="HIGH",
        description="병용 시 출혈 위험 증가",
        source="MANUAL"
    )
    add_contraindication_pair(
        "메트포르민", "조영제", severity="HIGH",
        description="신독성 위험, 검사 전 48시간 중단 필요",
        source="MANUAL"
    )
    print("✓ 금기 약물 쌍 2건 등록\n")

    # ── 금기 교차 검증 ────────────────────────────
    # 사용자가 아스피린 복용 중 → 와파린 스캔 → 충돌 감지
    conflicts = check_contraindications("와파린", uid)
    assert len(conflicts) == 1 and conflicts[0]["severity"] == "HIGH"
    print(f"✓ 금기 충돌 감지: '와파린' ↔ '{conflicts[0]['drug_name_a']}' [{conflicts[0]['severity']}]")
    print(f"  사유: {conflicts[0]['description']}\n")

    # 안전한 약 → 충돌 없음
    safe = check_contraindications("타이레놀", uid)
    assert len(safe) == 0
    print("✓ 안전한 약 '타이레놀' → 충돌 없음\n")

    # ── API 캐시 ─────────────────────────────────
    upsert_drug_cache(
        keyword="타이레놀",
        drug_name="아세트아미노펜(타이레놀정500mg)",
        drug_code="T999",
        efficacy="두통, 치통, 발열 완화",
        dosage_info="성인 1회 1~2정, 1일 3~4회",
        precautions="간 질환자 주의, 음주 후 복용 금지",
        contraindication={},
        full_response={"itemName": "타이레놀정500mg"}
    )
    cached = get_cached_drug_info("타이레놀")
    assert cached is not None and cached["drug_name"] == "아세트아미노펜(타이레놀정500mg)"
    print(f"✓ API 캐시 저장/조회: {cached['drug_name']}\n")

    miss = get_cached_drug_info("없는약")
    assert miss is None
    print("✓ 캐시 미스 → None 반환\n")

    # ── 스캔 로그 ─────────────────────────────────
    log_id = insert_scan_log(
        user_id=uid,
        recognition_mode="OCR",
        raw_text="타이레놀정500mg 1일3회",
        recognized_drug="타이레놀",
        drug_code="T999",
        conflict_detected=False,
        api_fetch_success=True,
        tts_script="타이레놀 500밀리그램입니다. 두통과 발열 완화에 사용합니다.",
    )
    print(f"✓ 스캔 로그 저장: log_id={log_id}")

    unsent = get_unsent_logs()
    assert len(unsent) >= 1
    print(f"✓ 미전송 로그 {len(unsent)}건 조회\n")

    mark_log_sent(log_id, server_response="200 OK")
    unsent_after = get_unsent_logs()
    assert len(unsent_after) == len(unsent) - 1
    print(f"✓ 전송 완료 마킹 후 미전송 {len(unsent_after)}건\n")

    print("=" * 40)
    print("모든 테스트 통과")

if __name__ == "__main__":
    run()
