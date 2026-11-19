import os
import re
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
    gemini_api_key: str
    gemini_model: str
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


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    admin = os.getenv("ADMIN_ID", "").strip()
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    public_url = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL") or "").strip().rstrip("/")

    if not token:
        raise RuntimeError("BOT_TOKEN manquant dans Render > Environment.")
    if not admin.isdigit():
        raise RuntimeError("ADMIN_ID doit être ton identifiant Telegram numérique.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
        raise RuntimeError("WEBHOOK_SECRET manquant ou invalide. Utilise une valeur secrète aléatoire.")
    if not public_url.startswith("https://"):
        raise RuntimeError("Render n'a pas fourni RENDER_EXTERNAL_URL. Vérifie que le service est de type Web Service.")

    port = int(os.getenv("PORT", "10000"))
    db_path = "data/hmb_surf_bot.sqlite3"
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=token,
        admin_id=int(admin),
        webhook_secret=secret,
        public_url=public_url,
        port=port,
        database_path=db_path,
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        # gemini-2.5-flash n'est plus servi aux nouvelles clés.
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip(),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_stt_model="whisper-large-v3-turbo",
        groq_chat_model=os.getenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile").strip(),
        piper_python=sys.executable,
        piper_fr_model="voices/fr_FR-upmc-medium.onnx",
        piper_fr_config="voices/fr_FR-upmc-medium.onnx.json",
        piper_en_model="voices/en_US-lessac-medium.onnx",
        piper_en_config="voices/en_US-lessac-medium.onnx.json",
        ai_enabled=True,
        voice_reply_enabled=True,
        max_voice_seconds=90,
        log_level="INFO",
        # Intervalle de vérification du webhook (secondes).
        webhook_watchdog_seconds=int(os.getenv("WEBHOOK_WATCHDOG_SECONDS", "600")),
        # Auto-ping anti-veille : désactivable avec KEEPALIVE_ENABLED=0 (plan payant).
        keepalive_enabled=os.getenv("KEEPALIVE_ENABLED", "1").strip() not in ("0", "false", "False"),
        keepalive_seconds=int(os.getenv("KEEPALIVE_SECONDS", "600")),
    )


settings = load_settings()
