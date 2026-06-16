from pathlib import Path

ROOT = Path(".")  # racine projet
DOCS = Path("docs")  # dossier mkdocs


def to_module(root: Path, file: Path) -> str:
    """Convertit un chemin fichier en module python.
    ex: models/index_repository.py -> models.index_repository
        main.py -> main
    """
    relative = file.with_suffix("")  # enlève .py
    parts = relative.parts

    return ".".join(parts)


def should_ignore(file: Path) -> bool:
    return "sam3" in file.parts or "__init__" in file.name


def main():
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
