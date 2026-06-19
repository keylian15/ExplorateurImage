"""Générer automatiquement la documentation MkDocs à partir des modules Python du projet.

Ce script parcourt récursivement les fichiers Python à partir de la racine du projet,
convertit chaque fichier en nom de module importable, puis génère les fichiers Markdown
correspondants dans le dossier de documentation MkDocs.

Les fichiers déjà existants ne sont pas écrasés.

Contenu du module :
- Définition des chemins de base (ROOT, DOCS)
- Conversion chemin → module Python
- Filtrage des fichiers à ignorer
- Génération des fichiers de documentation MkDocs

USAGE CLI:

# Mode standard : génère les langues demandées (sans écraser l'existant)
python -m tools.i18n_builder --root . --langs en,es,de

# Mode sync : complète uniquement les langues déjà présentes dans i18n.json
python -m tools.i18n_builder --root . --sync
"""

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
    """Extraire les chaînes de traduction présentes dans le code source.

    Repère et récupère toutes les occurrences de `tr("...")` dans un fichier source.

    Args:
        source (str): Contenu du fichier Python.

    Returns:
        list[str]: Liste des chaînes de texte à traduire.

    """
    return TR_REGEX.findall(source)


# ----------------------------
# IO JSON
# ----------------------------


def load_i18n() -> dict[str, dict[str, str]]:
    """Charger le fichier de traductions i18n.

    Lit le fichier JSON de traductions s'il existe et retourne son contenu sous forme
    de dictionnaire. Retourne un dictionnaire vide si le fichier n'existe pas.

    Returns:
    dict[str, dict[str, str]]: Dictionnaire des traductions par clé et par langue.

    """
    path = Path(I18N_FILE)
    if not path.exists():
        return {}

    return json.loads(path.read_text(encoding="utf-8"))


def save_i18n(data: dict[str, dict[str, str]]) -> None:
    """Sauvegarder les traductions i18n dans un fichier JSON.

    Écrit l'ensemble des traductions dans le fichier de configuration i18n
    au format JSON lisible.

    Args:
    data (dict[str, dict[str, str]]): Dictionnaire des traductions à sauvegarder.

    """
    Path(I18N_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------
# OLLAMA (stub à brancher)
# ----------------------------


def ollama_translate(text: str, lang: str) -> str:
    """Traduire un texte dans une langue cible à l'aide du service Ollama.

    Construit un prompt de traduction et interroge le modèle pour obtenir une
    traduction automatique du texte fourni.

    Args:
    text (str): Texte à traduire.
    lang (str): Langue cible de traduction.

    Returns:
    str: Texte traduit.

    """
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


def main(project_root: str, languages: list[str]) -> None:
    """Analyser le projet et générer automatiquement les traductions i18n manquantes.

    Parcourt récursivement les fichiers Python du projet, extrait les chaînes traductibles,
    met à jour le fichier i18n et génère les traductions manquantes via un service externe.

    Args:
    project_root (str): Chemin racine du projet à analyser.
    languages (list[str]): Liste des langues cibles à compléter.

    """
    translations = load_i18n()

    found_keys = set()
    generated = 0
    nb_gen_to_save = 5
    for file in Path(project_root).rglob("*.py"):
        print(f"[i18n] scanning file: {file}")
        if file.parts[0] == "sam3":
            continue
        try:
            source = file.read_text(encoding="utf-8")
        except Exception:
            continue

        for text in extract_tr_calls(source):
            print(f"[i18n] found key: {text}")
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
                print(f"[i18n] translating '{text}' -> {lang}")

                entry[lang] = ollama_translate(text, lang)
                generated += 1

                print(f"[i18n] done '{text}' -> {lang}")

                if generated % nb_gen_to_save == 0:
                    print("[i18n] auto-save")
                    save_i18n(translations)

    # option: cleanup ou debug
    print(f"[i18n] keys found: {len(found_keys)}")
    print(f"[i18n] translations generated: {generated}")
    save_i18n(translations)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Générateur i18n")
    parser.add_argument("--root", required=True, help="Racine du projet")
    parser.add_argument("--langs", required=True, help="Langues séparées par des virgules (ex: en,es,de)")
    parser.add_argument("--sync", action="store_true", help="Complète uniquement les langues déjà présentes dans i18n.json")

    args = parser.parse_args()

    translations = load_i18n()

    if args.sync:
        # récupérer uniquement les langues déjà présentes dans le fichier
        existing_langs = set()

        for entry in translations.values():
            if isinstance(entry, dict):
                existing_langs.update(entry.keys())

        languages = sorted(existing_langs - {SOURCE_LANG})

    else:
        languages = [lang.strip() for lang in args.langs.split(",") if lang.strip()]

    main(args.root, languages)

    # Commande pour lancer la traduction d'une langue :
    # python -m tools.i18n_builder --root . --langs en
    # Commande pour lancer la traduction
