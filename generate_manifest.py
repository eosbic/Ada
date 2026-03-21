"""
Genera .manifest.json con hashes SHA-256 de todos los archivos de skills.
Ejecutar cada vez que se modifique un skill:
    python scripts/generate_manifest.py

Referencia: ADA_V5_ANEXO_CORRECCIONES_QWEN.md §1
"""

import hashlib
import json
from pathlib import Path


SKILLS_DIR = Path(__file__).parent.parent / "skills"
MANIFEST_PATH = SKILLS_DIR / ".manifest.json"

EXTENSIONS = {".md", ".py", ".json", ".txt", ".yaml", ".yml"}


def generate():
    manifest = {}

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("."):
            continue

        for file in sorted(skill_dir.rglob("*")):
            if not file.is_file():
                continue
            if file.suffix not in EXTENSIONS:
                continue

            rel_path = str(file.relative_to(SKILLS_DIR))
            sha256 = hashlib.sha256(file.read_bytes()).hexdigest()
            manifest[rel_path] = sha256

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    print(f"Manifest generado: {MANIFEST_PATH}")
    print(f"Total archivos: {len(manifest)}")

    for path, hash_val in manifest.items():
        print(f"  {path}: {hash_val[:16]}...")


if __name__ == "__main__":
    generate()