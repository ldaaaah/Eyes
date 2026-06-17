"""
하우스 약사 — SQLite DB 스키마 정의 및 초기화 모듈
"""

import sqlite3
import hashlib
import os
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "house_pharmacist.db"
CACHE_EXPIRE_DAYS = 30  # 식약처 API 캐시 유효기간


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # 컬럼명으로 접근 가능
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")  # 동시 읽기 성능 향상
    return conn


def init_db() -> None:
    """DB 초기화 — 테이블 생성 및 기본 데이터 삽입"""
    with get_connection() as conn:
        _create_tables(conn)
        _insert_defaults(conn)
    print(f"[DB] 초기화 완료: {DB_PATH}")


# ──────────────────────────────────────────────
# 테이블 생성
# ──────────────────────────────────────────────

def _create_tables(conn: sqlite3.Connection) -> None:

    # 1. 사용자 테이블
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            display_order INTEGER NOT NULL UNIQUE, -- 다이얼 순환 순서 (1, 2, 3...)
            birth_year    INTEGER,                 -- 고령자 여부 판단용 (연도만)
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 2. 장기복용 약물 테이블 (사용자별 약통)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS medications (
            medication_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            drug_name      TEXT    NOT NULL,        -- 약품명 (식약처 공식명)
            drug_code      TEXT,                    -- 식약처 품목코드 (없을 수 있음)
            dosage         TEXT,                    -- 용량 (예: 500mg)
            frequency      TEXT,                    -- 복약 주기 (예: 1일 3회 식후)
            start_date     TEXT,                    -- 복약 시작일 (YYYY-MM-DD)
            end_date       TEXT,                    -- 복약 종료일 (NULL = 계속 복용)
            notes          TEXT,
            created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 3. 식약처 API 응답 캐시 테이블
    conn.execute("""
        CREATE TABLE IF NOT EXISTS drug_info_cache (
            cache_id            INTEGER PRIMARY KEY AUTOINCREMENT,
            search_keyword      TEXT    NOT NULL UNIQUE,  -- 검색에 사용한 키워드
            drug_name           TEXT,                     -- 식약처 반환 공식 약품명
            drug_code           TEXT,
            efficacy            TEXT,   -- 효능효과
            dosage_info         TEXT,   -- 용법용량
            precautions         TEXT,   -- 주의사항
            contraindication    TEXT,   -- 금기 정보 (JSON 문자열)
            full_response       TEXT,   -- API 원본 JSON 전체 (보존용)
            cached_at           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            expires_at          TEXT    NOT NULL           -- 만료 시각
        )
    """)

    # 4. 금기 약물 쌍 테이블
    #    - 식약처 API 응답에서 파싱하거나 수동으로 등록
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contraindication_pairs (
            pair_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            drug_name_a   TEXT    NOT NULL,
            drug_code_a   TEXT,
            drug_name_b   TEXT    NOT NULL,
            drug_code_b   TEXT,
            severity      TEXT    NOT NULL CHECK(severity IN ('HIGH', 'MEDIUM', 'LOW')),
            description   TEXT,                          -- 금기 이유 설명
            source        TEXT    NOT NULL DEFAULT 'MFDS_API',  -- 'MFDS_API' or 'MANUAL'
            created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
            -- 순서 무관 중복 방지: (A,B) == (B,A)
            UNIQUE(drug_name_a, drug_name_b)
        )
    """)

    # 5. 스캔 이력 + 보호자 앱 전송 로그 테이블
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_logs (
            log_id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
            scan_time           TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),

            -- 인식 정보
            recognition_mode    TEXT    NOT NULL CHECK(recognition_mode IN ('QR', 'OCR')),
            raw_extracted_text  TEXT,           -- OCR/QR 원본 추출 텍스트
            recognized_drug     TEXT,           -- 최종 인식 약품명
            drug_code           TEXT,

            -- QR 보안 검증 (처방약 모드)
            qr_hash_in_code     TEXT,           -- QR에 포함된 해시값
            qr_hash_computed    TEXT,           -- 장치가 직접 계산한 해시값
            hash_verified       INTEGER,        -- 1=일치, 0=불일치, NULL=OCR모드

            -- 금기 약물 교차 검증
            conflict_detected   INTEGER NOT NULL DEFAULT 0,   -- 1=충돌 있음
            conflict_details    TEXT,           -- 충돌 약물 목록 (JSON 문자열)

            -- 처리 결과
            api_fetch_success   INTEGER NOT NULL DEFAULT 0,
            tts_script          TEXT,           -- TTS로 읽어준 최종 텍스트
            gpt_response        TEXT,           -- GPT 응답 원문

            -- 보호자 앱 전송
            sent_to_server      INTEGER NOT NULL DEFAULT 0,
            sent_at             TEXT,
            server_response     TEXT            -- 전송 결과 (HTTP 상태코드 등)
        )
    """)

    # 인덱스
    conn.execute("CREATE INDEX IF NOT EXISTS idx_medications_user ON medications(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_logs_user   ON scan_logs(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_logs_time   ON scan_logs(scan_time)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_keyword    ON drug_info_cache(search_keyword)")


# ──────────────────────────────────────────────
# 기본 데이터
# ──────────────────────────────────────────────

def _insert_defaults(conn: sqlite3.Connection) -> None:
    pass  # 기본 사용자 없음 — 실제 사용자는 별도 등록


# ──────────────────────────────────────────────
# 유틸리티: 캐시 만료 시각 계산
# ──────────────────────────────────────────────

def cache_expires_at(days: int = CACHE_EXPIRE_DAYS) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    init_db()
