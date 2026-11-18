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
    .concurrent_updates(True)
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
    webhook_url = f"{settings.public_url}/{settings.webhook_secret}"
    await telegram_app.bot.set_webhook(
        url=webhook_url,
        secret_token=settings.webhook_secret,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )
    log.info("Webhook Telegram configuré.")
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

@app.post("/{secret}")
async def telegram_webhook(
    request: Request,
    secret: str,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if secret != settings.webhook_secret or x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        payload = await request.json()
        update = Update.de_json(payload, telegram_app.bot)
        # Accuser réception rapidement, puis laisser PTB traiter la mise à jour
        # dans sa file interne. Une requête IA lente ne bloque plus le webhook.
        await telegram_app.update_queue.put(update)
        log.info("Mise à jour Telegram reçue : update_id=%s", update.update_id)
    except Exception:
        log.exception("Impossible de mettre une mise à jour Telegram en file.")
        raise HTTPException(status_code=500, detail="Webhook processing error")
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
