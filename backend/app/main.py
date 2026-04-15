from __future__ import annotations

import logging
import sys
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.routes.health import router as health_router
from .api.version_routes import router as version_router
from .core.config import get_backend_settings

log = logging.getLogger("backend.main")

_stack_lock = threading.Lock()
_full_stack_ready = False


def _ensure_full_stack(app: FastAPI) -> None:
    """무거운 라우터 import + 리스크/포트폴리오 기동을 한 번만(헬스·버전 경로는 호출 안 함)."""
    global _full_stack_ready

    if _full_stack_ready:
        return
    with _stack_lock:
        if _full_stack_ready:
            return

        from .api.order_engine_routes import router as order_engine_router
        from .api.risk_routes import router as risk_router
        from .api.broker_routes import router as broker_router
        from .api.auth_routes import router as auth_router
        from .api.live_trading_routes import router as live_trading_router
        from .api.paper_trading_routes import router as paper_trading_router
        from .api.runtime_engine_routes import router as runtime_engine_router
        from .api.screening_routes import router as screening_router
        from .api.symbol_search_routes import router as symbol_search_router
        from .api.strategy_signal_routes import router as strategy_signal_router
        from .api.routes.dashboard import router as dashboard_router
        from .api.debug_routes import router as debug_router
        from .api.routes.performance import router as performance_router
        from .api.routes.portfolio import router as portfolio_router
        from .api.routes.trading import router as trading_router

        app.include_router(debug_router, prefix="/api")
        app.include_router(auth_router, prefix="/api")
        app.include_router(broker_router, prefix="/api")
        app.include_router(live_trading_router, prefix="/api")
        app.include_router(paper_trading_router, prefix="/api")
        app.include_router(dashboard_router, prefix="/api")
        app.include_router(trading_router, prefix="/api")
        app.include_router(portfolio_router, prefix="/api")
        app.include_router(performance_router, prefix="/api")
        app.include_router(runtime_engine_router, prefix="/api")
        app.include_router(screening_router, prefix="/api")
        app.include_router(symbol_search_router, prefix="/api")
        app.include_router(strategy_signal_router, prefix="/api")
        app.include_router(risk_router, prefix="/api")
        app.include_router(order_engine_router, prefix="/api")

        from app.config import get_settings as get_app_settings

        get_app_settings.cache_clear()

        from backend.app.core.storage_paths import get_resolved_storage_paths, sqlite_trading_db_file_path
        from backend.app.core.version_info import get_backend_version_payload
        from backend.app.portfolio.sync_engine import install_portfolio_sync_background
        from backend.app.risk.service import install_risk_audit_from_settings

        settings = get_backend_settings()
        install_risk_audit_from_settings()
        install_portfolio_sync_background(settings)

        paths = get_resolved_storage_paths()
        trade_sql = sqlite_trading_db_file_path(settings.database_url)
        log.info(
            "storage paths: backend_data_dir=%s users=%s broker_db=%s trading_sqlite=%s database_url=%s",
            paths.backend_data_dir,
            paths.auth_users_path,
            paths.broker_accounts_db_path,
            trade_sql or "(non-sqlite or memory)",
            settings.database_url.split("@")[-1] if "@" in settings.database_url else settings.database_url,
        )
        ver = get_backend_version_payload(app_version=app.version)
        log.info(
            "runtime info: git_sha=%s build_time=%s python=%s",
            ver.get("git_sha", ""),
            ver.get("build_time", ""),
            sys.executable,
        )

        _full_stack_ready = True


def _is_lightweight_probe_path(path: str) -> bool:
    if path in ("/", ""):
        return True
    if path.startswith("/api/health"):
        return True
    if path.startswith("/api/ready"):
        return True
    if path.startswith("/api/version"):
        return True
    if path in ("/docs", "/redoc", "/openapi.json"):
        return True
    return False


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """uvicorn 바인딩 직후 startup 에 무거운 작업을 두지 않음(Render 헬스체크)."""
    yield


settings = get_backend_settings()
app = FastAPI(
    title="Stock Quant Backend",
    version="0.1.0",
    description="Backend API for desktop/mobile trading platform",
    lifespan=_lifespan,
)


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(_request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 검증 오류를 앱에 표시하기 쉬운 한 줄 메시지로 감쌉니다."""
    errs = exc.errors()
    parts: list[str] = []
    for e in errs[:5]:
        loc = " → ".join(str(x) for x in e.get("loc", []) if x not in ("body", "query"))
        msg = str(e.get("msg", ""))
        if loc:
            parts.append(f"{loc}: {msg}")
        else:
            parts.append(msg)
    detail = "입력값을 확인해주세요. " + ("; ".join(parts) if parts else "형식이 올바르지 않습니다.")
    return JSONResponse(status_code=422, content={"detail": detail})


@app.middleware("http")
async def _lazy_load_heavy_stack(request: Request, call_next):
    """Render 등: /api/health 가 pandas 등 전역 import 를 기다리지 않게 한다."""
    if not _is_lightweight_probe_path(request.url.path):
        _ensure_full_stack(app)
    return await call_next(request)


app.include_router(health_router, prefix="/api")
app.include_router(version_router, prefix="/api")


@app.api_route("/", methods=["GET", "HEAD"])
def root() -> dict[str, str]:
    return {"service": "stock-quant-backend", "mode": settings.trading_mode}
