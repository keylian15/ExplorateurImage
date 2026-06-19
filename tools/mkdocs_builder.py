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
"""

from pathlib import Path

ROOT = Path(".")  # racine projet
DOCS = Path("docs")  # dossier mkdocs


def to_module(_root: Path, file: Path) -> str:
    """Convertit un chemin de fichier Python en nom de module importable.

    Transforme un chemin relatif en notation pointée (ex: models/index_repository.py
    → models.index_repository).

    Args:
        _root (Path): Racine du projet.
        file (Path): Fichier Python à convertir.

    Returns:
        str: Nom du module Python correspondant.

    """
    relative = file.with_suffix("")  # enlève .py
    parts = relative.parts

    return ".".join(parts)


def should_ignore(file: Path) -> bool:
    """Détermine si un fichier doit être ignoré lors de la génération de documentation.

    Ignore les fichiers appartenant au dossier 'sam3' ou les fichiers __init__.py.

    Args:
        file (Path): Fichier à évaluer.

    Returns:
        bool: True si le fichier doit être ignoré, False sinon.

    """
    return "sam3" in file.parts or "__init__" in file.name


def main() -> None:
    """Générer automatiquement la documentation MkDocs à partir des fichiers Python du projet.

    Parcourt récursivement les fichiers Python du projet, convertit chaque module en
    chemin de documentation MkDocs et crée les fichiers Markdown correspondants dans le
    dossier cible s'ils n'existent pas déjà.

    Ne modifie pas les fichiers existants.
    """
    python_files = ROOT.rglob("*.py")

    for file in python_files:
        if should_ignore(file):
            continue

        module = to_module(ROOT, file)

        # chemin cible md
        md_path = DOCS / file.with_suffix(".md")

        # création dossier si nécessaire
        md_path.parent.mkdir(parents=True, exist_ok=True)

        # contenu mkdocs
        content = f"::: {module}\n"

        # écrire seulement si fichier n'existe pas
        if not md_path.exists():
            md_path.write_text(content, encoding="utf-8")
            print(f"[CREATED] {md_path} -> {module}")
        else:
            print(f"[SKIP] {md_path} already exists")


if __name__ == "__main__":
    main()
