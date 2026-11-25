"""Formula library loader (fictional, illustrative formulas in data/formulas/)."""

import hashlib
from pathlib import Path

import yaml

from intake.models import Formula
from intake.rules import normalise_name

DEFAULT_FORMULA_DIR = Path(__file__).resolve().parents[2] / "data" / "formulas"
FORMULA_GLOB = "SHF-*.yaml"


def _formula_files(directory: Path) -> list[Path]:
    return sorted(directory.glob(FORMULA_GLOB))


def load_formulas(directory: Path = DEFAULT_FORMULA_DIR) -> list[Formula]:
    """Every `SHF-*.yaml` in the directory, schema-validated, sorted by file name."""
    return [Formula.model_validate(yaml.safe_load(path.read_text())) for path in _formula_files(directory)]


def load_alias_map(path: Path = DEFAULT_FORMULA_DIR / "ingredient_master.yaml") -> dict[str, str]:
    """Normalised name or alias -> normalised canonical name, from the ingredient master."""
    data = yaml.safe_load(path.read_text())
    aliases: dict[str, str] = {}
    for entry in data["ingredients"]:
        canonical = normalise_name(entry["name"])
        aliases[canonical] = canonical
        for alias in entry.get("aliases") or []:
            aliases[normalise_name(alias)] = canonical
    return aliases


def library_version(directory: Path = DEFAULT_FORMULA_DIR) -> str:
    """Short SHA-256 over the formula files' names and contents: changes whenever any formula does."""
    digest = hashlib.sha256()
    for path in _formula_files(directory):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]
