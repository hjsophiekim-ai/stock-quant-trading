from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.order_engine_routes import router as order_engine_router
from .api.risk_routes import router as risk_router
from .api.broker_routes import router as broker_router
from .api.auth_routes import router as auth_router
from .api.live_trading_routes import router as live_trading_router
from .api.paper_trading_routes import router as paper_trading_router
from .api.runtime_engine_routes import router as runtime_engine_router
from .api.screening_routes import router as screening_router
from .api.strategy_signal_routes import router as strategy_signal_router
from .api.routes.dashboard import router as dashboard_router
from .api.debug_routes import router as debug_router
from .api.routes.health import router as health_router
from .api.routes.performance import router as performance_router
from .api.routes.portfolio import router as portfolio_router
from .api.routes.trading import router as trading_router
from .core.config import get_backend_settings
from .core.storage_paths import get_resolved_storage_paths, sqlite_trading_db_file_path
from backend.app.portfolio.sync_engine import install_portfolio_sync_background

settings = get_backend_settings()
app = FastAPI(
    title="Stock Quant Backend",
    version="0.1.0",
    description="Backend API for desktop/mobile trading platform",
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


@app.on_event("startup")
def _install_risk_audit() -> None:
    import logging

    from backend.app.risk.service import install_risk_audit_from_settings

    install_risk_audit_from_settings()
    install_portfolio_sync_background(settings)

    log = logging.getLogger("backend.startup")
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


app.include_router(health_router, prefix="/api")
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
app.include_router(strategy_signal_router, prefix="/api")
app.include_router(risk_router, prefix="/api")
app.include_router(order_engine_router, prefix="/api")


@app.api_route("/", methods=["GET", "HEAD"])
def root() -> dict[str, str]:
    return {"service": "stock-quant-backend", "mode": settings.trading_mode}
