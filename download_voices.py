"""Download the pinned Piper voice models during Render's build."""
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
FILES = {
    "voices/fr_FR-upmc-medium.onnx": "fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx",
    "voices/fr_FR-upmc-medium.onnx.json": "fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx.json",
    "voices/en_US-lessac-medium.onnx": "en/en_US/lessac/medium/en_US-lessac-medium.onnx",
    "voices/en_US-lessac-medium.onnx.json": "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
}


def download(destination: str, relative_url: str) -> None:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 1_000_000:
        print(f"[Piper] Déjà présent : {path}")
        return
    url = BASE + relative_url
    print(f"[Piper] Téléchargement : {path.name}")
    request = Request(url, headers={"User-Agent": "HMB-SURF-BOT-build/1.0"})
    with urlopen(request, timeout=180) as response, path.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
    if path.stat().st_size < 1_000:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"Téléchargement invalide pour {path.name}")


if __name__ == "__main__":
    for target, source in FILES.items():
        download(target, source)
    print("[Piper] Les deux modèles vocaux sont prêts.")
