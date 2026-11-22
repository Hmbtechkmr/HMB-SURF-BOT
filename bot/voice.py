"""Fast Piper TTS with in-process model reuse and disk cache.

The Piper model is loaded once per language and reused for subsequent replies.
"""
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

# Piper models are relatively expensive to load. Keep one loaded instance per language.
_VOICES = {}
_VOICE_LOAD_LOCK = threading.Lock()
_SYNTHESIS_LOCK = threading.Lock()
_MAX_CACHE_FILES = 250


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


def _model_for(language, settings):
    lang = (language or "fr").lower()
    if lang.startswith("en") or "english" in lang:
        return settings.piper_en_model, settings.piper_en_config, "en"
    return settings.piper_fr_model, settings.piper_fr_config, "fr"


def _cache_path(settings, text, lang):
    digest = hashlib.sha256(f"{lang}|{text}".encode("utf-8")).hexdigest()
    return Path(settings.tts_cache_dir) / f"{digest}.wav"


def _load_voice(model_path, config_path, language):
    """Load Piper once and reuse the model until the process restarts."""
    key = (str(Path(model_path).resolve()), str(Path(config_path).resolve()))
    voice = _VOICES.get(key)
    if voice is not None:
        return voice

    with _VOICE_LOAD_LOCK:
        voice = _VOICES.get(key)
        if voice is not None:
            return voice
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise RuntimeError("piper-tts n'est pas installé.") from exc

        # Piper 1.2 accepts the model path and optional config path.
        try:
            voice = PiperVoice.load(str(model_path), config_path=str(config_path))
        except TypeError:
            voice = PiperVoice.load(str(model_path), str(config_path))
        _VOICES[key] = voice
        log.info("Modèle Piper chargé en mémoire : %s", language)
        return voice


def warm_piper(settings, language="fr"):
    """Optional startup warm-up: first French reply won't pay model-loading cost."""
    model, config, lang = _model_for(language, settings)
    if not Path(model).is_file() or not Path(config).is_file():
        log.warning("Modèle Piper %s absent : préchauffage ignoré.", lang)
        return False
    _load_voice(model, config, lang)
    return True


def _trim_cache(cache_dir):
    """Keep the disk cache bounded; remove oldest generated WAV files."""
    try:
        files = sorted(
            Path(cache_dir).glob("*.wav"),
            key=lambda item: item.stat().st_mtime,
        )
        for old in files[:-_MAX_CACHE_FILES]:
            old.unlink(missing_ok=True)
    except OSError:
        log.warning("Nettoyage du cache TTS impossible.", exc_info=True)


def _synthesize_with_python(voice, text, output_path, speaker_id=None):
    """Use the in-process Piper API (no process/model reload per request)."""
    with wave.open(str(output_path), "wb") as wav_file:
        synthesize_wav = getattr(voice, "synthesize_wav", None)
        if callable(synthesize_wav):
            try:
                synthesize_wav(text, wav_file, speaker_id=speaker_id)
            except TypeError:
                synthesize_wav(text, wav_file)
        else:
            synthesize = getattr(voice, "synthesize", None)
            if not callable(synthesize):
                raise RuntimeError("API Piper incompatible : méthode synthesize absente.")
            try:
                synthesize(text, wav_file, speaker_id=speaker_id)
            except TypeError:
                synthesize(text, wav_file)


def synthesize_piper(text, language, settings):
    """Retourne (chemin_audio, mis_en_cache), en réutilisant le modèle chargé."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Texte vocal vide.")

    model, config, cache_lang = _model_for(language, settings)
    model_path, config_path = Path(model), Path(config)
    if not model_path.is_file() or not config_path.is_file():
        raise FileNotFoundError("Modèles Piper absents. Vérifie le build Render.")

    cache_dir = Path(settings.tts_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = _cache_path(settings, text, cache_lang)
    if cached.is_file() and cached.stat().st_size > 44:
        return str(cached), True

    fd, output_name = tempfile.mkstemp(suffix=".wav", dir=str(cache_dir))
    os.close(fd)
    output = Path(output_name)
    try:
        voice = _load_voice(model_path, config_path, cache_lang)
        speaker_id = 1 if cache_lang == "fr" else None
        # Serialize synthesis for predictable CPU/RAM use on Render Free.
        with _SYNTHESIS_LOCK:
            _synthesize_with_python(voice, text, output, speaker_id=speaker_id)

        if not output.is_file() or output.stat().st_size <= 44:
            raise RuntimeError("Piper n'a produit aucun audio.")

        try:
            output.replace(cached)
            _trim_cache(cache_dir)
            return str(cached), False
        except OSError:
            return str(output), False
    except Exception:
        output.unlink(missing_ok=True)
        log.exception("Synthèse Piper en mémoire échouée.")
        raise


def clear_voice_cache():
    """Release loaded models (mainly useful for tests/shutdown)."""
    with _VOICE_LOAD_LOCK:
        _VOICES.clear()
