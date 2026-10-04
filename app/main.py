from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"/api/v1/openapi.json" if settings.ENVIRONMENT == "local" else None,
)

# Configuración de CORS para el Frontend local en React
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "environment": settings.ENVIRONMENT,
        "project": settings.PROJECT_NAME
    }