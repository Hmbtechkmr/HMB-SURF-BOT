import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          MessageHandler, filters)

from bot import handlers
from bot.ai import list_models
from bot.config import settings
from bot.database import Database
from bot.text import esc

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("hmb-surf-bot")

WEBHOOK_PATH = "/telegram/webhook"

db = Database(settings.database_path)

telegram_app = (
    Application.builder().token(settings.bot_token).updater(None)
    .concurrent_updates(True).build()
)


async def set_webhook() -> None:
    await telegram_app.bot.set_webhook(
        url=f"{settings.public_url}{WEBHOOK_PATH}",
        secret_token=settings.webhook_secret,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


telegram_app.bot_data.update({
    "admin_id": settings.admin_id, "db": db,
    "settings": settings, "set_webhook": set_webhook,
})

for name, func in (
    ("start", handlers.start), ("help", handlers.help_command),
    ("cgu", handlers.cgu), ("cancel", handlers.cancel),
    ("lang", handlers.lang_command), ("admin", handlers.admin),
    ("stats", handlers.stats), ("orders", handlers.orders),
    ("deliver", handlers.deliver), ("cancelorder", handlers.cancelorder),
    ("refund", handlers.refund), ("note", handlers.note),
    ("client", handlers.client), ("stock", handlers.stock),
    ("addstock", handlers.addstock), ("addfaq", handlers.addfaq),
    ("broadcast", handlers.broadcast), ("backup", handlers.backup),
    ("diag", handlers.diag), ("setwebhook", handlers.setwebhook),
    ("voicetest", handlers.voicetest),
):
    telegram_app.add_handler(CommandHandler(name, func))

telegram_app.add_handler(CallbackQueryHandler(handlers.admin_decision, pattern=r"^admin:"))
telegram_app.add_handler(CallbackQueryHandler(handlers.callbacks))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handlers.payment_photo))
telegram_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handlers.voice_message))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_message))

_error_times: list[float] = []


async def telegram_error_handler(update, context):
    log.error("Erreur Telegram (update_id=%s)", getattr(update, "update_id", "?"),
              exc_info=context.error)
    now = asyncio.get_running_loop().time()
    _error_times.append(now)
    while _error_times and now - _error_times[0] > 600:
        _error_times.pop(0)
    if len(_error_times) == 3:
        try:
            await telegram_app.bot.send_message(
                settings.admin_id,
                f"⚠️ 3 erreurs en 10 min. Dernière : {esc(str(context.error))[:300]}",
                parse_mode="HTML")
        except Exception:
            pass


telegram_app.add_error_handler(telegram_error_handler)


async def webhook_watchdog():
    while True:
        await asyncio.sleep(settings.webhook_watchdog_seconds)
        try:
            info = await telegram_app.bot.get_webhook_info()
            if not info.url:
                await set_webhook()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Watchdog webhook")


async def keepalive_loop():
    url = f"{settings.public_url}/health"
    while True:
        await asyncio.sleep(settings.keepalive_seconds)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                await client.get(url)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


async def expiry_loop():
    while True:
        await asyncio.sleep(300)
        try:
            rows = await asyncio.to_thread(db.expired_orders, settings.order_ttl_minutes)
            for order in rows:
                if await asyncio.to_thread(db.set_status, order["id"], "expired", "awaiting_proof"):
                    lang = await asyncio.to_thread(db.get_lang, order["user_id"]) or "fr"
                    await telegram_app.bot.send_message(
                        order["user_id"],
                        handlers.t(lang, "expired", code=esc(order["code"])), parse_mode="HTML")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Boucle expiration")


async def reminder_loop():
    while True:
        await asyncio.sleep(300)
        try:
            rows = await asyncio.to_thread(db.orders_to_remind, settings.reminder_minutes)
            for order in rows:
                await asyncio.to_thread(db.mark_reminded, order["id"])
                lang = await asyncio.to_thread(db.get_lang, order["user_id"]) or "fr"
                await telegram_app.bot.send_message(
                    order["user_id"],
                    handlers.t(lang, "reminder", code=esc(order["code"]),
                               offer=esc(order["offer_label"][:40])), parse_mode="HTML")
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Boucle relance")


async def purge_loop():
    while True:
        await asyncio.sleep(86400)
        try:
            removed = await asyncio.to_thread(db.purge_seen_updates, 7)
            old = await asyncio.to_thread(db.purge_conversations, 90)
            log.info("Purge : %s updates, %s messages.", removed, old)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Boucle purge")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await telegram_app.initialize()
    await telegram_app.start()
    await set_webhook()
    log.info("Webhook configuré. Token diagnostic : %s", settings.diag_token)

    # Préchauffe Piper : le premier vocal utilisateur est plus rapide.
    asyncio.create_task(asyncio.to_thread(
        handlers.synthesize_piper, "Bonjour", "fr", settings))

    tasks = [asyncio.create_task(webhook_watchdog()),
             asyncio.create_task(expiry_loop()),
             asyncio.create_task(reminder_loop()),
             asyncio.create_task(purge_loop())]
    if settings.keepalive_enabled:
        tasks.append(asyncio.create_task(keepalive_loop()))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(title="HMB SURF BOT", version="2.2.0", lifespan=lifespan)


def _check(key):
    if key != settings.diag_token:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.api_route("/", methods=["GET", "HEAD"])
async def home():
    return {"service": "HMB SURF BOT", "status": "online"}


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    try:
        await asyncio.to_thread(db.stats)
    except Exception:
        raise HTTPException(status_code=503, detail="db")
    try:
        await telegram_app.bot.get_me()
    except Exception:
        raise HTTPException(status_code=503, detail="telegram")
    return {"status": "ok"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        update = Update.de_json(await request.json(), telegram_app.bot)
        await telegram_app.update_queue.put(update)
    except Exception:
        log.exception("Mise en file impossible")
        raise HTTPException(status_code=500, detail="error")
    return {"ok": True}


@app.get("/telegram/status")
async def telegram_status(k: str = ""):
    _check(k)
    info = await telegram_app.bot.get_webhook_info()
    return {"webhook_configured": bool(info.url), "pending": info.pending_update_count,
            "last_error": info.last_error_message}


@app.get("/ai/status")
async def ai_status(k: str = ""):
    _check(k)
    result = {"model": settings.groq_chat_model, "key": bool(settings.groq_api_key)}
    try:
        models = await list_models(settings.groq_api_key)
        result["ok"] = True
        result["model_available"] = settings.groq_chat_model in models
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)[:200]
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
