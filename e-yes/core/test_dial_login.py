import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.schema import init_db, DB_PATH
from db import create_user
from core.dial_login import DialUserSelector


def run():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()

    # 사용자 3명 등록
    create_user("홍길동", birth_year=1948)
    create_user("김순이", birth_year=1955)
    create_user("이철수", birth_year=1960)

    selector = DialUserSelector()

    print("── 장치 켜짐: 첫 번째 사용자 자동 표시 ──")
    first = selector.current()
    print(f"  현재: {first['name']}\n")

    print("── 다이얼 오른쪽 회전 ──")
    r = selector.turn_right()
    print(f"  TTS: \"{r['tts_script']}\"")
    assert r["name"] == "김순이"

    r = selector.turn_right()
    print(f"  TTS: \"{r['tts_script']}\"")
    assert r["name"] == "이철수"

    print("\n── 마지막에서 오른쪽 → 처음으로 순환 ──")
    r = selector.turn_right()
    print(f"  TTS: \"{r['tts_script']}\"")
    assert r["name"] == "홍길동"

    print("\n── 다이얼 왼쪽 회전 ──")
    r = selector.turn_left()
    print(f"  TTS: \"{r['tts_script']}\"")
    assert r["name"] == "이철수"

    print("\n── 버튼 눌러서 로그인 확정 ──")
    selector.turn_right()  # 홍길동으로 이동
    selector.turn_right()  # 김순이로 이동
    result = selector.confirm()
    print(f"  TTS: \"{result['tts_script']}\"")
    assert result["name"] == "김순이"
    assert result["user_id"] is not None

    print("\n모든 테스트 통과")


if __name__ == "__main__":
    run()
