import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx


async def transcribe_groq(api_key, model, audio_bytes, filename="voice.ogg"):
    if not api_key:
        raise RuntimeError("GROQ_API_KEY manquante.")
    files = {"file": (filename, audio_bytes, "application/octet-stream")}
    data = {"model": model, "response_format": "verbose_json"}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data=data, files=files,
        )
        response.raise_for_status()
        result = response.json()
    return (result.get("text") or "").strip(), (result.get("language") or "").lower()


def _cache_path(settings, text, lang):
    digest = hashlib.sha1(f"{lang}|{text}".encode("utf-8")).hexdigest()
    return Path(settings.tts_cache_dir) / f"{digest}.wav"


def synthesize_piper(text, language, settings):
    """Retourne (chemin, mis_en_cache)."""
    lang = (language or "fr").lower()
    if lang.startswith("en") or "english" in lang:
        model, config, speaker_args, cache_lang = (
            settings.piper_en_model, settings.piper_en_config, [], "en")
    else:
        model, config, speaker_args, cache_lang = (
            settings.piper_fr_model, settings.piper_fr_config, ["--speaker", "1"], "fr")

    model_path, config_path = Path(model), Path(config)
    if not model_path.is_file() or not config_path.is_file():
        raise FileNotFoundError("Modèles Piper absents. Vérifie le build Render.")

    cached = _cache_path(settings, text, cache_lang)
    if cached.is_file() and cached.stat().st_size > 0:
        return str(cached), True

    output = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    output.close()
    command = [sys.executable, "-m", "piper", "--model", str(model_path),
               "--config", str(config_path), "--output_file", output.name, *speaker_args]
    try:
        completed = subprocess.run(command, input=text, text=True, check=False,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
        if completed.returncode != 0:
            raise RuntimeError(f"Piper code {completed.returncode} : {completed.stderr[-400:]}")
        if Path(output.name).stat().st_size == 0:
            raise RuntimeError("Piper n'a produit aucun audio.")
        cached.write_bytes(Path(output.name).read_bytes())
        return output.name, False
    finally:
        Path(output.name).unlink(missing_ok=True)
