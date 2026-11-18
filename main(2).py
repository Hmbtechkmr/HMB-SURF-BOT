import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
)
from bot.config import settings
from bot.database import Database
from bot import handlers

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("hmb-surf-bot")

db = Database(settings.database_path)
telegram_app = (
    Application.builder()
    .token(settings.bot_token)
    .updater(None)
    .concurrent_updates(False)
    .build()
)
telegram_app.bot_data.update({
    "admin_id": settings.admin_id,
    "db": db,
    "settings": settings,
})

telegram_app.add_handler(CommandHandler("start", handlers.start))
telegram_app.add_handler(CommandHandler("help", handlers.help_command))
telegram_app.add_handler(CommandHandler("cancel", handlers.cancel))
telegram_app.add_handler(CommandHandler("admin", handlers.admin))
telegram_app.add_handler(CommandHandler("stats", handlers.stats))
telegram_app.add_handler(CommandHandler("orders", handlers.orders))
telegram_app.add_handler(CommandHandler("deliver", handlers.deliver))
telegram_app.add_handler(CommandHandler("broadcast", handlers.broadcast))
telegram_app.add_handler(CallbackQueryHandler(handlers.admin_decision, pattern=r"^admin:"))
telegram_app.add_handler(CallbackQueryHandler(handlers.callbacks))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handlers.payment_photo))
telegram_app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handlers.voice_message))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_message))

async def telegram_error_handler(update, context):
    log.error("Erreur pendant le traitement Telegram (update_id=%s)",
              getattr(update, "update_id", "inconnu"), exc_info=context.error)

telegram_app.add_error_handler(telegram_error_handler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await telegram_app.initialize()
    await telegram_app.start()
    # Endpoint fixe : le secret est vérifié uniquement dans l’en-tête Telegram.
    webhook_url = f"{settings.public_url}/telegram/webhook"
    await telegram_app.bot.set_webhook(
        url=webhook_url,
        secret_token=settings.webhook_secret,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )
    log.info("Webhook Telegram configuré sur %s/telegram/webhook", settings.public_url)
    # Vérifie ce que Telegram a réellement enregistré (sans afficher le token).
    try:
        info = await telegram_app.bot.get_webhook_info()
        log.info(
            "État webhook Telegram : url=%s, pending=%s, last_error=%s",
            info.url, info.pending_update_count, info.last_error_message or "aucune"
        )
    except Exception:
        log.exception("Impossible de vérifier le webhook Telegram au démarrage.")
    yield
    await telegram_app.bot.delete_webhook()
    await telegram_app.stop()
    await telegram_app.shutdown()

app = FastAPI(title="HMB SURF BOT", version="1.0.0", lifespan=lifespan)

@app.get("/")
async def home():
    return {"service": "HMB SURF BOT", "status": "online"}

@app.get("/health")
async def health():
    return {"status": "ok", "service": "HMB SURF BOT"}

@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        payload = await request.json()
        update = Update.de_json(payload, telegram_app.bot)
        # Accuser réception rapidement, puis laisser PTB traiter la mise à jour
        # dans sa file interne. Une requête IA lente ne bloque plus le webhook.
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
            "webhook_path_ok": info.url.endswith("/telegram/webhook"),
            "pending_updates": info.pending_update_count,
            "last_error_date": info.last_error_date.isoformat() if info.last_error_date else None,
            "last_error_message": info.last_error_message,
        }
    except Exception:
        log.exception("Échec du diagnostic Telegram.")
        raise HTTPException(status_code=503, detail="Telegram status unavailable")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
