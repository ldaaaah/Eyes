import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import init_db, DB_PATH
from db import create_user, add_medication, add_contraindication_pair
from core.qr_security import verify_qr, generate_qr_data
from core.contraindication import check_and_warn, get_user_drug_summary


def run():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    uid = create_user("홍길동", dial_pin=1111, birth_year=1948)
    add_medication(uid, "아스피린",   drug_code="A001")
    add_medication(uid, "메트포르민", drug_code="M002")
    add_contraindication_pair("아스피린", "와파린",  severity="HIGH",
                               description="병용 시 출혈 위험 증가")
    add_contraindication_pair("메트포르민", "조영제", severity="HIGH",
                               description="신독성 위험")
    add_contraindication_pair("아스피린", "이부프로펜", severity="MEDIUM",
                               description="소화기 출혈 위험 증가")

    print("=" * 45)
    print("1. QR 해시 보안 검증")
    print("=" * 45)

    # ── 정상 QR
    payload = {
        "drug_name": "와파린정5mg",
        "drug_code": "W001",
        "patient_id": "P-2024-001",
        "issued_at": "2025-05-19",
    }
    valid_qr = generate_qr_data(payload)
    result = verify_qr(valid_qr)
    assert result["valid"] is True
    assert result["payload"]["drug_name"] == "와파린정5mg"
    print(f"✓ 정상 QR 검증 통과")
    print(f"  약품: {result['payload']['drug_name']}")
    print(f"  해시: {result['hash_in_code'][:20]}...\n")

    # ── 위변조 QR (payload 일부 수정)
    import json
    tampered = json.loads(valid_qr)
    tampered["payload"]["drug_name"] = "독약정100mg"   # 악의적 변조
    tampered_qr = json.dumps(tampered)
    result2 = verify_qr(tampered_qr)
    assert result2["valid"] is False
    print(f"✓ 위변조 QR 차단: {result2['error']}")
    print(f"  원본 해시:  {result2['hash_in_code'][:20]}...")
    print(f"  계산 해시:  {result2['hash_computed'][:20]}...\n")

    # ── 깨진 QR
    result3 = verify_qr("이건QR이아님")
    assert result3["valid"] is False
    print(f"✓ 잘못된 포맷 차단: {result3['error']}\n")

    print("=" * 45)
    print("2. 금기 약물 교차 검증")
    print("=" * 45)

    # ── HIGH 충돌 (와파린 스캔, 아스피린 복용 중)
    r = check_and_warn("와파린", uid)
    assert r["conflict_detected"] is True
    assert r["severity"] == "HIGH"
    print(f"✓ HIGH 충돌 감지: 와파린 ↔ 아스피린")
    print(f"  경고 멘트: {r['tts_warning']}\n")

    # ── MEDIUM 충돌 (이부프로펜 스캔)
    r2 = check_and_warn("이부프로펜", uid)
    assert r2["conflict_detected"] is True
    assert r2["severity"] == "MEDIUM"
    print(f"✓ MEDIUM 충돌 감지: 이부프로펜 ↔ 아스피린")
    print(f"  경고 멘트: {r2['tts_warning']}\n")

    # ── 안전한 약
    r3 = check_and_warn("타이레놀", uid)
    assert r3["conflict_detected"] is False
    assert r3["tts_warning"] == ""
    print(f"✓ 안전한 약 '타이레놀' → 경고 없음\n")

    # ── 약통 요약
    summary = get_user_drug_summary(uid)
    print(f"✓ 약통 요약 TTS: {summary}\n")

    print("=" * 45)
    print("모든 테스트 통과")


if __name__ == "__main__":
    run()
