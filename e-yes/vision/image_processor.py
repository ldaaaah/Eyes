"""
하우스 약사 — 비전 처리 모듈 v7 (Gemini Vision 4방향 동시 전송)

파이프라인:
  1. QR/바코드 감지 → 처방약 모드
  2. QR 없으면:
     → 0/90/180/270도 4방향 이미지를 한 번의 Gemini 요청으로 전송
     → 어느 방향으로 약을 놓아도 인식 가능
"""

import cv2
import base64
import json
import numpy as np
import requests
from pyzbar import pyzbar
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"

def _load_gemini_key() -> str:
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f).get("gemini_api_key", "")
    except Exception:
        return ""

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


# ══════════════════════════════════════════════
# 공개 인터페이스
# ══════════════════════════════════════════════

def process_image(image_path: str) -> dict:
    img = cv2.imread(str(image_path))
    if img is None:
        return _fail(f"이미지 로드 실패: {image_path}")

    # 1. QR/바코드 감지
    qr = _detect_qr_multipass(img)
    if qr:
        return {
            "mode":        "QR",
            "text":        qr["text"],
            "lines":       [qr["text"]],
            "qr_raw":      qr["raw"],
            "confidence":  100.0,
            "ocr_source":  None,
            "debug_image": qr["debug_img"],
        }
    # 2. Gemini Vision (4방향 동시 전송)
    result_text = _run_gemini_4way(img)
    if result_text:
        print(f"[VISION] Gemini 인식 성공: '{result_text}'")
        return {
            "mode":        "OCR",
            "text":        result_text,
            "lines":       [result_text],
            "qr_raw":      None,
            "confidence":  95.0,
            "ocr_source":  "gemini",
            "debug_image": img,
        }
    return _fail("Gemini Vision 실패")

    return _fail("Gemini Vision 실패")


# ══════════════════════════════════════════════
# Gemini Vision — 4방향 이미지 한 번에 전송
# ══════════════════════════════════════════════

def _run_gemini_4way(img: np.ndarray) -> str | None:
    api_key = _load_gemini_key()
    if not api_key:
        print("[VISION] Gemini API 키 없음")
        return None

    # 4방향 이미지 생성
    rotations = {
        "0도":   img,
        "90도":  cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE),
        "180도": cv2.rotate(img, cv2.ROTATE_180),
        "270도": cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE),
    }

    # 각 이미지를 base64로 변환
    parts = []
    for label, rotated in rotations.items():
        tmp_path = f"/tmp/gemini_{label}.jpg"
        cv2.imwrite(tmp_path, rotated)
        with open(tmp_path, "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode("utf-8")
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": img_b64
            }
        })

    # 프롬프트 마지막에 추가
    parts.append({
        "text": (
            "위 4장의 이미지는 동일한 약 포장지를 0도, 90도, 180도, 270도로 회전한 것입니다.\n"
            "시각장애인이 약을 어느 방향으로 놓을지 모르기 때문에 4방향으로 보냈습니다.\n\n"
            "4장 중 텍스트가 올바르게 보이는 방향을 기준으로 약품명(제품명)만 추출해주세요.\n\n"
            "규칙:\n"
            "1. 가장 크게 인쇄된 텍스트가 약품명입니다\n"
            "2. '정', '캡슐', 'mg' 등이 붙어있으면 포함\n"
            "3. 효능, 성분, 제조사 정보는 제외\n"
            "4. 약품명만 딱 한 줄로 출력 (예: 알로탈정)\n"
            "5. 알 수 없으면 '인식불가' 출력\n"
            "6. '약품명:' 같은 접두사 없이 이름만 출력\n\n"
            "출력예시: 알로탈정\n"
            "약품명(접두사 없이 이름만):"
        )
    })
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{_GEMINI_URL}?key={api_key}",
                json={"contents": [{"parts": parts}]},
                timeout=20,
            )
            if resp.status_code == 503:
                print(f"[VISION] Gemini 503 재시도 {attempt+1}/3...")
                import time as _t; _t.sleep(2)
                continue
            resp.raise_for_status()
            raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            print(f"[VISION] Gemini 원본 응답: '{raw}'")
            clean = raw.replace("*", "").replace("#", "").replace("약품명:", "").replace("약품명 :", "").replace("약품명(접두사 없이 이름만):", "").strip()
            clean = clean.split("\n")[0].strip()
            if not clean or clean == "인식불가":
                return None
            return clean
        except requests.exceptions.Timeout:
            print("[VISION] Gemini 타임아웃")
        except requests.exceptions.ConnectionError:
            print("[VISION] 네트워크 없음")
        except Exception as e:
            print(f"[VISION] Gemini 오류: {e}")
    return None


def _get_ocr_engine():
    pass  # Gemini 사용으로 PaddleOCR 불필요



def _detect_qr_multipass(img):
    import cv2
    from pyzbar import pyzbar
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    candidates = [
        (gray, 0),
        (cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], 0),
        (cv2.equalizeHist(gray), 0),
    ]
    for angle in [90, 180, 270]:
        candidates.append((_rotate(gray, angle), angle))
    for scan_img, angle in candidates:
        result = _try_decode(scan_img, img)
        if result:
            result["angle"] = angle
            return result
    return None


def _try_decode(scan_img, orig_img):
    import cv2
    from pyzbar import pyzbar
    decoded = pyzbar.decode(scan_img)
    for d in decoded:
        text = d.data.decode("utf-8", errors="ignore")
        print(f"[VISION] {d.type} 감지: {text[:50]}")
        debug = orig_img.copy()
        cv2.putText(debug, f"{d.type} DETECTED", (20, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
        return {"text": text, "raw": text, "debug_img": debug}
    return None


def _rotate(img, angle):
    import cv2
    if angle == 90:  return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180: return cv2.rotate(img, cv2.ROTATE_180)
    if angle == 270: return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _fail(msg):
    print(f"[VISION] {msg}")
    return {
        "mode": "ERROR", "text": "", "lines": [],
        "qr_raw": None, "confidence": 0.0,
        "ocr_source": None, "debug_image": None,
    }
