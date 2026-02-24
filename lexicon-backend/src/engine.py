"""
Grammar Engine — loads extensions from the extensions/ folder
and runs user input through them.
"""

import importlib
import sys
import os
import uuid


# Path to the extensions folder (sibling of lexicon-backend)
EXTENSIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "extensions")


class GrammarEngine:
    def __init__(self):
        self.extensions = []
        self._load_extensions()

    def _load_extensions(self):
        """Import every .py file in extensions/ and grab its EXTENSION dict."""
        ext_dir = os.path.normpath(EXTENSIONS_DIR)
        if not os.path.isdir(ext_dir):
            print(f"⚠️  extensions dir not found: {ext_dir}")
            return

        if ext_dir not in sys.path:
            sys.path.insert(0, ext_dir)

        for fname in sorted(os.listdir(ext_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            mod_name = fname[:-3]
            try:
                mod = importlib.import_module(mod_name)
                ext = getattr(mod, "EXTENSION", None)
                if ext and callable(ext.get("match")) and callable(ext.get("action")):
                    self.extensions.append(ext)
                    print(f"  ✔ loaded extension: {ext.get('name', mod_name)}")
                else:
                    print(f"  ⚠ skipped {fname}: no valid EXTENSION dict")
            except Exception as e:
                print(f"  ✖ failed to load {fname}: {e}")

        print(f"🧩 {len(self.extensions)} extension(s) loaded")

    def get_help_entries(self):
        """Collect help metadata from all loaded extensions."""
        entries = []
        for ext in self.extensions:
            h = ext.get("help")
            if h:
                entries.append(h)
        return entries

    def process(self, text):
        """Run text through all extensions, return list of actions."""
        text_lower = text.lower().strip()
        actions = []

        for ext in self.extensions:
            match_result = ext["match"](text_lower)
            if match_result is not None:
                action = ext["action"](text, match_result)
                if isinstance(action, list):
                    actions.extend(action)
                else:
                    actions.append(action)

        if not actions:
            actions.append({
                "type": "FEEDBACK",
                "message": f"Unknown command: '{text}'",
            })

        return actions
