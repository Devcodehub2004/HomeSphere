from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import protect_data_routes, router as auth_router

from app.database import get_db
from app.files import router as files_router, lifespan
from app.storage import MAX_FILE_SIZE
from starlette.middleware.body_limit import RequestBodyLimitMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

app = FastAPI(
    title="HomeSphere API",
    version="1.0.0",
    description=(
        "Self-hosted personal cloud storage built with "
        "FastAPI, PostgreSQL, and Docker."
    ),
    lifespan=lifespan,
    dependencies=[Depends(protect_data_routes)],
)

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "homesphere-api"
    }
@app.get("/db-health")
def database_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "healthy",
        "database": "connected"
    }

app.include_router(auth_router)
app.include_router(files_router)
from app.cloud_features import router as cloud_router
app.include_router(cloud_router)
app.add_middleware(RequestBodyLimitMiddleware, max_body_size=MAX_FILE_SIZE + 64 * 1024)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
