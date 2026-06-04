import asyncio
import contextlib
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from app.bot.handlers import payment as payment_handler
from app.bot.handlers import start as start_handler
from app.bot.middleware import DbSessionMiddleware
from app.config import settings
from app.database import AsyncSessionFactory, engine, Base
from app.routers import auth, messages, payments, users, ws, generate


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware(AsyncSessionFactory))
    dp.include_router(start_handler.router)
    dp.include_router(payment_handler.router)

    await bot.delete_webhook(drop_pending_updates=True)
    polling_task = asyncio.create_task(
        dp.start_polling(bot, polling_timeout=5, handle_signals=False)
    )

    yield

    polling_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await polling_task
    await bot.session.close()


app = FastAPI(lifespan=lifespan)


@app.options("/{path:path}")
async def options_handler(request: Request) -> Response:
    requested_headers = request.headers.get("access-control-request-headers", "")
    headers = {"Access-Control-Allow-Headers": requested_headers} if requested_headers else {}
    return Response(status_code=200, headers=headers)


app.include_router(auth.router)
app.include_router(payments.router)
app.include_router(messages.router)
app.include_router(users.router)
app.include_router(ws.router)
app.include_router(generate.router)
