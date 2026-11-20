import os
import re
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_id: int
    webhook_secret: str
    public_url: str
    port: int
    database_path: str
    groq_api_key: str
    groq_stt_model: str
    groq_chat_model: str
    piper_python: str
    piper_fr_model: str
    piper_fr_config: str
    piper_en_model: str
    piper_en_config: str
    ai_enabled: bool
    voice_reply_enabled: bool
    max_voice_seconds: int
    log_level: str
    webhook_watchdog_seconds: int
    keepalive_enabled: bool
    keepalive_seconds: int
    diag_token: str
    order_ttl_minutes: int
    reminder_minutes: int
    low_stock_threshold: int
    tts_cache_dir: str


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    admin = os.getenv("ADMIN_ID", "").strip()
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    public_url = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL") or "").strip().rstrip("/")
    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()

    if not token:
        raise RuntimeError("BOT_TOKEN manquant dans Render > Environment.")
    if not admin.isdigit():
        raise RuntimeError("ADMIN_ID doit être ton identifiant Telegram numérique.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
        raise RuntimeError("WEBHOOK_SECRET manquant ou invalide.")
    if not public_url.startswith("https://"):
        raise RuntimeError("RENDER_EXTERNAL_URL absent. Le service doit être un Web Service.")

    db_path = "data/hmb_surf_bot.sqlite3"
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    tts_dir = "data/tts"
    Path(tts_dir).mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=token,
        admin_id=int(admin),
        webhook_secret=secret,
        public_url=public_url,
        port=int(os.getenv("PORT", "10000")),
        database_path=db_path,
        groq_api_key=groq_api_key,
        groq_stt_model=os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo").strip(),
        groq_chat_model=os.getenv("GROQ_CHAT_MODEL", "openai/gpt-oss-20b").strip(),
        piper_python=sys.executable,
        piper_fr_model="voices/fr_FR-upmc-medium.onnx",
        piper_fr_config="voices/fr_FR-upmc-medium.onnx.json",
        piper_en_model="voices/en_US-lessac-medium.onnx",
        piper_en_config="voices/en_US-lessac-medium.onnx.json",
        ai_enabled=bool(groq_api_key),
        voice_reply_enabled=True,
        max_voice_seconds=90,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        webhook_watchdog_seconds=int(os.getenv("WEBHOOK_WATCHDOG_SECONDS", "600")),
        keepalive_enabled=os.getenv("KEEPALIVE_ENABLED", "1").strip().lower() not in ("0", "false", "no"),
        keepalive_seconds=int(os.getenv("KEEPALIVE_SECONDS", "600")),
        diag_token=os.getenv("DIAG_TOKEN", "").strip() or secrets.token_urlsafe(16),
        order_ttl_minutes=int(os.getenv("ORDER_TTL_MINUTES", "45")),
        reminder_minutes=int(os.getenv("REMINDER_MINUTES", "20")),
        low_stock_threshold=int(os.getenv("LOW_STOCK_THRESHOLD", "3")),
        tts_cache_dir=tts_dir,
    )


settings = load_settings()
