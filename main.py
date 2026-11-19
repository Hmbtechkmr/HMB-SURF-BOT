import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
)
from bot.ai import list_models
from bot.config import settings
from bot.database import Database
from bot import handlers

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("hmb-surf-bot")

WEBHOOK_PATH = "/telegram/webhook"

db = Database(settings.database_path)

telegram_app = (
    Application.builder()
    .token(settings.bot_token)
    .updater(None)
    # True : un appel IA lent ne bloque plus les autres utilisateurs.
    # Les accès SQLite sont exécutés dans des threads (voir handlers.py).
    .concurrent_updates(True)
    .build()
)


async def set_webhook() -> None:
    """Pose (ou repose) le webhook Telegram."""
    await telegram_app.bot.set_webhook(
        url=f"{settings.public_url}{WEBHOOK_PATH}",
        secret_token=settings.webhook_secret,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


telegram_app.bot_data.update({
    "admin_id": settings.admin_id,
    "db": db,
    "settings": settings,
    "set_webhook": set_webhook,
})

telegram_app.add_handler(CommandHandler("start", handlers.start))
telegram_app.add_handler(CommandHandler("help", handlers.help_command))
telegram_app.add_handler(CommandHandler("cancel", handlers.cancel))
telegram_app.add_handler(CommandHandler("admin", handlers.admin))
telegram_app.add_handler(CommandHandler("stats", handlers.stats))
telegram_app.add_handler(CommandHandler("orders", handlers.orders))
telegram_app.add_handler(CommandHandler("deliver", handlers.deliver))
telegram_app.add_handler(CommandHandler("broadcast", handlers.broadcast))
telegram_app.add_handler(CommandHandler("setwebhook", handlers.setwebhook))
telegram_app.add_handler(CallbackQueryHandler(handlers.admin_decision, pattern=r"^admin:"))
telegram_app.add_handler(CallbackQueryHandler(handlers.callbacks))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handlers.payment_photo))
telegram_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handlers.voice_message))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_message))


async def telegram_error_handler(update, context):
    log.error("Erreur pendant le traitement Telegram (update_id=%s)",
              getattr(update, "update_id", "inconnu"), exc_info=context.error)


telegram_app.add_error_handler(telegram_error_handler)


async def webhook_watchdog() -> None:
    """Repose le webhook s'il a disparu (arrêt concurrent, redéploiement)."""
    while True:
        await asyncio.sleep(settings.webhook_watchdog_seconds)
        try:
            info = await telegram_app.bot.get_webhook_info()
            if not info.url:
                log.warning("Webhook absent : rétablissement automatique.")
                await set_webhook()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Watchdog webhook : vérification impossible.")


async def keepalive_loop() -> None:
    """Auto-ping pour empêcher la mise en veille Render (plan gratuit)."""
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await telegram_app.initialize()
    await telegram_app.start()

    await set_webhook()
    log.info("Webhook Telegram configuré sur %s%s", settings.public_url, WEBHOOK_PATH)
    try:
        info = await telegram_app.bot.get_webhook_info()
        log.info(
            "État webhook : url=%s, pending=%s, last_error=%s",
            info.url, info.pending_update_count, info.last_error_message or "aucune"
        )
    except Exception:
        log.exception("Impossible de vérifier le webhook au démarrage.")

    tasks = [asyncio.create_task(webhook_watchdog())]
    if settings.keepalive_enabled:
        tasks.append(asyncio.create_task(keepalive_loop()))

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Pas de delete_webhook ici : le webhook doit survivre aux redémarrages
        # et aux mises en veille, sinon plus rien ne peut réveiller le service.
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(title="HMB SURF BOT", version="1.2.0", lifespan=lifespan)


@app.api_route("/", methods=["GET", "HEAD"])
async def home():
    return {"service": "HMB SURF BOT", "status": "online"}


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok", "service": "HMB SURF BOT"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        payload = await request.json()
        update = Update.de_json(payload, telegram_app.bot)
        # Accusé de réception immédiat, traitement en file interne PTB.
        await telegram_app.update_queue.put(update)
        log.info("MISE À JOUR REÇUE ET MISE EN FILE : update_id=%s", update.update_id)
    except Exception:
        log.exception("Impossible de mettre une mise à jour Telegram en file.")
        raise HTTPException(status_code=500, detail="Webhook processing error")
    return {"ok": True}


@app.get("/telegram/status")
async def telegram_status():
    """Diagnostic sans exposer le token ni le secret du webhook."""
    try:
        info = await telegram_app.bot.get_webhook_info()
        return {
            "service": "HMB SURF BOT",
            "webhook_configured": bool(info.url),
            "webhook_path_ok": info.url.endswith(WEBHOOK_PATH),
            "pending_updates": info.pending_update_count,
            "last_error_date": info.last_error_date.isoformat() if info.last_error_date else None,
            "last_error_message": info.last_error_message,
        }
    except Exception:
        log.exception("Échec du diagnostic Telegram.")
        raise HTTPException(status_code=503, detail="Telegram status unavailable")


@app.get("/ai/status")
async def ai_status():
    """Diagnostic IA : quels modèles la clé autorise réellement."""
    result = {
        "gemini_key_present": bool(settings.gemini_api_key),
        "groq_key_present": bool(settings.groq_api_key),
        "configured_model": settings.gemini_model,
    }
    try:
        models = await list_models(settings.gemini_api_key)
        result["gemini_ok"] = True
        result["flash_models_available"] = [
            m.split("/")[-1] for m in models if "flash" in m
        ][:20]
    except Exception as exc:
        result["gemini_ok"] = False
        result["error"] = str(exc)[:300]
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
