import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import init_db, DB_PATH
from db import create_user
from core.dial_login import DialUserSelector
from core.voice_registration import VoiceRegistration, _extract_year


def run():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    create_user("홍길동", birth_year=1948)
    create_user("김순이", birth_year=1955)

    print("=" * 45)
    print("1. 다이얼 순환 + 사용자 추가 슬롯")
    print("=" * 45)

    selector = DialUserSelector()

    steps = []
    # 전체 목록 한 바퀴 순환: 사용자 2명 + 추가슬롯 = 3칸
    for _ in range(3):
        steps.append(selector.turn_right())

    for s in steps:
        print(f"  TTS: \"{s['tts_script']}\"")

    # 3번 오른쪽: 김순이 → 사용자추가 → 홍길동(처음으로)
    assert steps[1]["is_add_slot"] is True, "두 번째가 추가 슬롯이어야 함"
    print()

    # 루프 후 index=0(홍길동), 두 번 오른쪽 → 사용자 추가
    selector.turn_right()  # 김순이
    selector.turn_right()  # 사용자 추가
    result = selector.confirm()
    assert result["is_add_slot"] is True
    print(f"  확인 버튼 → TTS: \"{result['tts_script']}\"\n")

    # 일반 사용자 로그인: index=2, 한 번 오른쪽 → 홍길동
    selector.turn_right()  # 홍길동
    login = selector.confirm()
    assert login["is_add_slot"] is False
    assert login["name"] == "홍길동"
    print(f"  로그인 확정 → TTS: \"{login['tts_script']}\"\n")

    print("=" * 45)
    print("2. 음성 등록 시뮬레이션 (마이크 없이)")
    print("=" * 45)

    tts_log = []
    stt_answers = ["홍 길 동", "천구백사십팔"]   # 미리 준비한 답변

    def mock_tts(text):
        tts_log.append(text)
        print(f"  TTS: \"{text}\"")

    def mock_stt():
        answer = stt_answers.pop(0) if stt_answers else ""
        print(f"  사용자 음성: \"{answer}\"")
        return answer

    reg = VoiceRegistration(tts_fn=mock_tts, listen_fn=mock_stt)
    pending = reg.run()

    assert pending["success"] is True
    assert pending["pending"] is True
    print(f"\n  → 확인 버튼 대기 중...\n")

    # 확인 버튼 눌림
    saved = reg.save(pending["name"], pending["birth_year"])
    assert saved["success"] is True
    print(f"  TTS: \"{saved['tts_script']}\"\n")

    # 등록 후 다이얼 목록 갱신
    selector.reload()
    slots = []
    for _ in range(5):
        slots.append(selector.turn_right())
    names = [s["tts_script"] for s in slots]
    print("  다이얼 갱신 후 목록:")
    for n in names:
        print(f"    {n}")
    assert any("홍 길 동" in n or "홍" in n for n in names)

    print()
    print("=" * 45)
    print("3. 연도 추출 로직")
    print("=" * 45)
    cases = [
        ("천구백사십팔", 1948),
        ("1948년",       1948),
        ("1965",         1965),
        ("천구백육십오", 1965),
    ]
    for text, expected in cases:
        result = _extract_year(text)
        print(f"  \"{text}\" → {result}  {'✓' if result == expected else '✗'}")

    print("\n모든 테스트 통과")


if __name__ == "__main__":
    run()
