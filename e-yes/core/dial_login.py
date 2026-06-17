"""
하우스 약사 — 다이얼(로터리 엔코더) 사용자 선택 모듈

동작 방식:
  다이얼 오른쪽 → 다음 사용자 이름 TTS 읽기
  다이얼 왼쪽  → 이전 사용자 이름 TTS 읽기
  버튼 누름    → 현재 사용자로 로그인 / 마지막 칸이면 사용자 추가 시작
"""

from db import get_all_users

_ADD_USER_SLOT = {
    "user_id":      None,
    "name":         "사용자 추가",
    "display_order": 9999,
    "is_add_slot":  True,
}


class DialUserSelector:
    """
    다이얼로 사용자를 순환 선택하는 상태 관리 클래스.

    목록 마지막 칸은 항상 "사용자 추가" 슬롯.
    confirm() 호출 시 반환값의 is_add_slot 이 True 이면
    호출부에서 VoiceRegistration 을 시작하면 됨.
    """

    def __init__(self):
        self.reload()

    # ── 다이얼 조작 ──────────────────────────────

    def turn_right(self) -> dict:
        """다이얼 오른쪽 회전 → 다음 항목"""
        self._index = min(self._index + 1, len(self._slots) - 1)
        return self._announce()

    def turn_left(self) -> dict:
        """다이얼 왼쪽 회전 → 이전 항목"""
        self._index = max(self._index - 1, 0)
        return self._announce()

    def current(self) -> dict:
        return self._slots[self._index]

    def confirm(self) -> dict:
        """
        버튼 누름.
        일반 사용자 → {"user_id": ..., "name": ..., "tts_script": ..., "is_add_slot": False}
        추가 슬롯   → {"is_add_slot": True, "tts_script": "사용자 추가를 시작합니다."}
        """
        slot = self._slots[self._index]
        if slot.get("is_add_slot"):
            return {"is_add_slot": True, "tts_script": "사용자 추가를 시작합니다."}
        return {
            "user_id":    slot["user_id"],
            "name":       slot["name"],
            "is_add_slot": False,
            "tts_script": f"{slot['name']}님으로 로그인했습니다.",
        }

    def reload(self) -> None:
        """DB에서 사용자 목록 다시 불러오기 + 추가 슬롯 붙이기"""
        users = get_all_users()
        self._slots = [{**u, "is_add_slot": False} for u in users] + [_ADD_USER_SLOT]
        self._index = 0

    # ── 내부 ─────────────────────────────────────

    def _announce(self) -> dict:
        slot = self._slots[self._index]
        if slot.get("is_add_slot"):
            return {"is_add_slot": True, "tts_script": "사용자 추가"}
        position = f"{self._index + 1}번"
        return {
            "user_id":    slot["user_id"],
            "name":       slot["name"],
            "is_add_slot": False,
            "tts_script": f"{position}, {slot['name']}",
        }
