"""
하우스 약사 — 메인 파이프라인 (최종)

실행:
  python main.py

전체 흐름:
  부팅 → OCR 워밍업 → 로그인 → 스캔 대기
  → 이미지 폴링(새 파일만) → 병렬 OCR/QR 인식
  → 약 요약 TTS → STT 상세 안내 여부
  → 금기 교차검증 → 장기복용 등록 → 로그 저장
"""

import sys
import time
import json
import threading
import os
import platform
import concurrent.futures
from pathlib import Path
from datetime import datetime, date

# ══════════════════════════════════════════════════════════════════
# GPIO (라즈베리파이 전용 — Windows에서는 조용히 비활성화)
# ══════════════════════════════════════════════════════════════════

GPIO     = None
_GPIO_OK = False
_IS_PI   = platform.system() == "Linux"
LED_PIN  = 12   # ★ HW팀 확인 후 수정

def _gpio_init():
    global GPIO, _GPIO_OK
    if not _IS_PI:
        print("[GPIO] Windows 환경 — GPIO 비활성화")
        return
    try:
        import RPi.GPIO as _GPIO
        _GPIO.setmode(_GPIO.BCM)
        _GPIO.setup(LED_PIN, _GPIO.OUT)
        _GPIO.output(LED_PIN, _GPIO.LOW)
        GPIO     = _GPIO
        _GPIO_OK = True
        print(f"[GPIO] 초기화 완료 (LED_PIN={LED_PIN})")
    except Exception as e:
        print(f"[GPIO] 초기화 실패 (무시하고 계속): {e}")

def _led(state: bool):
    if not _GPIO_OK or GPIO is None:
        return
    try:
        GPIO.output(LED_PIN, GPIO.HIGH if state else GPIO.LOW)
    except Exception:
        pass

def _gpio_cleanup():
    if _GPIO_OK and GPIO is not None:
        try:
            GPIO.cleanup()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# 내부 모듈
# ══════════════════════════════════════════════════════════════════

from db                      import init_db, get_user_by_id
from db                      import insert_scan_log, mark_log_sent, add_medication
from api                     import fetch_drug_info
from vision.image_processor  import process_image, _get_ocr_engine
from core                    import verify_qr, check_and_warn, DialUserSelector
from core.voice_registration import VoiceRegistration
from core.drug_matcher       import get_drug_candidates
from core.stt                import stt_listen, stt_yes_no
from tts                     import Speaker, Script
from server                  import send_scan_log, retry_unsent_logs
from serial_manager          import get_serial, close_serial


# ══════════════════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════════════════

# ★ 실제 경로 확인 필요 (HW팀이 저장하는 위치)
_BASE_DIR = Path("/home/pi/photos")
IMG_PICAM = _BASE_DIR / "picam.jpg"
IMG_ESP32 = _BASE_DIR / "esp32.jpg"

_USE_SERIAL     = False          # ★ HW팀 합체 후 True로 변경
SERIAL_PORT     = "/dev/ttyUSB0" # 안 되면 /dev/ttyACM0 시도
SERIAL_BAUD     = 9600
RETRY_INTERVAL  = 60
IMAGE_TIMEOUT   = 10.0           # 이미지 대기 최대 시간(초)
IMAGE_STALE_SEC = 5.0            # 이보다 오래된 파일은 이전 스캔으로 간주


# STT는 core/stt.py 에서 임포트 (위 import 구문 참조)


# ══════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════

def main():
    print("[BOOT] 하우스 약사 시작")

    _gpio_init()
    # 이전 다이얼 신호 초기화
    import os
    for f in ["/tmp/dial_signal", "/tmp/capture_ready"]:
        try: os.remove(f)
        except: pass
    init_db()

    # OCR 엔진 워밍업 (첫 스캔 지연 방지)
    print("[BOOT] OCR 엔진 워밍업 중...")
    try:
        _get_ocr_engine()
        print("[BOOT] OCR 엔진 준비 완료")
    except Exception as e:
        print(f"[BOOT] OCR 워밍업 실패 (계속 진행): {e}")

    speaker = Speaker()
    #pass  # _start_retry_timer() 비활성화  # 서버 미설정으로 비활성화

    current_user = _login_flow(speaker)
    speaker.say(Script.SCAN_READY)

    try:
        while True:
            try:
                _wait_for_object()
                _scan_cycle(speaker, current_user)

            except LoginRequested:
                current_user = _login_flow(speaker)
                speaker.say(Script.SCAN_READY)

    except KeyboardInterrupt:
        print("\n[BOOT] 종료")
    finally:
        _gpio_cleanup()
        close_serial()


# ══════════════════════════════════════════════════════════════════
# 로그인 흐름
# ══════════════════════════════════════════════════════════════════

class LoginRequested(Exception):
    pass


def _login_flow(speaker: Speaker) -> dict:
    speaker.say(Script.LOGIN_PROMPT)
    selector = DialUserSelector()

    first = selector.current()
    speaker.say(f"1번, {first['name']}")

    while True:
        action = _read_dial_input()

        if action == "RIGHT":
            slot = selector.turn_right()
            speaker.say(slot["tts_script"])

        elif action == "LEFT":
            slot = selector.turn_left()
            speaker.say(slot["tts_script"])

        elif action == "CONFIRM":
            result = selector.confirm()

            if result["is_add_slot"]:
                speaker.say(result["tts_script"])
                reg = VoiceRegistration(tts_fn=speaker.say)
                while True:
                    # 이름 입력
                    speaker.say("등록하실 이름을 말씀해주세요.", block=True)
                    time.sleep(0.8)
                    name = stt_listen(timeout=7)
                    if not name:
                        name = input("[키보드] 이름 입력: ").strip()
                    # 나이 입력 (한국식)
                    speaker.say("나이를 말씀해주세요. 예: 예순다섯.", block=True)
                    time.sleep(0.8)
                    age_text = stt_listen(timeout=7)
                    import re as _re
                    if age_text:
                        digits = _re.sub(r"[^0-9]", "", age_text)
                        age = int(digits) if digits else 0
                    else:
                        age_input = input("[키보드] 나이 입력: ").strip()
                        age = int(age_input) if age_input.isdigit() else 0
                    birth = 2026 - age + 1  # 한국식 나이
                    # 확인
                    speaker.say(f"{name}님, {birth}년생 맞으시면 버튼을 눌러주세요. 아니라면 아니라고 말씀해주세요.", block=True)
                    time.sleep(0.8)
                    confirm_text = stt_listen(timeout=6)
                    if confirm_text and any(w in confirm_text for w in ["아니", "아니요", "틀려", "다시"]):
                        speaker.say("다시 입력해주세요.")
                        continue
                    action2 = _read_dial_input()
                    if action2 == "CONFIRM":
                        saved = reg.save(name, birth)
                        speaker.say(saved["tts_script"], block=True)
                        selector.reload()
                        speaker.say(Script.LOGIN_PROMPT)
                        break
                    else:
                        speaker.say("취소했습니다.")
                        break

            else:
                speaker.say(result["tts_script"], block=True)
                return result


# ══════════════════════════════════════════════════════════════════
# 스캔 사이클
# ══════════════════════════════════════════════════════════════════

def _scan_cycle(speaker: Speaker, user: dict) -> None:
    user_id = user["user_id"]
    speaker.say(Script.SCANNING)
    # ── 잠시만 기다려주세요 반복 안내 ────
    _waiting = [True]
    def _waiting_tts():
        while _waiting[0]:
            speaker.say("잠시만 기다려주세요.")
            for _ in range(30):
                if not _waiting[0]:
                    return
                time.sleep(0.1)
    import threading as _th
    _th.Thread(target=_waiting_tts, daemon=True).start()
    scan_triggered_at = time.time()
    picam_path, esp32_path = _find_latest_images(_BASE_DIR, scan_triggered_at)
    if not picam_path and not esp32_path:
        speaker.say(Script.SCAN_FAIL)
        return
    # ── 병렬 OCR 처리 ────────────────────────────────────────────────
    results = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {}
        if picam_path:
            futures[picam_path] = executor.submit(process_image, str(picam_path))
        if esp32_path:
            futures[esp32_path] = executor.submit(process_image, str(esp32_path))
        for path, future in futures.items():
            try:
                res = future.result()
                if res["mode"] != "ERROR":
                    results.append(res)
            except Exception as e:
                print(f"[SCAN] OCR 오류 ({path.name}): {e}")
            finally:
                _safe_remove(path)

    if not results:
        speaker.say(Script.SCAN_FAIL)
        return

    # QR 결과 우선, 없으면 신뢰도 높은 OCR 선택
    qr_results = [r for r in results if r["mode"] == "QR"]
    result     = qr_results[0] if qr_results else max(results, key=lambda x: x["confidence"])

    if not result["text"]:
        speaker.say(Script.SCAN_FAIL)
        return

    raw_text  = result["text"]
    ocr_lines = result.get("lines", [])
    mode      = result["mode"]
    print(f"[SCAN] 모드={mode} 신뢰도={result['confidence']:.1f}% 텍스트='{raw_text[:60]}'")

    # ── QR / OCR 분기 ────────────────────────────────────────────────
    qr_hash_in = qr_hash_out = None
    hash_verified = None

    if mode == "QR":
        vr = verify_qr(result["qr_raw"])
        if not vr["valid"]:
            speaker.say(Script.QR_TAMPERED)
            _save_log(user_id, mode, raw_text, None,
                      hash_verified=False, conflict_detected=False,
                      api_fetch_success=False, tts_script=Script.QR_TAMPERED)
            return
        hash_verified = True
        qr_hash_in    = vr["hash_in_code"]
        qr_hash_out   = vr["hash_computed"]
        drug_name     = vr["payload"].get("drug_name", raw_text)
        candidates    = [drug_name]

    else:
        candidates = get_drug_candidates(raw_text, ocr_lines)
        print(f"[SCAN] fuzzy 매칭 후보: {candidates}")

        if not candidates:
            # ★ 시연 안전망: OCR 실패 시 키보드로 직접 입력
            print("\n⚠️  OCR 인식 결과 없음.")
            drug_name = input("약 이름 직접 입력 (시연용 백업): ").strip()
            candidates = [drug_name] if drug_name else []

        if not candidates:
            speaker.say(Script.SCAN_FAIL)
            return

        drug_name = candidates[0]

    # ── API 검색 ─────────────────────────────────────────────────────
    drug_info = None
    if mode == "QR":
        drug_info = fetch_drug_info(drug_name)
    else:
        for candidate in candidates:
            print(f"[SCAN] API 검색: '{candidate}'")
            drug_info = fetch_drug_info(candidate)
            if drug_info:
                drug_name = candidate
                break

    if not drug_info:
        speaker.say(Script.API_FAIL)
        _save_log(user_id, mode, raw_text, drug_name,
                  hash_verified=hash_verified, conflict_detected=False,
                  api_fetch_success=False, tts_script=Script.API_FAIL)
        return

    # ── 대기 안내 중단 ───────────────────────────────────────────────
    _waiting[0] = False
    speaker.clear()

    # ── LED 점등 ─────────────────────────────────────────────────────
    _led(True)

    # ── 금기 약물 검사 ───────────────────────────────────────────────
    # 첫 인식 여부 확인
    from db import get_connection as _gc
    with _gc() as _conn:
        pair_count = _conn.execute(
            "SELECT COUNT(*) FROM contraindication_pairs WHERE drug_name_a LIKE ? OR drug_name_b LIKE ?",
            (f"%{drug_name}%", f"%{drug_name}%")
        ).fetchone()[0]
    if pair_count == 0 and user_id != -1:
        first_result = stt_yes_no(speaker,
            "처음 인식한 약입니다. 금기약물 정보가 등록되어 있지 않습니다. 금기약물 정보를 등록할까요?",
            timeout=8)
        if first_result:
            speaker.say("금기약물 정보를 등록 중입니다. 잠시만 기다려주세요.")
            from api.mfds_api import _auto_register_contraindications
            _auto_register_contraindications(drug_info)
            speaker.say("금기약물 정보가 등록되었습니다.")
    conflict = check_and_warn(drug_name, user_id)
    if conflict["conflict_detected"]:
        speaker.say(conflict["tts_warning"], block=True)

    # ── 요약 안내 (항상) ─────────────────────────────────────────────
    short_summary = (
        f"{drug_info.get('drug_name', drug_name)}입니다. "
        f"{(drug_info.get('efficacy', '효능 정보 없음') or '')[:60]}"
    )
    speaker.say(short_summary, block=True)

    # ── STT: 상세 안내 여부 ──────────────────────────────────────────
    detail_script = ""
    stt_result = stt_yes_no(speaker, "자세한 설명을 원하시면 설명이라고 말씀해주세요.", timeout=8)

    # STT 실패 시 버튼 폴백
    if stt_result is None:
        stt_result = _wait_for_button_timeout(timeout_sec=5)

    if stt_result:
        detail_script = Script.drug_summary(
            drug_name = drug_info.get("drug_name", drug_name),
            efficacy  = drug_info.get("efficacy",  "효능 정보 없음"),
            dosage    = drug_info.get("dosage_info", "용법 정보 없음"),
        )
        speaker.say(detail_script, block=True)

    tts_script = detail_script if detail_script else short_summary

    # ── 장기복용 등록 ────────────────────────────────────────────────
    _ask_add_medication(speaker, user_id, drug_info)

    # ── 로그 저장 ────────────────────────────────────────────────────
    _save_log(
        user_id=user_id, mode=mode, raw_text=raw_text,
        drug_name=drug_name, qr_hash_in=qr_hash_in, qr_hash_out=qr_hash_out,
        hash_verified=hash_verified,
        conflict_detected=conflict["conflict_detected"],
        conflict_details=conflict["conflicts"],
        api_fetch_success=True,
        tts_script=tts_script,
    )

    # ── LED 소등 ─────────────────────────────────────────────────────
    _led(False)

    # ── 종료 여부 확인 ───────────────────────────────────────────────
    speaker.say("종료하시겠습니까? 종료하려면 종료라고 말씀해주세요.")
    import time as _t2; _t2.sleep(0.8)
    quit_response = stt_listen(timeout=8)
    quit_words = ["종료", "꺼줘", "끝", "그만", "종료해", "네", "응", "예", "좋아"]
    quit_result = any(w in quit_response for w in quit_words) if quit_response else None
    if quit_result is None:
        quit_result = _wait_for_button_timeout(timeout_sec=5)
    if quit_result:
        speaker.say("이용해주셔서 감사합니다. 프로그램을 종료합니다.", block=True)
        raise KeyboardInterrupt
    else:
        speaker.say("다음 약을 올려주세요.")


# ══════════════════════════════════════════════════════════════════
# 하드웨어 인터페이스
# ══════════════════════════════════════════════════════════════════
def _wait_for_object() -> None:
    """스캔 신호(C) 대기"""
    import os
    open("/tmp/capture_ready", "w").write("1")
    print("\n[대기] 다이얼 버튼(C)을 눌러 스캔 시작...")
    while True:
        if not os.path.exists("/tmp/capture_ready"):
            print(">>> 스캔 시작 <<<")
            return
        time.sleep(0.1)


def _read_dial_input() -> str:
    """다이얼 입력 읽기 (R/L/C)"""
    if _USE_SERIAL and _IS_PI:
        try:
            ser = get_serial(SERIAL_PORT, SERIAL_BAUD)
            while True:
                if ser.in_waiting > 0:
                    line = ser.readline().decode("utf-8", errors="ignore").strip().upper()
                    if line == "R":
                        print(">>> RIGHT")
                        return "RIGHT"
                    elif line == "L":
                        print(">>> LEFT")
                        return "LEFT"
                    elif line == "C":
                        print(">>> CONFIRM")
                        return "CONFIRM"
        except Exception as e:
            print(f"[시리얼 에러] {e} → 키보드 모드")

    # med_capture.py가 /tmp/dial_signal 파일에 R/L/C 씀
    import os
    sig_path = "/tmp/dial_signal"
    print("[다이얼] 입력 대기 중...")
    while True:
        if os.path.exists(sig_path):
            try:
                sig = open(sig_path).read().strip().upper()
                os.remove(sig_path)
                if sig == "R":
                    print(">>> RIGHT")
                    return "RIGHT"
                elif sig == "L":
                    print(">>> LEFT")
                    return "LEFT"
                elif sig == "C":
                    print(">>> CONFIRM")
                    return "CONFIRM"
            except Exception:
                pass
        time.sleep(0.05)


def _wait_for_button_timeout(timeout_sec: int = 5) -> bool:
    """
    timeout_sec 초 안에 C 신호 오면 True.
    select 미사용 (Windows/Pi 공통 호환).
    """
    if _USE_SERIAL and _IS_PI:
        try:
            ser = get_serial(SERIAL_PORT, SERIAL_BAUD)
            print(f"[장기복용] {timeout_sec}초 안에 다이얼(C)을 누르면 추가됩니다...")
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                if ser.in_waiting > 0:
                    line = ser.readline().decode("utf-8", errors="ignore").strip().upper()
                    if line in ("C", "CONFIRM"):
                        return True
                time.sleep(0.05)
            print("(시간 초과)")
            return False
        except Exception as e:
            print(f"[시리얼 에러] {e}")
            return False

    # 키보드 모드: threading으로 타임아웃 (select 대체)
    ans = input("[키보드] 추가하려면 c, 건너뛰려면 Enter → ").strip().lower()
    return ans == "c"


# ══════════════════════════════════════════════════════════════════
# 이미지 유틸리티
# ══════════════════════════════════════════════════════════════════

def _wait_for_fresh_image(path: Path, since: float,
                          timeout: float = IMAGE_TIMEOUT,
                          interval: float = 0.2) -> bool:
    """
    스캔 트리거(since) 이후에 저장된 새 이미지만 인정.
    오래된 파일(이전 스캔 잔존)은 무시.
    """
    deadline = since + timeout
    while time.time() < deadline:
        if path.exists() and path.stat().st_size > 0:
            mtime = path.stat().st_mtime
            if mtime >= since - IMAGE_STALE_SEC:
                return True
        time.sleep(interval)
    print(f"[IMAGE] 대기 타임아웃: {path.name}")
    return False


def _safe_remove(path: Path) -> None:
    try:
        path.unlink()
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════
# 유틸리티
# ══════════════════════════════════════════════════════════════════

def _ask_add_medication(speaker: Speaker, user_id: int, drug_info: dict) -> None:
    dosage    = drug_info.get("dosage_info", "")
    speaker.say("장기복용 목록에 추가하시려면 추가라고 말씀해주세요.", block=True)
    time.sleep(0.8)
    add_response = stt_listen(timeout=8)
    add_words = ["추가", "추가해", "넣어", "등록", "네", "응", "예", "좋아"]
    stt_result = bool(add_response and any(w in add_response for w in add_words))

    if stt_result:
        add_medication(
            user_id    = user_id,
            drug_name  = drug_name,
            drug_code  = drug_info.get("drug_code"),
            dosage     = dosage,
            start_date = date.today().strftime("%Y-%m-%d"),
        )
        speaker.say(f"{drug_name}을 장기복용 목록에 추가했습니다.")
        print(f"[MED] 장기복용 추가: {drug_name}")
    else:
        print("[MED] 장기복용 추가 스킵")


def _save_log(user_id, mode, raw_text, drug_name,
              qr_hash_in=None, qr_hash_out=None, hash_verified=None,
              conflict_detected=False, conflict_details=None,
              api_fetch_success=False, tts_script=None) -> int:
    return insert_scan_log(
        user_id           = user_id,
        recognition_mode  = mode,
        raw_text          = raw_text,
        recognized_drug   = drug_name,
        qr_hash_in_code   = qr_hash_in,
        qr_hash_computed  = qr_hash_out,
        hash_verified     = hash_verified,
        conflict_detected = conflict_detected,
        conflict_details  = conflict_details or [],
        api_fetch_success = api_fetch_success,
        tts_script        = tts_script,
    )


def _start_retry_timer() -> None:
    def loop():
        while True:
            time.sleep(RETRY_INTERVAL)
            try:
                retry_unsent_logs()
            except Exception as e:
                print(f"[RETRY] 전송 실패: {e}")
    threading.Thread(target=loop, daemon=True).start()


def _find_latest_images(base_dir: Path, since: float) -> tuple:
    """photo 폴더에서 가장 최근 picam/esp32 파일 동적 탐색"""
    picam = None
    esp32 = None
    deadline = since + IMAGE_TIMEOUT
    print(f"[IMAGE] 새 파일 대기 중... (최대 {IMAGE_TIMEOUT}초)")
    while time.time() < deadline:
        try:
            files = list(base_dir.glob("*.jpg"))
            for f in sorted(files, key=lambda x: x.stat().st_mtime, reverse=True):
                mtime = f.stat().st_mtime
                if mtime < since - IMAGE_STALE_SEC:
                    continue
                name = f.name.lower()
                if "picam" in name and picam is None:
                    picam = f
                elif "esp32" in name and esp32 is None:
                    esp32 = f
                if picam and esp32:
                    break
        except Exception as e:
            print(f"[IMAGE] 탐색 오류: {e}")
        if picam or esp32:
            print(f"[IMAGE] 발견: picam={picam}, esp32={esp32}")
            return picam, esp32
        time.sleep(0.2)
    print("[IMAGE] 대기 타임아웃")
    return None, None


if __name__ == "__main__":
    main()
