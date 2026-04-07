from fastapi import FastAPI

from .api.broker_routes import router as broker_router
from .api.auth_routes import router as auth_router
from .api.live_trading_routes import router as live_trading_router
from .api.paper_trading_routes import router as paper_trading_router
from .api.routes.dashboard import router as dashboard_router
from .api.routes.health import router as health_router
from .api.routes.performance import router as performance_router
from .api.routes.portfolio import router as portfolio_router
from .api.routes.trading import router as trading_router
from .core.config import get_backend_settings

settings = get_backend_settings()
app = FastAPI(
    title="Stock Quant Backend",
    version="0.1.0",
    description="Backend API for desktop/mobile trading platform",
)

app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(broker_router, prefix="/api")
app.include_router(live_trading_router, prefix="/api")
app.include_router(paper_trading_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(trading_router, prefix="/api")
app.include_router(portfolio_router, prefix="/api")
app.include_router(performance_router, prefix="/api")


@app.get("/")
def root() -> dict[str, str]:
    return {"service": "stock-quant-backend", "mode": settings.trading_mode}
