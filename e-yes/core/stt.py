"""
하우스 약사 — STT(음성 인식) 전담 모듈
"""

import speech_recognition as sr
import time

_recognizer = None

def _get_recognizer() -> sr.Recognizer:
    global _recognizer
    if _recognizer is None:
        _recognizer = sr.Recognizer()
        _recognizer.pause_threshold = 0.5
        _recognizer.energy_threshold = 50
        _recognizer.dynamic_energy_threshold = False
    return _recognizer


def stt_listen(timeout: int = 8) -> str:
    recognizer = _get_recognizer()
    try:
        with sr.Microphone(device_index=2, sample_rate=48000) as source:
            print("[STT] 듣는 중...")
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=6)
        print("[STT] 인식 시도 중...")
        text = recognizer.recognize_google(audio, language="ko-KR")
        print(f"[STT] 인식 결과: '{text}'")
        return text
    except sr.WaitTimeoutError:
        print("[STT] 입력 시간 초과")
    except sr.UnknownValueError:
        print("[STT] 인식 실패 (소리는 들었는데 내용 모름)")
    except sr.RequestError as e:
        print(f"[STT] 서비스 오류: {e}")
    except Exception as e:
        print(f"[STT] 오류: {e}")
    return ""


def stt_yes_no(speaker, prompt: str, timeout: int = 8) -> bool | None:
    speaker.say(prompt, block=True)
    time.sleep(0.8)
    response = stt_listen(timeout=timeout)
    if not response:
        return None
    positive = ["응", "네", "예", "좋아", "알겠어", "알겠습니다", "맞아", "해줘", "설명", "네네", "그래", "당연", "물론", "해주세요"]
    negative = ["아니", "아니요", "됐어", "괜찮아", "싫어", "노", "필요없어", "안해"]
    if any(word in response for word in positive):
        return True
    if any(word in response for word in negative):
        return False
    return None
