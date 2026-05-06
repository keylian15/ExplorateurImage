# ExplorateurImage


## Architecture

Le projet suit une architecture **MVVM** (Model – View – ViewModel) organisée en quatre couches :

```
ExplorateurImage/
├── models/          # Données et accès persistance
├── services/        # Logique métier, IA, cache
├── viewmodels/      # État et logique de présentation
└── views/           # Interface utilisateur PyQt6
```

## Fonctionnalités principales

- **Galerie d'images** avec thumbnails paginés et zoom (Ctrl+molette)
- **Auto-complétion** des descriptions et mots-clés via `qwen2.5vl:7b`
- **Recherche sémantique** hybride (embedding cosinus + correspondance texte)
- **Carte 2D sémantique** via UMAP + HDBSCAN avec clustering interactif
- **Images similaires** (top-K voisins par similarité cosinus)
- **Renommage** de fichiers avec mise à jour de l'index

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Interface | PyQt6 |
| Modèles IA | Ollama (`qwen2.5vl:7b`, `nomic-embed-text:v1.5`) |
| Réduction dimensionnelle | UMAP |
| Clustering | HDBSCAN |
| Cache thumbnails | LRU mémoire + disque JPEG |
| Persistance index | `index.json` par dossier |
| Configuration | `config.json` racine |

## Démarrage rapide

```bash
python -m venv venv
.\venv\Scripts\Activate 

pip install -r requirements.txt

python main.py
```