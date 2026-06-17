"""
하우스 약사 — TTS 음성 출력 모듈

온라인:  gTTS (구글) → 자연스러운 한국어 발음
오프라인: pyttsx3    → 와이파이 없을 때 자동 전환

수정사항:
  - pygame 출력 장치 명시적 지정 (USB 스피커 자동 감지)
  - 장치 감지 실패 시 기본 장치 유지
"""

import os
import tempfile
import threading
import queue
import socket
import platform
from pathlib import Path


# ── 출력 장치 감지 ──────────────────────────────────────────────────

def _find_usb_audio_device() -> int:
    """
    USB 오디오 장치 인덱스 자동 감지.
    라즈베리파이 기준: aplay -l 로 카드 목록 조회.
    감지 실패 시 -1 반환 (pygame 기본 장치 사용).
    """
    try:
        import subprocess
        result = subprocess.run(
            ["aplay", "-l"],
            capture_output=True, text=True, timeout=3
        )
        lines = result.stdout.lower()

        # USB 오디오 카드 번호 찾기
        for line in lines.splitlines():
            if "usb" in line and "card" in line:
                # 예: "card 1: Device [USB Audio Device], ..."
                parts = line.split("card")
                if len(parts) > 1:
                    card_num = parts[1].strip().split(":")[0].strip()
                    if card_num.isdigit():
                        print(f"[TTS] USB 오디오 장치 감지: card {card_num}")
                        return int(card_num)
    except Exception as e:
        print(f"[TTS] 장치 감지 실패 ({e}) → 기본 장치 사용")
    return -1


# 앱 시작 시 1회 감지
_AUDIO_DEVICE_INDEX = _find_usb_audio_device() if platform.system() == "Linux" else -1


# ══════════════════════════════════════════════════════════════════
# 공개 인터페이스
# ══════════════════════════════════════════════════════════════════

class Speaker:
    """
    TTS 음성 출력 클래스.
    내부적으로 큐를 사용해 메시지가 겹치지 않게 순서대로 재생.

    사용 예시:
        sp = Speaker()
        sp.say("타이레놀 500밀리그램입니다.")
        sp.say("하루 세 번 식후에 복용하세요.")
        sp.wait()
    """

    def __init__(self):
        self._queue  = queue.Queue()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def say(self, text: str, block: bool = False) -> None:
        if not text or not text.strip():
            return
        ev = threading.Event() if block else None
        self._queue.put((text.strip(), ev))
        if block and ev:
            ev.wait()

    def wait(self) -> None:
        self._queue.join()

    def clear(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

    # ── 내부 워커 ────────────────────────────────────────────────────

    def _run(self) -> None:
        while True:
            text, event = self._queue.get()
            try:
                if _is_online():
                    _speak_gtts(text)
                else:
                    _speak_pyttsx3(text)
            except Exception as e:
                print(f"[TTS] 재생 실패 ({e}) → 텍스트 출력: {text}")
            finally:
                self._queue.task_done()
                if event:
                    event.set()


# ══════════════════════════════════════════════════════════════════
# gTTS (온라인)
# ══════════════════════════════════════════════════════════════════

def _speak_gtts(text: str) -> None:
    from gtts import gTTS
    import pygame

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    try:
        # TTS 파일 생성
        tts = gTTS(text=text, lang="ko", slow=False)
        tts.save(tmp_path)

        # ── pygame 초기화: USB 장치 지정 ────────────────────────────
        if _AUDIO_DEVICE_INDEX >= 0:
            # USB 스피커가 감지된 경우 환경변수로 장치 지정
            os.environ["SDL_AUDIODRIVER"] = "alsa"
            os.environ["AUDIODEV"]        = f"hw:{_AUDIO_DEVICE_INDEX},0"
        else:
            # 기본 장치 (감지 못 한 경우)
            os.environ.pop("SDL_AUDIODRIVER", None)
            os.environ.pop("AUDIODEV", None)

        pygame.mixer.pre_init(frequency=22050, size=-16, channels=1, buffer=512)
        pygame.mixer.init()
        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()

        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)

        pygame.mixer.music.stop()
        pygame.mixer.quit()

    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# pyttsx3 (오프라인 백업)
# ══════════════════════════════════════════════════════════════════

def _speak_pyttsx3(text: str) -> None:
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 150)
        engine.setProperty("volume", 1.0)
        _set_korean_voice(engine)
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"[TTS] pyttsx3 실패 ({e}) → espeak 시도")
        # espeak: USB 장치 지정
        if _AUDIO_DEVICE_INDEX >= 0:
            os.system(f'espeak -v ko -s 150 -a 200 --stdout "{text}" | aplay -D hw:{_AUDIO_DEVICE_INDEX},0')
        else:
            os.system(f'espeak -v ko -s 150 "{text}"')


def _set_korean_voice(engine) -> None:
    try:
        voices = engine.getProperty("voices")
        for v in voices:
            if "korean" in v.name.lower() or "ko" in v.id.lower():
                engine.setProperty("voice", v.id)
                return
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# 네트워크 상태 확인
# ══════════════════════════════════════════════════════════════════

def _is_online() -> bool:
    try:
        socket.setdefaulttimeout(2)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# 미리 정의된 안내 문구
# ══════════════════════════════════════════════════════════════════

class Script:
    SCAN_READY     = "약을 스테이지에 올려주세요."
    SCANNING       = "인식 중입니다. 잠시 기다려 주세요."
    SCAN_FAIL      = "인식에 실패했습니다. 약을 바르게 놓고 다시 시도해 주세요."
    NOT_MEDICINE   = "약품을 찾을 수 없습니다. 다시 시도해 주세요."
    API_FAIL       = "약품 정보를 가져오지 못했습니다. 잠시 후 다시 시도해 주세요."
    CONFLICT_INTRO = "주의! 현재 복용 중인 약과 충돌이 감지되었습니다."
    QR_TAMPERED    = "경고. 위변조된 처방 코드입니다. 사용하지 마십시오."
    LOGIN_PROMPT   = "다이얼을 돌려 사용자를 선택하고 버튼을 누르세요."

    @staticmethod
    def drug_summary(drug_name: str, efficacy: str, dosage: str) -> str:
        return (
            f"{drug_name}입니다. "
            f"{efficacy} "
            f"복용 방법은 {dosage}"
        )