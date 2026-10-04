# app/main.py

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.db.base import Base  # Carga todos los modelos registrados
from app.db.session import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestión del ciclo de vida de la aplicación.
    Crea las tablas automáticamente en la base de datos si aún no existen.
    """
    logger.info("🚀 Iniciando la aplicación...")
    try:
        logger.info("📦 Verificando y creando tablas en la base de datos...")
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Tablas creadas/verificadas correctamente.")
    except Exception as e:
        logger.error(f"❌ Error al inicializar las tablas de la base de datos: {e}")

    yield

    logger.info("🛑 Cerrando la aplicación...")


app = FastAPI(
    title="Kidobank API",
    description="Backend para la PWA de simulación bancaria familiar",
    version="1.0.0",
    lifespan=lifespan,
)

# Configuración de CORS
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health Check"])
async def health_check():
    return {"status": "ok", "app_name": app.title}


app.include_router(api_router, prefix="/api/v1")