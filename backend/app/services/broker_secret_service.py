from __future__ import annotations

import base64
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet

from app.clients.kis_client import KISClient, KISClientError
from app.clients.kis_parsers import balance_cash_summary, rt_cd_ok

from ..auth.kis_auth import issue_access_token, validate_kis_inputs
from ..models.broker_account import (
    BrokerAccountResponse,
    BrokerAccountUpsertRequest,
    BrokerConnectionTestResponse,
    ConnectionStatus,
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


# KIS 접근 토큰 유효 시간(보통 24h)보다 짧게 보수적으로 재발급
_CACHED_TOKEN_MAX_AGE = timedelta(hours=23)


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
    failure_code: str | None = None


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
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        self._migrate_cached_token_columns_once()

    def _migrate_cached_token_columns_once(self) -> None:
        with self._connect() as conn:
            rows = conn.execute("PRAGMA table_info(broker_accounts)").fetchall()
            col_names = {str(r[1]) for r in rows}
            if "cached_access_token_enc" not in col_names:
                conn.execute("ALTER TABLE broker_accounts ADD COLUMN cached_access_token_enc TEXT")
            if "cached_token_issued_at" not in col_names:
                conn.execute("ALTER TABLE broker_accounts ADD COLUMN cached_token_issued_at TEXT")
            conn.commit()

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
                        cached_access_token_enc, cached_token_issued_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'unknown', NULL, NULL, ?, ?)
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
                old_key = self._decrypt(row["kis_app_key_enc"])
                old_secret = self._decrypt(row["kis_app_secret_enc"])
                old_mode = str(row["trading_mode"] or "paper").strip().lower()
                new_mode = str(payload.trading_mode or "paper").strip().lower()
                invalidate_kis_oauth_cache = (
                    old_key != payload.kis_app_key
                    or old_secret != payload.kis_app_secret
                    or old_mode != new_mode
                )
                if invalidate_kis_oauth_cache:
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

    def _persist_cached_token(self, user_id: str, access_token: str) -> None:
        now = _utc_now_iso()
        enc = self._encrypt(access_token)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE broker_accounts
                SET cached_access_token_enc = ?, cached_token_issued_at = ?, updated_at = ?
                WHERE user_id = ?
                """,
                (enc, now, now, user_id),
            )
            conn.commit()

    def get_cached_token(
        self,
        *,
        user_id: str,
        trading_mode: str,
        api_base: str,
        app_key: str,
    ) -> str | None:
        """연결 테스트 등으로 저장된 암호화 토큰을 복호화해 반환(만료·키 불일치 시 None)."""
        del trading_mode, api_base, app_key  # 향후 무효화 조건 확장용
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cached_access_token_enc, cached_token_issued_at FROM broker_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None or not row["cached_access_token_enc"]:
            return None
        issued = _to_dt(row["cached_token_issued_at"])
        if issued is not None:
            if datetime.now(timezone.utc) - issued > _CACHED_TOKEN_MAX_AGE:
                return None
        try:
            return self._decrypt(row["cached_access_token_enc"])
        except Exception:
            return None

    def ensure_cached_token_for_paper_start(self, user_id: str) -> PaperSessionTokenEnsureResult:
        """Paper 세션 시작용: SQLite 캐시 우선, 없으면 OAuth 신규 발급 후 저장."""
        try:
            app_key, app_secret, _acct, _prod, mode = self.get_plain_credentials(user_id)
        except ValueError:
            return PaperSessionTokenEnsureResult(
                ok=False,
                access_token=None,
                token_cache_hit=False,
                token_cache_source="",
                token_cache_persisted=False,
                cache_miss_reason="no_broker",
                token_error_code=None,
                message="브로커 계정 없음",
                failure_code="BROKER_NOT_REGISTERED",
            )
        api_base = self._resolve_kis_api_base(mode)
        cached = self.get_cached_token(
            user_id=user_id,
            trading_mode=mode,
            api_base=api_base,
            app_key=app_key,
        )
        if cached:
            return PaperSessionTokenEnsureResult(
                ok=True,
                access_token=cached,
                token_cache_hit=True,
                token_cache_source="sqlite_encrypted",
                token_cache_persisted=True,
                cache_miss_reason=None,
                token_error_code=None,
                message="캐시된 접근 토큰 사용",
                failure_code=None,
            )
        tr = issue_access_token(
            app_key=app_key,
            app_secret=app_secret,
            base_url=api_base,
            timeout_sec=self.timeout_sec,
        )
        if not tr.ok or not tr.access_token:
            return PaperSessionTokenEnsureResult(
                ok=False,
                access_token=None,
                token_cache_hit=False,
                token_cache_source="oauth_fresh",
                token_cache_persisted=False,
                cache_miss_reason="issue_failed",
                token_error_code=tr.error_code,
                message=tr.message,
                failure_code="PAPER_TOKEN_NOT_READY",
            )
        self._persist_cached_token(user_id, tr.access_token)
        return PaperSessionTokenEnsureResult(
            ok=True,
            access_token=tr.access_token,
            token_cache_hit=False,
            token_cache_source="oauth_fresh",
            token_cache_persisted=True,
            cache_miss_reason=None,
            token_error_code=None,
            message="신규 접근 토큰 발급·저장",
            failure_code=None,
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
        api_kind = "mock" if "openapivts" in (api_base or "").lower() else "live"

        status: ConnectionStatus = "failed"
        message = "알 수 없는 오류"
        ok = False
        balance_check_ok: bool | None = None
        balance_rt_cd: str | None = None
        balance_cash_hint: str | None = None
        debug: dict[str, object] = {
            "stage": "init",
            "api_base_host": api_base,
            "api_base_kind": api_kind,
            "trading_mode": str(row["trading_mode"] or "paper"),
        }

        validation_issues = validate_kis_inputs(
            app_key=app_key,
            app_secret=app_secret,
            account_no=account_no,
            account_product_code=account_product_code,
            base_url=api_base,
        )
        if validation_issues:
            debug["stage"] = "validation_failed"
            debug["validation_issues"] = validation_issues
            message = "[입력 검증 실패] " + " / ".join(validation_issues)
        else:
            debug["stage"] = "token_request"
            token_result = issue_access_token(
                app_key=app_key,
                app_secret=app_secret,
                base_url=api_base,
                timeout_sec=self.timeout_sec,
            )
            debug["token_http_status"] = token_result.status_code
            debug["token_error_code"] = token_result.error_code
            if not token_result.ok or not token_result.access_token:
                debug["stage"] = "token_http_failed"
                message = (
                    f"[KIS OAuth 토큰 실패 · {api_kind}] HTTP={token_result.status_code or '—'} "
                    f"code={token_result.error_code} — {token_result.message}"
                )
            else:
                debug["stage"] = "balance_request"
                client = KISClient(
                    base_url=api_base,
                    timeout_sec=self.timeout_sec,
                    max_retries=2,
                    token_provider=lambda: token_result.access_token or "",
                    app_key=app_key,
                    app_secret=app_secret,
                    live_execution_unlocked=False,
                )
                try:
                    bal = client.get_balance(account_no, account_product_code)
                except KISClientError as exc:
                    debug["stage"] = "balance_exception"
                    debug["balance_error"] = str(exc)
                    ctx = getattr(exc, "kis_context", {}) or {}
                    if ctx:
                        debug["kis_context"] = {k: ctx.get(k) for k in ("path", "tr_id", "http_status") if ctx.get(k)}
                    message = f"[잔고조회 실패 · {api_kind}] 토큰은 성공했으나 잔고 API 오류: {exc}"
                    balance_check_ok = False
                else:
                    balance_rt_cd = str(bal.get("rt_cd", ""))
                    debug["balance_rt_cd"] = balance_rt_cd
                    if rt_cd_ok(bal):
                        balance_check_ok = True
                        snap = balance_cash_summary(bal)
                        cash_bits = [f"{k}={v}" for k, v in snap.items() if v is not None and str(v).strip() != ""]
                        balance_cash_hint = ", ".join(cash_bits[:4]) if cash_bits else "(요약 필드 없음)"
                        ok = True
                        status = "success"
                        debug["stage"] = "success"
                        message = f"[성공 · {api_kind}] 토큰·잔고조회 — {balance_cash_hint}"
                        if token_result.access_token:
                            self._persist_cached_token(user_id, token_result.access_token)
                    else:
                        balance_check_ok = False
                        debug["stage"] = "balance_rt_cd_failed"
                        message = (
                            f"[잔고 비정상 응답 · {api_kind}] rt_cd={balance_rt_cd}. "
                            "키·계좌·모의/실전 호스트를 확인하세요."
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
        return BrokerConnectionTestResponse(
            ok=ok,
            status=status,
            message=message,
            balance_check_ok=balance_check_ok,
            balance_rt_cd=balance_rt_cd,
            balance_cash_hint=balance_cash_hint,
            debug=debug,
        )
