"""
Download every model the input security layer needs, ahead of time.

Run this during the Docker build or deployment, not on the first user request:

    python scripts/download_models.py                       # everything
    python scripts/download_models.py --only fasttext spacy  # some of them

Downloads only. Nothing is loaded into memory, so it is safe on a small machine.

    fasttext   step 4   lid.176.ftz (~1 MB)                  -> models/
    spacy      step 6   spaCy model for Presidio (PRESIDIO_SPACY_MODEL)
    fastembed  step 11  all-MiniLM-L6-v2 ONNX (~90 MB)       -> models/fastembed/
    llm-guard  step 8   deberta-v3-base-prompt-injection-v2  -> Hugging Face cache
    llama-guard step 10 printed instructions (served by Ollama / vLLM)
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import urllib.request

from input_security.settings import get_settings

FASTTEXT_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"
FASTTEXT_SHA256 = "8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83"

CHOICES = ["fasttext", "spacy", "fastembed", "llm-guard", "llama-guard"]


def download_fasttext() -> None:
    path = get_settings().fasttext_model_path
    if path.exists():
        print(f"[fasttext] already present: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"[fasttext] downloading {FASTTEXT_URL}")
    data = urllib.request.urlopen(FASTTEXT_URL, timeout=120).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != FASTTEXT_SHA256:
        raise SystemExit(f"[fasttext] checksum mismatch: {digest}")
    path.write_bytes(data)
    print(f"[fasttext] saved {path} ({len(data) // 1024} KB)")


def download_spacy() -> None:
    import spacy.util

    model = get_settings().presidio_spacy_model
    if spacy.util.is_package(model):
        print(f"[spacy] already installed: {model}")
        return
    print(f"[spacy] python -m spacy download {model}")
    subprocess.run([sys.executable, "-m", "spacy", "download", model], check=True)


def download_fastembed() -> None:
    from fastembed import TextEmbedding

    settings = get_settings()
    model = settings.topic_embedding_model
    print(f"[fastembed] fetching {model} -> {settings.fastembed_cache_dir}")
    # TextEmbedding downloads into the cache folder. The ONNX session it opens is small.
    TextEmbedding(model, cache_dir=str(settings.fastembed_cache_dir))
    print("[fastembed] ready")


def download_llm_guard() -> None:
    from huggingface_hub import snapshot_download
    from llm_guard.input_scanners.prompt_injection import V2_MODEL

    print(f"[llm-guard] fetching {V2_MODEL.path}@{V2_MODEL.revision[:8]}")
    snapshot_download(V2_MODEL.path, revision=V2_MODEL.revision, allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt"])
    print("[llm-guard] ready")


def explain_llama_guard() -> None:
    s = get_settings()
    print(
        "[llama-guard] runs as its own model server, not inside this app.\n"
        "  development:  ollama pull llama-guard3:1b\n"
        "  production :  vllm serve meta-llama/Llama-Guard-3-8B\n"
        f"  configured :  backend={s.llama_guard_backend} url={s.llama_guard_base_url} model={s.llama_guard_model}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", choices=CHOICES, default=CHOICES)
    args = parser.parse_args()
    actions = {
        "fasttext": download_fasttext,
        "spacy": download_spacy,
        "fastembed": download_fastembed,
        "llm-guard": download_llm_guard,
        "llama-guard": explain_llama_guard,
    }
    for name in args.only:
        actions[name]()


if __name__ == "__main__":
    main()
