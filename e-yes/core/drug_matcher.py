"""
하우스 약사 — 약품명 퍼지 매칭 모듈

역할:
  OCR로 추출한 텍스트가 불완전해도 (글자 오인식, 공백 오류 등)
  e약은요 API 검색 결과와 유사도 비교를 통해 가장 가까운 약품명 찾기

파이프라인:
  OCR 텍스트 → 후보 단어 추출 → API 검색 → fuzzy 매칭 → 최적 약품명 반환
"""

import re
from typing import Optional

# rapidfuzz: 빠르고 정확한 문자열 유사도 라이브러리
# pip install rapidfuzz
from rapidfuzz import fuzz, process as fuzz_process


# 검색에서 제외할 불용어 (약 이름이 아닌 일반 단어들)
_STOPWORDS = {
    "그리고", "하지만", "그런데", "복용", "사용", "주의", "성분",
    "위하여", "경우에", "있습니다", "복합", "제산제", "함유량",
    "용법", "용량", "효능", "효과", "주성분", "첨가제", "의약품",
    "전문", "일반", "처방", "보관", "주의사항", "부작용",
}


# ──────────────────────────────────────────────
# 공개 인터페이스
# ──────────────────────────────────────────────

def find_drug_name(ocr_text: str, ocr_lines: list[str] = None) -> Optional[str]:
    """
    OCR 텍스트에서 약품명을 찾아 반환.
    API 검색 + fuzzy matching 조합으로 최적 결과 반환.

    Args:
        ocr_text:  OCR 전체 텍스트 (공백 포함)
        ocr_lines: OCR 줄별 텍스트 목록 (있으면 더 정확한 매칭)

    Returns:
        매칭된 약품명 (예: "타이레놀정500mg") 또는 None
    """
    from api.mfds_api import search_drug_candidates

    if not ocr_text.strip():
        return None

    # 1. 후보 검색어 추출
    search_keywords = _extract_search_keywords(ocr_text, ocr_lines)
    if not search_keywords:
        print("[MATCHER] 검색어 추출 실패")
        return None

    print(f"[MATCHER] 검색 키워드: {search_keywords}")

    # 2. 각 키워드로 API 검색 → 후보 약품명 수집
    api_candidates = []
    for keyword in search_keywords:
        results = search_drug_candidates(keyword, num=5)
        for r in results:
            name = r.get("drug_name", "")
            if name and name not in api_candidates:
                api_candidates.append(name)

    if not api_candidates:
        print("[MATCHER] API 검색 결과 없음")
        return None

    print(f"[MATCHER] API 후보 {len(api_candidates)}건: {api_candidates[:5]}")

    # 3. OCR 텍스트와 API 후보들 간 fuzzy matching
    best_name, best_score = _fuzzy_match(ocr_text, api_candidates)

    if best_score >= 60:  # 60% 이상 유사도면 신뢰
        print(f"[MATCHER] 최종 매칭: '{best_name}' (유사도={best_score:.1f}%)")
        return best_name
    else:
        print(f"[MATCHER] 유사도 미달: '{best_name}' ({best_score:.1f}%) → 매칭 실패")
        return None


def get_drug_candidates(ocr_text: str, ocr_lines: list[str] = None) -> list[str]:
    """
    fuzzy matching 후보 목록 반환 (신뢰도 순).
    main.py의 순서대로 시도 로직과 호환.
    """
    from api.mfds_api import search_drug_candidates

    search_keywords = _extract_search_keywords(ocr_text, ocr_lines)
    if not search_keywords:
        return []

    api_candidates = []
    for keyword in search_keywords:
        results = search_drug_candidates(keyword, num=5)
        for r in results:
            name = r.get("drug_name", "")
            if name and name not in api_candidates:
                api_candidates.append(name)

    if not api_candidates:
        return []

    # 유사도 기준 정렬
    scored = _score_all(ocr_text, api_candidates)
    return [name for name, score in scored if score >= 40]


# ──────────────────────────────────────────────
# 내부 함수
# ──────────────────────────────────────────────

def _extract_search_keywords(ocr_text: str, ocr_lines: list[str] = None) -> list[str]:
    """
    OCR 텍스트에서 API 검색에 쓸 키워드 목록 추출.
    줄 단위 텍스트가 있으면 짧은 줄(약 이름일 가능성 높음)을 우선.
    """
    keywords = []

    # 줄 단위 분석: 짧고 한글 비율 높은 줄 우선 (약 이름은 보통 첫 줄에 크게 표시)
    if ocr_lines:
        for line in ocr_lines:
            line = line.strip()
            korean_ratio = len(re.findall(r"[가-힣]", line)) / max(len(line), 1)
            # 2~15자, 한글 40% 이상인 줄
            if 2 <= len(line) <= 15 and korean_ratio >= 0.4:
                keywords.append(line)

    # OCR 전체 텍스트에서 한글 단어 추출
    collapsed = re.sub(r"(?<=[가-힣])\s(?=[가-힣])", "", ocr_text)
    words = re.findall(r"[가-힣]{2,}", collapsed)
    words = [w for w in words if w not in _STOPWORDS]

    # 중복 제거, 길이 2~10자 우선
    for w in words:
        if w not in keywords:
            keywords.append(w)

    # 최대 5개 (API 호출 횟수 제한)
    return keywords[:5]


def _fuzzy_match(ocr_text: str, candidates: list[str]) -> tuple[str, float]:
    """
    OCR 텍스트와 후보 약품명들의 유사도 계산 → 최고점 반환.

    여러 유사도 지표를 조합해 약 이름 특성에 맞게 가중치 적용:
    - token_set_ratio: 순서 무관 단어 매칭 (공백이 다른 경우 강함)
    - partial_ratio: 부분 문자열 매칭 (OCR이 일부만 읽은 경우 강함)
    """
    # 공백 제거 버전도 함께 비교 (OCR이 공백을 잘못 인식하는 경우 대응)
    ocr_no_space = re.sub(r"\s+", "", ocr_text)

    best_name  = candidates[0]
    best_score = 0.0

    for candidate in candidates:
        cand_no_space = re.sub(r"\s+", "", candidate)

        # 공백 포함 비교
        s1 = fuzz.token_set_ratio(ocr_text, candidate)
        s2 = fuzz.partial_ratio(ocr_text, candidate)

        # 공백 제거 비교 (OCR 공백 오류 대응)
        s3 = fuzz.ratio(ocr_no_space, cand_no_space)
        s4 = fuzz.partial_ratio(ocr_no_space, cand_no_space)

        # 가중 평균
        score = s1 * 0.3 + s2 * 0.3 + s3 * 0.2 + s4 * 0.2

        print(f"[MATCHER]   '{candidate}': {score:.1f}% "
              f"(token={s1}, partial={s2}, nospace={s3}, partial_ns={s4})")

        if score > best_score:
            best_score = score
            best_name  = candidate

    return best_name, best_score


def _score_all(ocr_text: str, candidates: list[str]) -> list[tuple[str, float]]:
    """모든 후보의 점수를 계산해 내림차순 정렬"""
    scored = []
    ocr_no_space = re.sub(r"\s+", "", ocr_text)

    for candidate in candidates:
        cand_no_space = re.sub(r"\s+", "", candidate)
        s1 = fuzz.token_set_ratio(ocr_text, candidate)
        s2 = fuzz.partial_ratio(ocr_text, candidate)
        s3 = fuzz.ratio(ocr_no_space, cand_no_space)
        s4 = fuzz.partial_ratio(ocr_no_space, cand_no_space)
        score = s1 * 0.3 + s2 * 0.3 + s3 * 0.2 + s4 * 0.2
        scored.append((candidate, score))

    return sorted(scored, key=lambda x: x[1], reverse=True)
