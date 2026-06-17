"""
하우스 약사 — 음성 사용자 등록 모듈
이름 → 나이 순서로 음성 입력
"""

import re
from db import create_user
from core.stt import stt_listen


class VoiceRegistration:
    def __init__(self, tts_fn=None):
        self._tts = tts_fn or (lambda text: print(f"[TTS] {text}"))

    def run(self) -> dict:
        name = self._ask_name()
        if not name:
            return self._fail("이름 인식에 실패했습니다.")

        age = self._ask_age()
        if not age:
            return self._fail("나이 인식에 실패했습니다.")

        birth_year = 2025 - int(age)

        self._tts(f"{name}님, {age}세로 등록할까요? 확인 버튼을 눌러주세요.")
        return {
            "success":    True,
            "name":       name,
            "birth_year": birth_year,
            "pending":    True,
        }

    def save(self, name: str, birth_year: int, gender: str = None) -> dict:
        user_id = create_user(name=name, birth_year=birth_year)
        script = f"{name}님이 등록되었습니다."
        self._tts(script)
        return {
            "success":    True,
            "user_id":    user_id,
            "name":       name,
            "tts_script": script,
        }

    def _ask_name(self) -> str:
        for attempt in range(2):
            prompt = "이름을 말씀해 주세요." if attempt == 0 else "다시 한 번 말씀해 주세요."
            self._tts(prompt)
            text = stt_listen(timeout=7)
            if text:
                return text.strip()
        print("[STT 실패] 키보드 입력으로 대체")
        return input("[키보드] 이름 입력: ").strip()

    def _ask_age(self) -> str:
        for attempt in range(2):
            prompt = "나이를 말씀해 주세요. 예: 예순다섯." if attempt == 0 else "다시 한 번 말씀해 주세요."
            self._tts(prompt)
            text = stt_listen(timeout=7)
            if text:
                digits = re.sub(r"[^0-9]", "", text)
                if digits:
                    return digits
                age = _korean_to_age(text)
                if age:
                    return str(age)
        print("[STT 실패] 키보드 입력으로 대체")
        return input("[키보드] 나이 입력: ").strip()

    def _fail(self, reason: str) -> dict:
        self._tts(reason)
        return {"success": False, "reason": reason}


def _korean_to_age(text: str) -> int | None:
    korean_nums = {
        "하나": 1, "둘": 2, "셋": 3, "넷": 4, "다섯": 5,
        "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
        "스물": 20, "서른": 30, "마흔": 40, "쉰": 50,
        "예순": 60, "일흔": 70, "여든": 80, "아흔": 90,
    }
    total = 0
    for k, v in sorted(korean_nums.items(), key=lambda x: -x[1]):
        if k in text:
            total += v
            text = text.replace(k, "", 1)
    return total if total > 0 else None
