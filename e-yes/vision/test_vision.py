import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from vision.image_processor import process_image

IMG_DIR = Path(__file__).parent.parent / "test_images"

TEST_IMAGES = [
    ("박스 - 15cm",       "15cm.jpg"),
    ("박스 - 20cm",       "20cm.jpg"),
    ("튜브 QR포함",        "tubetest_1.jpg"),
    ("튜브 정면",          "tubetest.jpg"),
    ("튜브 위에서",        "tubetest_up_2.jpg"),
]

def run():
    print("=" * 55)
    print("하우스 약사 — 비전 처리 테스트")
    print("=" * 55)

    for label, fname in TEST_IMAGES:
        path = IMG_DIR / fname
        if not path.exists():
            print(f"\n[SKIP] {label}: 파일 없음")
            continue

        print(f"\n{'─'*55}")
        print(f"[{label}] {fname}")
        print('─'*55)

        result = process_image(str(path))

        print(f"  모드:     {result['mode']}")
        print(f"  신뢰도:   {result['confidence']:.1f}%")
        print(f"  추출 텍스트: {result['text'][:80] if result['text'] else '(없음)'}")

    print(f"\n{'='*55}")
    print("테스트 완료")

if __name__ == "__main__":
    run()
