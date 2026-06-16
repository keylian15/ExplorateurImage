import json
import re
from pathlib import Path

from services.ollama_wrapper import OllamaWrapper

SOURCE_LANG = "fr"


# ----------------------------
# CONFIG
# ----------------------------

I18N_FILE = "i18n.json"
CLIENT = OllamaWrapper()

# ----------------------------
# EXTRACTION
# ----------------------------
TR_REGEX = re.compile(r'\.tr\("([^"]+)"\)')


def extract_tr_calls(source: str) -> list[str]:
    return TR_REGEX.findall(source)


# ----------------------------
# IO JSON
# ----------------------------


def load_i18n() -> dict[str, dict[str, str]]:
    path = Path(I18N_FILE)
    if not path.exists():
        return {}

    return json.loads(path.read_text(encoding="utf-8"))


def save_i18n(data: dict[str, dict[str, str]]) -> None:
    Path(I18N_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------
# OLLAMA (stub à brancher)
# ----------------------------


def ollama_translate(text: str, lang: str) -> str:
    prompt = f"""You are a professional translator.

Translate the following text to {lang}.
Rules:
- return ONLY the translation
- no explanations
- keep punctuation

Text:
{text}
"""

    try:
        response = CLIENT.generate_text(
            model="qwen3:8b",
            prompt=prompt,
        )
        raw = response.response.strip()  # .response, pas .strip() direct

        # Filtre le bloc <think>...</think> si présent malgré tout
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        return raw

    except Exception as e:
        print(f"[i18n] Ollama error: {e}")
        return text


# ----------------------------
# MAIN SCRIPT
# ----------------------------


def main(project_root: str, languages: list[str]):
    translations = load_i18n()

    found_keys = set()
    generated = 0
    for file in Path(project_root).rglob("*.py"):
        if file.parts[0] == "sam3":
            continue
        try:
            source = file.read_text(encoding="utf-8")
        except Exception:
            continue

        for text in extract_tr_calls(source):
            found_keys.add(text)

            if text not in translations:
                translations[text] = {}

            entry = translations[text]

            # SOURCE LANG = base
            if SOURCE_LANG not in entry:
                entry[SOURCE_LANG] = text

            # fill languages
            for lang in languages:
                if lang == SOURCE_LANG:
                    continue

                if entry.get(lang):
                    continue

                entry[lang] = ollama_translate(text, lang)
                generated += 1

    # option: cleanup ou debug
    print(f"[i18n] keys found: {len(found_keys)}")
    print(f"[i18n] translations generated: {generated}")
    save_i18n(translations)


# ----------------------------
# ENTRYPOINT CLI
# ----------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument("--root", required=True, help="project root")
    parser.add_argument("--langs", nargs="+", default=["en"])

    args = parser.parse_args()

    main(args.root, args.langs)

    # python -m tools.i18n_builder --root . --langs en
