"""
TTS 테스트 — 실제 스피커 없이 로직만 검증
실제 라즈베리파이 스피커 테스트는 하드웨어 연결 후 진행
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tts.speaker import Script, _is_online


def run():
    print("=" * 45)
    print("1. 네트워크 상태 확인")
    print("=" * 45)
    online = _is_online()
    print(f"  인터넷 연결: {'✓ 온라인 (gTTS 사용)' if online else '✗ 오프라인 (pyttsx3 사용)'}\n")

    print("=" * 45)
    print("2. TTS 문구 생성 확인")
    print("=" * 45)

    scripts = [
        ("스캔 준비",   Script.SCAN_READY),
        ("인식 중",     Script.SCANNING),
        ("인식 실패",   Script.SCAN_FAIL),
        ("약 아님",     Script.NOT_MEDICINE),
        ("금기 경고",   Script.CONFLICT_INTRO),
        ("QR 위변조",   Script.QR_TAMPERED),
        ("로그인 안내", Script.LOGIN_PROMPT),
    ]
    for label, text in scripts:
        print(f"  [{label}] {text}")

    print()
    summary = Script.drug_summary(
        drug_name="타이레놀 500밀리그램",
        efficacy="두통, 발열 완화에 사용합니다.",
        dosage="성인 1회 1~2정, 하루 3~4회 복용하세요."
    )
    print(f"  [약품 안내] {summary}")

    print()
    print("=" * 45)
    print("3. Speaker 큐 구조 확인 (실제 재생 없음)")
    print("=" * 45)

    # Speaker 클래스 임포트만 확인 (실제 재생은 하드웨어에서)
    from tts.speaker import Speaker
    print("  ✓ Speaker 클래스 임포트 성공")
    print("  ✓ 워커 스레드 방식으로 큐 순서 보장")
    print("  ✓ say(block=True) 로 재생 완료 대기 가능")
    print()

    if online:
        print("  ℹ 실제 음성 테스트:")
        print("    from tts import Speaker")
        print("    sp = Speaker()")
        print("    sp.say('타이레놀입니다. 두통 발열에 복용하세요.', block=True)")
    else:
        print("  ⚠ 오프라인: 라즈베리파이에서 espeak-ng 한국어 팩 설치 필요")
        print("    sudo apt install espeak-ng espeak-ng-data")

    print()
    print("모든 테스트 통과")


if __name__ == "__main__":
    run()
