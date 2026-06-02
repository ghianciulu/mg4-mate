import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))

import i18n


class I18nTest(unittest.TestCase):
    def test_loads_languages_from_json_and_falls_back_to_english(self):
        with tempfile.TemporaryDirectory() as tmp:
            locale_dir = Path(tmp)
            (locale_dir / "en.json").write_text(
                json.dumps({
                    "__language_name": "English",
                    "settings_title": "Settings",
                    "only_english": "Fallback value",
                }),
                encoding="utf-8",
            )
            (locale_dir / "it.json").write_text(
                json.dumps({
                    "__language_name": "Italiano",
                    "settings_title": "Impostazioni",
                }),
                encoding="utf-8",
            )

            i18n.load_translations(locale_dir)
            try:
                translate = i18n.get_t("it")

                self.assertEqual(translate("settings_title"), "Impostazioni")
                self.assertEqual(translate("only_english"), "Fallback value")
                self.assertEqual(translate("missing_key"), "missing_key")
                self.assertEqual(
                    i18n.available_languages(),
                    [
                        {"code": "en", "name": "English"},
                        {"code": "it", "name": "Italiano"},
                    ],
                )
            finally:
                i18n.load_translations()


if __name__ == "__main__":
    unittest.main()
