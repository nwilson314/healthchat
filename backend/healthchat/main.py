from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from healthchat.config import settings
from loguru import logger

from healthchat.ws import chat_socket


app = FastAPI()


app.include_router(chat_socket.router)


if settings.ENVIRONMENT == "dev":
    logger.info("Running in development mode - CORS enabled for development origins")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",  # Local development
            "http://localhost:5173",  # Vite default port
            "http://localhost:5174",  # Vite default port
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "accept"],
        expose_headers=["*"],
        max_age=3600,  # Cache preflight requests for 1 hour
    )
else:
    logger.info("Running in production mode - CORS enabled for production origins")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:5174",
            "https://healthchat-flame.vercel.app/"
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "accept"],
        expose_headers=["*"],
        max_age=3600,  # Cache preflight requests for 1 hour
    )


@app.get("/")
async def root():
    return {
        "message": "Hello, World!",
    }