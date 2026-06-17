"""
하우스 약사 — 금기 약물 교차 검증 모듈

스캔된 약이 현재 로그인 사용자의 장기복용 약물과 충돌하는지 검사.
DB의 check_contraindications() 결과를 받아 TTS 경고 스크립트까지 생성.
"""

from db import check_contraindications, get_user_medications

# 중증도별 TTS 경고 문구
_SEVERITY_SCRIPT = {
    "HIGH":   "경고. 위험한 약물 조합이 감지되었습니다.",
    "MEDIUM": "주의. 함께 복용 시 주의가 필요한 약물이 있습니다.",
    "LOW":    "참고. 복용 중인 약과 확인이 필요한 조합이 있습니다.",
}


def check_and_warn(scanned_drug: str, user_id: int) -> dict:
    """
    스캔된 약과 사용자 약통을 교차 검증하고 TTS 경고 스크립트 반환.

    Returns:
        {
            "conflict_detected": bool,
            "severity":          str | None,   # 가장 높은 중증도
            "conflicts":         list[dict],   # 충돌 쌍 목록
            "tts_warning":       str,          # TTS로 읽을 경고문 (충돌 없으면 빈 문자열)
        }
    """
    conflicts = check_contraindications(scanned_drug, user_id)

    if not conflicts:
        return {
            "conflict_detected": False,
            "severity":          None,
            "conflicts":         [],
            "tts_warning":       "",
        }

    top_severity = conflicts[0]["severity"]   # 이미 severity DESC 정렬됨
    warning_lines = [_SEVERITY_SCRIPT[top_severity]]

    for c in conflicts:
        # 스캔된 약과 충돌하는 상대 약 이름 추출
        other = c["drug_name_b"] if c["drug_name_a"] == scanned_drug else c["drug_name_a"]
        warning_lines.append(
            f"현재 복용 중인 {other}와 함께 드시면 {c['description']}"
        )

    warning_lines.append("복용 전에 반드시 담당 의사 또는 약사에게 문의하시기 바랍니다.")

    return {
        "conflict_detected": True,
        "severity":          top_severity,
        "conflicts":         conflicts,
        "tts_warning":       " ".join(warning_lines),
    }


def get_user_drug_summary(user_id: int) -> str:
    """사용자 약통 목록을 TTS용 문장으로 반환"""
    meds = get_user_medications(user_id)
    if not meds:
        return "등록된 복용 약물이 없습니다."
    names = [m["drug_name"] for m in meds]
    return f"현재 {len(names)}가지 약물이 등록되어 있습니다. " + ", ".join(names) + "."
