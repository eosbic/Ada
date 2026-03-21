"""
SkillLoader — Carga Agent Skills con verificación de integridad.
Referencia: ADA_MIGRACION_V5_SECCIONES_10-15.md §14
Corrección seguridad: ADA_V5_ANEXO_CORRECCIONES_QWEN.md §1

Seguridad:
- Verificación SHA-256 de archivos contra manifest
- Whitelist de skills permitidos (ALLOWED_SKILLS en .env)
- En producción: sin manifest = no carga
- En desarrollo: sin manifest = OK (warning)
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Optional, List
from datetime import datetime, timedelta


class SkillSecurityError(Exception):
    pass


class SkillNotFoundError(Exception):
    pass


class SkillLoader:
    SKILLS_DIR = Path(os.getenv("SKILLS_DIR", "/app/skills"))
    MANIFEST_PATH = Path(os.getenv("SKILLS_HASH_MANIFEST", "/app/skills/.manifest.json"))
    IS_PRODUCTION = os.getenv("ENV") == "production"
    ALLOWED_SKILLS = [
        s.strip()
        for s in os.getenv("ALLOWED_SKILLS", "").split(",")
        if s.strip()
    ]

    # Mapeo intent → skill
    INTENT_SKILL_MAP = {
        "calendar": "ada-calendar-skill",
        "email": "ada-email-skill",
        "excel_analysis": "ada-excel-analysis-skill",
        "data_query": "ada-document-search-skill",
        "prospecting": "ada-prospecting-skill",
        "project": "ada-project-skill",
    }

    # Mapeo industria → skill adicional
    INDUSTRY_SKILL_MAP = {
        "retail": "ada-retail-skill",
        "servicios": "ada-services-skill",
    }

    def __init__(self):
        self._cache: Dict[str, dict] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._cache_ttl = timedelta(minutes=5)
        self._manifest = self._load_manifest()

    def _load_manifest(self) -> Dict[str, str]:
        """Carga el manifest con hashes SHA-256."""
        if not self.MANIFEST_PATH.exists():
            if self.IS_PRODUCTION:
                raise SkillSecurityError(
                    "SKILLS_HASH_MANIFEST no encontrado en producción"
                )
            print("WARNING: Sin manifest de skills (modo desarrollo)")
            return {}
        return json.loads(self.MANIFEST_PATH.read_text())

    def _verify_integrity(self, file_path: Path) -> bool:
        """Verifica que el hash del archivo coincida con el manifest."""
        if not self._manifest:
            return True  # Dev only

        rel = str(file_path.relative_to(self.SKILLS_DIR))
        expected_hash = self._manifest.get(rel)
        if not expected_hash:
            return False

        current_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        return current_hash == expected_hash

    def _is_cache_valid(self, skill_name: str) -> bool:
        """Verifica si el cache del skill aún es válido."""
        ts = self._cache_timestamps.get(skill_name)
        if not ts:
            return False
        return datetime.utcnow() - ts < self._cache_ttl

    def load_skill(self, skill_name: str) -> dict:
        """Carga un skill por nombre. Retorna dict con instructions y metadata."""

        # 1. Cache
        if skill_name in self._cache and self._is_cache_valid(skill_name):
            return self._cache[skill_name]

        # 2. Whitelist en producción
        if self.IS_PRODUCTION and self.ALLOWED_SKILLS and skill_name not in self.ALLOWED_SKILLS:
            raise SkillSecurityError(
                f"Skill '{skill_name}' no está en ALLOWED_SKILLS"
            )

        # 3. Verificar que existe
        skill_dir = self.SKILLS_DIR / skill_name
        if not skill_dir.exists():
            raise SkillNotFoundError(f"Skill '{skill_name}' no encontrado en {skill_dir}")

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            raise SkillNotFoundError(f"SKILL.md no encontrado en {skill_dir}")

        # 4. Verificar integridad
        if self.IS_PRODUCTION and not self._verify_integrity(skill_md):
            raise SkillSecurityError(
                f"Hash de '{skill_name}/SKILL.md' no coincide con manifest"
            )

        # 5. Cargar
        instructions = skill_md.read_text(encoding="utf-8")

        # Cargar recursos adicionales si existen
        resources = {}
        resources_dir = skill_dir / "resources"
        if resources_dir.exists():
            for f in resources_dir.iterdir():
                if f.suffix == ".json":
                    try:
                        resources[f.stem] = json.loads(f.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        print(f"WARNING: No se pudo parsear {f}")

        result = {
            "name": skill_name,
            "instructions": instructions,
            "resources": resources,
            "has_scripts": (skill_dir / "scripts").exists(),
            "has_templates": (skill_dir / "templates").exists(),
        }

        # 6. Cache
        self._cache[skill_name] = result
        self._cache_timestamps[skill_name] = datetime.utcnow()

        return result

    def get_skill_for_intent(self, intent: str, industry_type: str = None) -> Optional[dict]:
        """Carga el skill apropiado según intent e industria."""

        skill_name = self.INTENT_SKILL_MAP.get(intent)
        if not skill_name:
            return None

        try:
            skill = self.load_skill(skill_name)
        except (SkillNotFoundError, SkillSecurityError) as e:
            print(f"WARNING: No se pudo cargar skill para intent '{intent}': {e}")
            return None

        # Si hay skill de industria, agregar instrucciones extra
        if industry_type and industry_type in self.INDUSTRY_SKILL_MAP:
            industry_skill_name = self.INDUSTRY_SKILL_MAP[industry_type]
            try:
                industry_skill = self.load_skill(industry_skill_name)
                skill["industry_instructions"] = industry_skill["instructions"]
                skill["industry_resources"] = industry_skill.get("resources", {})
            except (SkillNotFoundError, SkillSecurityError):
                pass  # No pasa nada si no existe skill de industria

        return skill

    def get_instructions_for_task(
        self, intent: str, industry_type: str = None
    ) -> str:
        """Devuelve instrucciones como string listo para inyectar en prompt."""

        skill = self.get_skill_for_intent(intent, industry_type)
        if not skill:
            return ""

        instructions = skill["instructions"]

        # Agregar instrucciones de industria si existen
        industry_instructions = skill.get("industry_instructions", "")
        if industry_instructions:
            instructions += f"\n\n## Contexto de industria ({industry_type})\n{industry_instructions}"

        return instructions

    def list_available_skills(self) -> List[str]:
        """Lista todos los skills disponibles en el directorio."""
        if not self.SKILLS_DIR.exists():
            return []
        return [
            d.name
            for d in self.SKILLS_DIR.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        ]


# Instancia global reutilizable
skill_loader = SkillLoader()