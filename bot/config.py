import os
import re
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

def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    admin_raw = os.getenv("ADMIN_ID", "").strip()
    secret = os.getenv("WEBHOOK_SECRET", "").strip()
    public_url = (os.getenv("PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if not token:
        raise RuntimeError("Variable BOT_TOKEN manquante.")
    if not admin_raw.isdigit():
        raise RuntimeError("ADMIN_ID doit être un identifiant Telegram numérique.")
    if not secret or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret):
        raise RuntimeError("WEBHOOK_SECRET manquant ou invalide (lettres, chiffres, _ et -).")
    if not public_url.startswith("https://"):
        raise RuntimeError("URL HTTPS manquante : renseigne PUBLIC_URL ou déploie sur Render.")
    port = int(os.getenv("PORT", "10000"))
    db_path = os.getenv("DATABASE_PATH", "./data/hmb_surf_bot.sqlite3")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return Settings(token, int(admin_raw), secret, public_url, port, db_path)
