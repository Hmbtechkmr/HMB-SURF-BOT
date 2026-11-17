import logging
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from bot.config import load_settings
from bot.database import Database
from bot import handlers

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hmb-surf-bot")
settings = load_settings()
db = Database(settings.database_path)

telegram_app = Application.builder().token(settings.bot_token).updater(None).build()
telegram_app.bot_data["admin_id"] = settings.admin_id
telegram_app.bot_data["db"] = db
telegram_app.add_handler(CommandHandler("start", handlers.start))
telegram_app.add_handler(CommandHandler("deliver", handlers.deliver))
telegram_app.add_handler(CallbackQueryHandler(handlers.admin_decision, pattern=r"^admin:"))
telegram_app.add_handler(CallbackQueryHandler(handlers.callbacks))
telegram_app.add_handler(MessageHandler(filters.PHOTO, handlers.payment_photo))

app = FastAPI(title="HMB SURF BOT")

@app.on_event("startup")
async def startup():
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.bot.set_webhook(
        url=f"{settings.public_url}/{settings.webhook_secret}",
        secret_token=settings.webhook_secret,
        allowed_updates=Update.ALL_TYPES
    )
    log.info("Webhook configuré.")

@app.on_event("shutdown")
async def shutdown():
    await telegram_app.bot.delete_webhook()
    await telegram_app.stop()
    await telegram_app.shutdown()

@app.get("/health")
async def health():
    return {"status": "ok", "service": "HMB SURF BOT"}

@app.post("/{secret}")
async def telegram_webhook(request: Request, secret: str, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if secret != settings.webhook_secret or x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        payload = await request.json()
        update = Update.de_json(payload, telegram_app.bot)
        await telegram_app.process_update(update)
    except Exception:
        log.exception("Erreur pendant le traitement d'une mise à jour Telegram.")
        return JSONResponse(status_code=200, content={"ok": True})
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
