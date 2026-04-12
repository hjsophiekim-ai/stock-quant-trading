from __future__ import annotations

import base64
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
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

        status: ConnectionStatus = "failed"
        message = "토큰 발급 실패"
        ok = False
        balance_check_ok: bool | None = None
        balance_rt_cd: str | None = None
        balance_cash_hint: str | None = None
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
            if not token_result.ok or not token_result.access_token:
                message = token_result.message
            else:
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
                    message = f"토큰은 성공했으나 잔고조회 실패: {exc}"
                    balance_check_ok = False
                else:
                    balance_rt_cd = str(bal.get("rt_cd", ""))
                    if rt_cd_ok(bal):
                        balance_check_ok = True
                        snap = balance_cash_summary(bal)
                        cash_bits = [f"{k}={v}" for k, v in snap.items() if v is not None and str(v).strip() != ""]
                        balance_cash_hint = ", ".join(cash_bits[:4]) if cash_bits else "(요약 필드 없음)"
                        ok = True
                        status = "success"
                        message = f"토큰·잔고조회 성공 — {balance_cash_hint}"
                    else:
                        balance_check_ok = False
                        message = f"잔고조회 비정상 응답(rt_cd={balance_rt_cd}). 키·계좌·모의/실전 호스트를 확인하세요."

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
        )
