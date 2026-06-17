import cv2
import pytesseract

print("[시스템] 원본 사진을 불러옵니다...")
img = cv2.imread('/home/pi/m.jpg')

# ── [핵심 전처리 마법 구간] ──
print("[시스템] OCR 전용 흑백 고대비 필터를 적용합니다...")

# 1. 사진 크기 2배 뻥튀기 (작은 글씨 인식률 폭발적 증가)
img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

# 2. 컬러를 흑백(Grayscale)으로 변환
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

# 3. 이진화 (배경은 완전 하얗게, 글씨는 완전 까맣게 분리)
# 오츠(Otsu) 알고리즘을 써서 최적의 흑백 대비를 자동으로 찾습니다.
_, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

# (옵션) 테서랙트가 어떻게 보는지 확인하기 위해 변환된 사진 저장해보기
cv2.imwrite('/home/pi/Desktop/e-yes/debug_ocr.jpg', thresh)

print("[시스템] 글자를 읽어냅니다...")

# 4. 테서랙트 가동 (psm 6 모드: 텍스트가 한 덩어리로 뭉쳐있다고 가정하고 꼼꼼히 읽기)
custom_config = r'--oem 3 --psm 6'
text = pytesseract.image_to_string(thresh, lang='kor', config=custom_config)

print("\n==== 💡 [인식 결과] ====")
print(text.strip())
print("========================\n")
