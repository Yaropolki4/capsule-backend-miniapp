import asyncio
import contextlib
import logging
import time
import traceback
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

from app.bot.handlers import payment as payment_handler
from app.bot.handlers import photo as photo_handler
from app.bot.handlers import rating as rating_handler
from app.bot.handlers import start as start_handler
from app.bot.middleware import DbSessionMiddleware
from app.config import settings
from app.database import AsyncSessionFactory, engine, Base
from app.routers import auth, messages, payments, users, ws, generate, feedback, media
from app.services.notify import notify_admin, format_error_message


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware(AsyncSessionFactory))
    dp.include_router(start_handler.router)
    dp.include_router(payment_handler.router)
    dp.include_router(rating_handler.router)
    dp.include_router(photo_handler.router)

    await bot.delete_webhook(drop_pending_updates=True)
    polling_task = asyncio.create_task(
        dp.start_polling(bot, polling_timeout=5, handle_signals=False)
    )

    logger.info("App started | environment=%s", settings.environment)

    yield

    polling_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await polling_task
    await bot.session.close()
    logger.info("App shut down")


app = FastAPI(lifespan=lifespan)

if settings.environment != "development":
    logger.warning("CORS origins: [%s] | environment: %s", settings.miniapp_url, settings.environment)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.miniapp_url.rstrip("/")],
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    duration_ms = (time.monotonic() - start) * 1000
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(
        level,
        "%s %s → %s (%.0fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code >= 500:
        logger.error(
            "HTTPException %s: %s %s — %s",
            exc.status_code, request.method, request.url.path, exc.detail,
        )
        msg = format_error_message(request.method, request.url.path, exc.status_code, str(exc.detail))
        asyncio.create_task(notify_admin(msg, settings.bot_token, settings.admin_chat_id))
    else:
        logger.warning(
            "HTTPException %s: %s %s — %s",
            exc.status_code, request.method, request.url.path, exc.detail,
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    logger.exception("Unhandled exception: %s %s", request.method, request.url.path)
    msg = format_error_message(
        request.method, request.url.path, 500,
        f"{type(exc).__name__}: {exc}", tb,
    )
    asyncio.create_task(notify_admin(msg, settings.bot_token, settings.admin_chat_id))
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(auth.router)
app.include_router(payments.router)
app.include_router(messages.router)
app.include_router(users.router)
app.include_router(ws.router)
app.include_router(generate.router)
app.include_router(feedback.router)
app.include_router(media.router)


@app.get("/debug/error-test")
async def error_test():
    """Intentional 500 to verify Telegram error alerts."""
    raise RuntimeError("Test error — Telegram alert check")
