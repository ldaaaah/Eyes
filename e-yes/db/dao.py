"""
하우스 약사 — DB 접근 객체 (DAO)
모든 쿼리는 이 파일을 통해서만 실행
"""

import json
from datetime import datetime
from typing import Optional
from .schema import get_connection, cache_expires_at


# ══════════════════════════════════════════════
# Users
# ══════════════════════════════════════════════

def get_all_users() -> list[dict]:
    """다이얼 순서대로 활성 사용자 전체 반환"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM users WHERE is_active = 1 ORDER BY display_order"
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_by_id(user_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ? AND is_active = 1",
            (user_id,)
        ).fetchone()
        return dict(row) if row else None


def create_user(name: str, birth_year: int = None) -> int:
    """사용자 추가 — display_order는 현재 최대값 + 1 자동 지정"""
    with get_connection() as conn:
        row = conn.execute("SELECT MAX(display_order) FROM users").fetchone()
        next_order = (row[0] or 0) + 1
        cursor = conn.execute(
            "INSERT INTO users (name, display_order, birth_year) VALUES (?, ?, ?)",
            (name, next_order, birth_year)
        )
        return cursor.lastrowid


# ══════════════════════════════════════════════
# Medications (장기복용 약물 약통)
# ══════════════════════════════════════════════

def get_user_medications(user_id: int) -> list[dict]:
    """현재 복용 중인 약물 목록 (종료일 없거나 오늘 이전)"""
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM medications
            WHERE user_id = ?
              AND (end_date IS NULL OR end_date >= ?)
            ORDER BY drug_name
        """, (user_id, today)).fetchall()
        return [dict(r) for r in rows]


def add_medication(user_id: int, drug_name: str, drug_code: str = None,
                   dosage: str = None, frequency: str = None,
                   start_date: str = None, end_date: str = None,
                   notes: str = None) -> int:
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO medications
                (user_id, drug_name, drug_code, dosage, frequency, start_date, end_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, drug_name, drug_code, dosage, frequency, start_date, end_date, notes))
        return cursor.lastrowid


def remove_medication(medication_id: int, user_id: int) -> bool:
    """소유자 확인 후 삭제"""
    with get_connection() as conn:
        cursor = conn.execute(
            "DELETE FROM medications WHERE medication_id = ? AND user_id = ?",
            (medication_id, user_id)
        )
        return cursor.rowcount > 0


# ══════════════════════════════════════════════
# Drug Info Cache (식약처 API 캐시)
# ══════════════════════════════════════════════

def get_cached_drug_info(keyword: str) -> Optional[dict]:
    """유효한 캐시가 있으면 반환, 만료/없으면 None"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        row = conn.execute("""
            SELECT * FROM drug_info_cache
            WHERE search_keyword = ? AND expires_at > ?
        """, (keyword, now)).fetchone()
        return dict(row) if row else None


def upsert_drug_cache(keyword: str, drug_name: str, drug_code: str,
                      efficacy: str, dosage_info: str, precautions: str,
                      contraindication: dict, full_response: dict) -> None:
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO drug_info_cache
                (search_keyword, drug_name, drug_code, efficacy, dosage_info,
                 precautions, contraindication, full_response, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(search_keyword) DO UPDATE SET
                drug_name        = excluded.drug_name,
                drug_code        = excluded.drug_code,
                efficacy         = excluded.efficacy,
                dosage_info      = excluded.dosage_info,
                precautions      = excluded.precautions,
                contraindication = excluded.contraindication,
                full_response    = excluded.full_response,
                cached_at        = datetime('now', 'localtime'),
                expires_at       = excluded.expires_at
        """, (
            keyword, drug_name, drug_code, efficacy, dosage_info, precautions,
            json.dumps(contraindication, ensure_ascii=False),
            json.dumps(full_response, ensure_ascii=False),
            cache_expires_at()
        ))


# ══════════════════════════════════════════════
# Contraindication (금기 약물 교차 검증)
# ══════════════════════════════════════════════

# db/dao.py 내부 수정

def check_contraindications(scanned_drug_name: str, user_id: int) -> list[dict]:
    """
    스캔된 약과 사용자의 장기복용 약물 목록을 대조해 금기 쌍 반환.
    ★수정됨: 완벽 일치가 아닌 부분 일치(LIKE) 연산을 적용해 안전성 극대화
    """
    user_drugs = [m["drug_name"] for m in get_user_medications(user_id)]
    if not user_drugs:
        return []

    conflicts = []
    with get_connection() as conn:
        for u_drug in user_drugs:
            # 스캔된 약(scanned)과 복용중인 약(u_drug)이 금기 쌍에 있는지 양방향 검색
            row = conn.execute("""
                SELECT * FROM contraindication_pairs
                WHERE (
                    (drug_name_a LIKE '%' || ? || '%' AND drug_name_b LIKE '%' || ? || '%')
                    OR 
                    (drug_name_b LIKE '%' || ? || '%' AND drug_name_a LIKE '%' || ? || '%')
                )
                ORDER BY severity DESC LIMIT 1
            """, (scanned_drug_name, u_drug, scanned_drug_name, u_drug)).fetchone()
            
            if row:
                conflicts.append(dict(row))
                
    # 중복 제거 및 위험도(severity) 높은 순으로 정렬
    conflicts = {c['pair_id']: c for c in conflicts}.values() if conflicts else []
    return sorted(list(conflicts), key=lambda x: x.get('severity', ''), reverse=True)


def add_contraindication_pair(drug_a: str, drug_b: str, severity: str,
                               description: str, code_a: str = None,
                               code_b: str = None, source: str = "MFDS_API") -> None:
    # 항상 알파벳/가나다 순으로 저장해 (A,B)==(B,A) 중복 방지
    if drug_a > drug_b:
        drug_a, drug_b = drug_b, drug_a
        code_a, code_b = code_b, code_a
    with get_connection() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO contraindication_pairs
                (drug_name_a, drug_code_a, drug_name_b, drug_code_b, severity, description, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (drug_a, code_a, drug_b, code_b, severity, description, source))


# ══════════════════════════════════════════════
# Scan Logs
# ══════════════════════════════════════════════

def insert_scan_log(user_id: int, recognition_mode: str, raw_text: str,
                    recognized_drug: str, drug_code: str = None,
                    qr_hash_in_code: str = None, qr_hash_computed: str = None,
                    hash_verified: bool = None,
                    conflict_detected: bool = False, conflict_details: list = None,
                    api_fetch_success: bool = False,
                    tts_script: str = None, gpt_response: str = None) -> int:
    hash_val = None if hash_verified is None else int(hash_verified)
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO scan_logs (
                user_id, recognition_mode, raw_extracted_text, recognized_drug,
                drug_code, qr_hash_in_code, qr_hash_computed, hash_verified,
                conflict_detected, conflict_details,
                api_fetch_success, tts_script, gpt_response
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, recognition_mode, raw_text, recognized_drug,
            drug_code, qr_hash_in_code, qr_hash_computed, hash_val,
            int(conflict_detected),
            json.dumps(conflict_details or [], ensure_ascii=False),
            int(api_fetch_success), tts_script, gpt_response
        ))
        return cursor.lastrowid


def mark_log_sent(log_id: int, server_response: str) -> None:
    with get_connection() as conn:
        conn.execute("""
            UPDATE scan_logs
            SET sent_to_server = 1,
                sent_at        = datetime('now', 'localtime'),
                server_response = ?
            WHERE log_id = ?
        """, (server_response, log_id))


def get_unsent_logs() -> list[dict]:
    """보호자 앱에 아직 전송 안 된 로그"""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT l.*, u.name as user_name
            FROM scan_logs l
            LEFT JOIN users u ON l.user_id = u.user_id
            WHERE l.sent_to_server = 0
            ORDER BY l.scan_time
        """).fetchall()
        return [dict(r) for r in rows]
