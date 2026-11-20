import subprocess
import sys
import tempfile
from pathlib import Path

import httpx


async def transcribe_groq(api_key, model, audio_bytes, filename="voice.ogg"):
    if not api_key:
        raise RuntimeError("GROQ_API_KEY manquante.")
    headers = {"Authorization": f"Bearer {api_key}"}
    files = {"file": (filename, audio_bytes, "application/octet-stream")}
    data = {"model": model, "response_format": "verbose_json"}
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers=headers,
            data=data,
            files=files,
        )
        response.raise_for_status()
        result = response.json()
    return (result.get("text") or "").strip(), (result.get("language") or "").lower()


def synthesize_piper(text, language, settings):
    lang = (language or "fr").lower()
    if lang.startswith("en") or "english" in lang:
        model = settings.piper_en_model
        config = settings.piper_en_config
        speaker_args = []
    else:
        # Le modèle UPMC possède deux voix ; l'identifiant 1 correspond à Pierre.
        model = settings.piper_fr_model
        config = settings.piper_fr_config
        speaker_args = ["--speaker", "1"]

    model_path = Path(model)
    config_path = Path(config)
    if not model_path.is_file() or not config_path.is_file():
        raise FileNotFoundError(
            "Les modèles Piper ne sont pas présents. Vérifie le téléchargement pendant le build Render."
        )

    output = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    output.close()

    command = [
        sys.executable, "-m", "piper",
        "--model", str(model_path),
        "--config", str(config_path),
        "--output_file", output.name,
        *speaker_args,
    ]
    try:
        # Le texte passe par stdin : le CLI Piper ne l'accepte pas après « -- ».
        completed = subprocess.run(
            command,
            input=text,
            text=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Piper a échoué (code {completed.returncode}) : {completed.stderr[-500:]}"
            )
        result_path = Path(output.name)
        if not result_path.is_file() or result_path.stat().st_size == 0:
            raise RuntimeError("Piper n'a produit aucun fichier audio.")
        return output.name
    except Exception:
        Path(output.name).unlink(missing_ok=True)
        raise
