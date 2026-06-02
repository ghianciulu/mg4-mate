"""MG4 Mate translations loaded from locale JSON files."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_LANGUAGE = "en"
LOCALES_DIR = Path(__file__).parent / "locales"

_translations: dict[str, dict[str, str]] = {}


def load_translations(locale_dir: str | Path = LOCALES_DIR) -> None:
    """Load all locale files from disk.

    Locale files are plain JSON objects. The optional ``__language_name`` key is
    used by Settings to render the language selector.
    """
    global _translations
    locale_path = Path(locale_dir)
    loaded: dict[str, dict[str, str]] = {}

    for path in sorted(locale_path.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        loaded[path.stem] = {str(key): str(value) for key, value in data.items()}

    _translations = loaded or {
        DEFAULT_LANGUAGE: {
            "__language_name": "English",
            "settings_title": "Settings",
        }
    }


def available_languages() -> list[dict[str, str]]:
    if not _translations:
        load_translations()
    return [
        {
            "code": code,
            "name": strings.get("__language_name", code),
        }
        for code, strings in sorted(_translations.items())
    ]


def available_language_codes() -> set[str]:
    if not _translations:
        load_translations()
    return set(_translations.keys())


def get_t(lang: str):
    if not _translations:
        load_translations()
    strings = _translations.get(lang, _translations.get(DEFAULT_LANGUAGE, {}))
    fallback = _translations.get(DEFAULT_LANGUAGE, {})

    def t(key: str) -> str:
        return strings.get(key, fallback.get(key, key))

    return t


load_translations()
