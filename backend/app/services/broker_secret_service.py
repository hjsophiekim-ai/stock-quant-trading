from __future__ import annotations

import base64
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from uuid import uuid4

from cryptography.fernet import Fernet

from ..auth.kis_auth import classify_token_issue_error, issue_access_token, validate_kis_inputs
from ..models.broker_account import (
    BrokerAccountResponse,
    BrokerAccountUpsertRequest,
    BrokerConnectionTestResponse,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _mask_keep_last(value: str, keep: int = 4) -> str:
    if len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


def _derive_fernet_key(raw: str) -> bytes:
    seed = (raw or "dev-only-broker-secret-key").encode("utf-8")
    digest = hashlib.sha256(seed).digest()
    return base64.urlsafe_b64encode(digest)


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class PaperSessionTokenEnsureResult:
    ok: bool
    access_token: str | None
    token_cache_hit: bool
    token_cache_source: str
    token_cache_persisted: bool
    cache_miss_reason: str | None
    token_error_code: str | None
    message: str
    failure_code: str | None  # PAPER_TOKEN_NOT_READY | TOKEN_RATE_LIMIT_WAIT | None


@dataclass
class BrokerSecretService:
    db_path: str
    encryption_seed: str
    kis_base_url: str
    kis_mock_base_url: str = ""
    timeout_sec: int = 8

    def __post_init__(self) -> None:
        self._cipher = Fernet(_derive_fernet_key(self.encryption_seed))
        db_file = Path(self.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS broker_accounts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT UNIQUE NOT NULL,
                    kis_app_key_enc TEXT NOT NULL,
                    kis_app_secret_enc TEXT NOT NULL,
                    kis_account_no_enc TEXT NOT NULL,
                    kis_account_product_code_enc TEXT NOT NULL,
                    trading_mode TEXT NOT NULL,
                    connection_status TEXT NOT NULL DEFAULT 'unknown',
                    connection_message TEXT,
                    last_tested_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    cached_access_token_enc TEXT,
                    cached_token_issued_at TEXT,
                    cached_token_api_base TEXT,
                    cached_token_app_key_tail TEXT
                )
                """
            )
            self._migrate_schema(conn)
            conn.commit()
        self._token_cache: dict[str, dict[str, object]] = {}
        self._paper_token_blocked_until: dict[str, float] = {}

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        cur = conn.execute("PRAGMA table_info(broker_accounts)")
        existing = {str(row[1]) for row in cur.fetchall()}
        alters: list[tuple[str, str]] = [
            ("cached_access_token_enc", "TEXT"),
            ("cached_token_issued_at", "TEXT"),
            ("cached_token_api_base", "TEXT"),
            ("cached_token_app_key_tail", "TEXT"),
        ]
        for col, typ in alters:
            if col not in existing:
                conn.execute(f"ALTER TABLE broker_accounts ADD COLUMN {col} {typ}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _encrypt(self, raw: str) -> str:
        return self._cipher.encrypt(raw.encode("utf-8")).decode("utf-8")

    def _decrypt(self, encrypted: str) -> str:
        return self._cipher.decrypt(encrypted.encode("utf-8")).decode("utf-8")

    def _resolve_kis_api_base(self, trading_mode: str) -> str:
        mode = (trading_mode or "paper").strip().lower()
        if mode == "paper":
            return (self.kis_mock_base_url or self.kis_base_url).rstrip("/")
        return self.kis_base_url.rstrip("/")

    def _memory_put_token(
        self,
        user_id: str,
        *,
        token: str,
        trading_mode: str,
        api_base: str,
        app_key_tail: str,
        issued_wall_iso: str,
    ) -> None:
        self._token_cache[user_id] = {
            "token": token,
            "issued_monotonic": time.monotonic(),
            "issued_wall_iso": issued_wall_iso,
            "mode": trading_mode.strip().lower(),
            "api_base": api_base,
            "app_key_tail": app_key_tail,
        }

    def _persist_token_row(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        *,
        token: str,
        api_base: str,
        app_key_tail: str,
        issued_iso: str,
    ) -> None:
        now_u = _utc_now_iso()
        conn.execute(
            """
            UPDATE broker_accounts
            SET cached_access_token_enc = ?,
                cached_token_issued_at = ?,
                cached_token_api_base = ?,
                cached_token_app_key_tail = ?,
                updated_at = ?
            WHERE user_id = ?
            """,
            (
                self._encrypt(token),
                issued_iso,
                api_base,
                app_key_tail,
                now_u,
                user_id,
            ),
        )

    def _clear_persisted_token_columns(self, conn: sqlite3.Connection, user_id: str) -> None:
        conn.execute(
            """
            UPDATE broker_accounts
            SET cached_access_token_enc = NULL,
                cached_token_issued_at = NULL,
                cached_token_api_base = NULL,
                cached_token_app_key_tail = NULL
            WHERE user_id = ?
            """,
            (user_id,),
        )

    def _token_still_valid_age(self, issued_wall_iso: str | None, issued_monotonic: float, max_age_sec: float) -> bool:
        if issued_wall_iso:
            dt = _parse_iso_utc(issued_wall_iso)
            if dt is None:
                return False
            if datetime.now(timezone.utc) - dt > timedelta(seconds=max_age_sec):
                return False
            return True
        age = time.monotonic() - issued_monotonic
        return 0 <= age <= max_age_sec

    def _read_memory_token(
        self,
        user_id: str,
        *,
        trading_mode: str,
        api_base: str,
        app_key: str,
        max_age_sec: float,
    ) -> str | None:
        ent = self._token_cache.get(user_id)
        if not ent:
            return None
        if str(ent.get("mode") or "") != str(trading_mode or "").strip().lower():
            return None
        if str(ent.get("api_base") or "") != str(api_base or ""):
            return None
        if str(ent.get("app_key_tail") or "") != _mask_keep_last(app_key):
            return None
        token = ent.get("token")
        if not isinstance(token, str) or not token:
            return None
        issued_wall = ent.get("issued_wall_iso")
        if isinstance(issued_wall, str) and issued_wall:
            mono = float(ent.get("issued_monotonic", 0.0))
            if not self._token_still_valid_age(issued_wall, mono, max_age_sec):
                return None
        else:
            try:
                mono = float(ent.get("issued_monotonic", 0.0))
            except (TypeError, ValueError):
                return None
            if not self._token_still_valid_age(None, mono, max_age_sec):
                return None
        return token

    def _hydrate_from_db(
        self,
        user_id: str,
        *,
        trading_mode: str,
        api_base: str,
        app_key: str,
        max_age_sec: float,
    ) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM broker_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        enc = row["cached_access_token_enc"]
        issued_at = row["cached_token_issued_at"]
        row_base = row["cached_token_api_base"]
        row_tail = row["cached_token_app_key_tail"]
        if not enc or not issued_at or not row_base or not row_tail:
            return None
        if str(row_base) != str(api_base or ""):
            return None
        if str(row_tail) != _mask_keep_last(app_key):
            return None
        if str(row["trading_mode"] or "").strip().lower() != str(trading_mode or "").strip().lower():
            return None
        try:
            mono = float(self._token_cache.get(user_id, {}).get("issued_monotonic", 0.0))  # type: ignore[union-attr]
        except (TypeError, ValueError):
            mono = time.monotonic()
        if not self._token_still_valid_age(str(issued_at), mono, max_age_sec):
            return None
        try:
            token = self._decrypt(str(enc))
        except Exception:
            return None
        if not token:
            return None
        self._memory_put_token(
            user_id,
            token=token,
            trading_mode=trading_mode,
            api_base=api_base,
            app_key_tail=str(row_tail),
            issued_wall_iso=str(issued_at),
        )
        return token

    def upsert_account(self, user_id: str, payload: BrokerAccountUpsertRequest) -> BrokerAccountResponse:
        now = _utc_now_iso()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM broker_accounts WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                account_id = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO broker_accounts (
                        id, user_id, kis_app_key_enc, kis_app_secret_enc, kis_account_no_enc,
                        kis_account_product_code_enc, trading_mode, connection_status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'unknown', ?, ?)
                    """,
                    (
                        account_id,
                        user_id,
                        self._encrypt(payload.kis_app_key),
                        self._encrypt(payload.kis_app_secret),
                        self._encrypt(payload.kis_account_no),
                        self._encrypt(payload.kis_account_product_code),
                        payload.trading_mode,
                        now,
                        now,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE broker_accounts
                    SET kis_app_key_enc = ?,
                        kis_app_secret_enc = ?,
                        kis_account_no_enc = ?,
                        kis_account_product_code_enc = ?,
                        trading_mode = ?,
                        connection_status = 'unknown',
                        connection_message = NULL,
                        cached_access_token_enc = NULL,
                        cached_token_issued_at = NULL,
                        cached_token_api_base = NULL,
                        cached_token_app_key_tail = NULL,
                        updated_at = ?
                    WHERE user_id = ?
                    """,
                    (
                        self._encrypt(payload.kis_app_key),
                        self._encrypt(payload.kis_app_secret),
                        self._encrypt(payload.kis_account_no),
                        self._encrypt(payload.kis_account_product_code),
                        payload.trading_mode,
                        now,
                        user_id,
                    ),
                )
            conn.commit()
        self._token_cache.pop(user_id, None)
        self._paper_token_blocked_until.pop(user_id, None)
        return self.get_account(user_id)

    def get_account(self, user_id: str) -> BrokerAccountResponse:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM broker_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("등록된 브로커 계정이 없습니다.")
        return BrokerAccountResponse(
            id=row["id"],
            user_id=row["user_id"],
            kis_app_key_masked=_mask_keep_last(self._decrypt(row["kis_app_key_enc"])),
            kis_account_no_masked=_mask_keep_last(self._decrypt(row["kis_account_no_enc"])),
            kis_account_product_code=self._decrypt(row["kis_account_product_code_enc"]),
            trading_mode=row["trading_mode"],
            connection_status=row["connection_status"],
            connection_message=row["connection_message"],
            last_tested_at=_to_dt(row["last_tested_at"]),
            updated_at=_to_dt(row["updated_at"]) or datetime.now(timezone.utc),
            created_at=_to_dt(row["created_at"]) or datetime.now(timezone.utc),
        )

    def get_plain_credentials(self, user_id: str) -> tuple[str, str, str, str, str]:
        """서버 내부(모의 자동매매 루프) 전용 — 평문 키·계좌. 외부로 반환 금지."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM broker_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("등록된 브로커 계정이 없습니다.")
        mode = str(row["trading_mode"] or "paper").strip().lower()
        return (
            self._decrypt(row["kis_app_key_enc"]),
            self._decrypt(row["kis_app_secret_enc"]),
            self._decrypt(row["kis_account_no_enc"]),
            self._decrypt(row["kis_account_product_code_enc"]),
            mode,
        )

    def delete_account(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM broker_accounts WHERE user_id = ?", (user_id,))
            conn.commit()
        self._token_cache.pop(user_id, None)
        self._paper_token_blocked_until.pop(user_id, None)

    def get_cached_token(
        self,
        *,
        user_id: str,
        trading_mode: str,
        api_base: str,
        app_key: str,
        max_age_sec: float = 50 * 60,
    ) -> str | None:
        tok, _, _ = self.resolve_cached_token(
            user_id=user_id,
            trading_mode=trading_mode,
            api_base=api_base,
            app_key=app_key,
            max_age_sec=max_age_sec,
        )
        return tok

    def resolve_cached_token(
        self,
        *,
        user_id: str,
        trading_mode: str,
        api_base: str,
        app_key: str,
        max_age_sec: float = 50 * 60,
    ) -> tuple[str | None, str, str | None]:
        """
        Returns (token, source, miss_reason) where source is memory | db | empty.
        """
        t = self._read_memory_token(
            user_id, trading_mode=trading_mode, api_base=api_base, app_key=app_key, max_age_sec=max_age_sec
        )
        if t:
            return (t, "memory", None)
        t2 = self._hydrate_from_db(
            user_id, trading_mode=trading_mode, api_base=api_base, app_key=app_key, max_age_sec=max_age_sec
        )
        if t2:
            return (t2, "db", None)
        return (None, "", "no_cached_token")

    def has_persisted_token_row(self, user_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cached_access_token_enc FROM broker_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        return bool(row and row["cached_access_token_enc"])

    def ensure_cached_token_for_paper_start(self, user_id: str) -> PaperSessionTokenEnsureResult:
        """
        Paper 시작 전: 메모리·DB 캐시 확인 후 없으면 토큰 발급 시도.
        KIS 1분 1회 제한 시 무작정 재시도하지 않음.
        """
        key, secret, _acct, _prod, mode = self.get_plain_credentials(user_id)
        api_base = self._resolve_kis_api_base(mode)
        max_age = 50 * 60

        tok, src, miss = self.resolve_cached_token(
            user_id=user_id,
            trading_mode=mode,
            api_base=api_base,
            app_key=key,
            max_age_sec=max_age,
        )
        if tok:
            return PaperSessionTokenEnsureResult(
                ok=True,
                access_token=tok,
                token_cache_hit=True,
                token_cache_source=src,
                token_cache_persisted=self.has_persisted_token_row(user_id),
                cache_miss_reason=None,
                token_error_code=None,
                message="cached token ready",
                failure_code=None,
            )

        until = float(self._paper_token_blocked_until.get(user_id, 0.0))
        if time.monotonic() < until:
            wait_sec = max(1, int(until - time.monotonic()) + 1)
            return PaperSessionTokenEnsureResult(
                ok=False,
                access_token=None,
                token_cache_hit=False,
                token_cache_source="",
                token_cache_persisted=self.has_persisted_token_row(user_id),
                cache_miss_reason=miss,
                token_error_code="TOKEN_RATE_LIMIT",
                message=f"접근 토큰 발급이 최근 제한되었습니다. 약 {wait_sec}초 후 다시 시도하세요.",
                failure_code="TOKEN_RATE_LIMIT_WAIT",
            )

        tr = issue_access_token(
            app_key=key,
            app_secret=secret,
            base_url=api_base,
            timeout_sec=max(10, self.timeout_sec),
        )
        if tr.ok and tr.access_token:
            now_iso = _utc_now_iso()
            tail = _mask_keep_last(key)
            with self._connect() as conn:
                self._persist_token_row(
                    conn,
                    user_id,
                    token=tr.access_token,
                    api_base=api_base,
                    app_key_tail=tail,
                    issued_iso=now_iso,
                )
                conn.commit()
            self._memory_put_token(
                user_id,
                token=tr.access_token,
                trading_mode=mode,
                api_base=api_base,
                app_key_tail=tail,
                issued_wall_iso=now_iso,
            )
            self._paper_token_blocked_until.pop(user_id, None)
            return PaperSessionTokenEnsureResult(
                ok=True,
                access_token=tr.access_token,
                token_cache_hit=False,
                token_cache_source="fresh_issue",
                token_cache_persisted=True,
                cache_miss_reason=miss,
                token_error_code=None,
                message="token issued for paper start",
                failure_code=None,
            )

        err = tr.error_code or "TOKEN_ISSUE_FAILED"
        if err == "TOKEN_RATE_LIMIT":
            self._paper_token_blocked_until[user_id] = time.monotonic() + 60.0
            return PaperSessionTokenEnsureResult(
                ok=False,
                access_token=None,
                token_cache_hit=False,
                token_cache_source="",
                token_cache_persisted=self.has_persisted_token_row(user_id),
                cache_miss_reason=miss,
                token_error_code="TOKEN_RATE_LIMIT",
                message=tr.message or "토큰 발급 제한(1분당 1회 등)",
                failure_code="TOKEN_RATE_LIMIT_WAIT",
            )

        return PaperSessionTokenEnsureResult(
            ok=False,
            access_token=None,
            token_cache_hit=False,
            token_cache_source="",
            token_cache_persisted=self.has_persisted_token_row(user_id),
            cache_miss_reason=miss,
            token_error_code=err,
            message=tr.message or "토큰을 확보할 수 없습니다.",
            failure_code="PAPER_TOKEN_NOT_READY",
        )

    def test_connection(self, user_id: str) -> BrokerConnectionTestResponse:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM broker_accounts WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("등록된 브로커 계정이 없습니다.")

        app_key = self._decrypt(row["kis_app_key_enc"])
        app_secret = self._decrypt(row["kis_app_secret_enc"])
        account_no = self._decrypt(row["kis_account_no_enc"])
        account_product_code = self._decrypt(row["kis_account_product_code_enc"])
        api_base = self._resolve_kis_api_base(str(row["trading_mode"]))

        status = "failed"
        message = "토큰 발급 실패"
        ok = False
        validation_issues = validate_kis_inputs(
            app_key=app_key,
            app_secret=app_secret,
            account_no=account_no,
            account_product_code=account_product_code,
            base_url=api_base,
        )
        if validation_issues:
            message = " / ".join(validation_issues)
        else:
            token_result = issue_access_token(
                app_key=app_key,
                app_secret=app_secret,
                base_url=api_base,
                timeout_sec=self.timeout_sec,
            )
            if token_result.ok:
                ok = True
                status = "success"
                message = "토큰 발급 성공 및 연결 확인 완료"
                if token_result.access_token:
                    now_iso = _utc_now_iso()
                    tail = _mask_keep_last(app_key)
                    with self._connect() as conn:
                        self._persist_token_row(
                            conn,
                            user_id,
                            token=token_result.access_token,
                            api_base=api_base,
                            app_key_tail=tail,
                            issued_iso=now_iso,
                        )
                        conn.commit()
                    self._memory_put_token(
                        user_id,
                        token=token_result.access_token,
                        trading_mode=str(row["trading_mode"]).strip().lower(),
                        api_base=api_base,
                        app_key_tail=tail,
                        issued_wall_iso=now_iso,
                    )
                    self._paper_token_blocked_until.pop(user_id, None)
            else:
                message = token_result.message
                err = token_result.error_code or ""
                if err == "TOKEN_RATE_LIMIT":
                    self._paper_token_blocked_until[user_id] = time.monotonic() + 60.0
                    tok, src, _miss = self.resolve_cached_token(
                        user_id=user_id,
                        trading_mode=str(row["trading_mode"]),
                        api_base=api_base,
                        app_key=app_key,
                        max_age_sec=50 * 60,
                    )
                    if tok:
                        ok = True
                        status = "success"
                        message = (
                            "새 토큰 발급은 KIS 1분당 1회 제한으로 보류되었습니다. "
                            "저장된 접근 토큰으로 연결 유지(캐시 "
                            + src
                            + "). 잠시 후 다시 연결 테스트하세요."
                        )
                    elif token_result.status_code == 403:
                        mode_label = "paper" if str(row["trading_mode"]).strip().lower() == "paper" else "live"
                        message = (
                            f"{message} | mode={mode_label} api_base={api_base} | "
                            "모의투자라면 trading_mode=paper 및 openapivts 도메인, "
                            "실전이라면 trading_mode=live 및 openapi 도메인/권한을 확인하세요."
                        )
                elif token_result.status_code == 403:
                    mode_label = "paper" if str(row["trading_mode"]).strip().lower() == "paper" else "live"
                    message = (
                        f"{message} | mode={mode_label} api_base={api_base} | "
                        "모의투자라면 trading_mode=paper 및 openapivts 도메인, "
                        "실전이라면 trading_mode=live 및 openapi 도메인/권한을 확인하세요."
                    )

        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE broker_accounts
                SET connection_status = ?,
                    connection_message = ?,
                    last_tested_at = ?,
                    updated_at = ?
                WHERE user_id = ?
                """,
                (status, message, now, now, user_id),
            )
            conn.commit()
        return BrokerConnectionTestResponse(ok=ok, status=status, message=message)
