from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(email: str, password: str) -> dict[str, str]:
    # JWT issuance placeholder. Replace with real user auth/DB verification.
    _ = (email, password)
    expire_at = datetime.now(timezone.utc) + timedelta(hours=8)
    return {"access_token": "jwt-placeholder", "token_type": "bearer", "expires_at": expire_at.isoformat()}
