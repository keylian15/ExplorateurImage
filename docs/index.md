# ExplorateurImage

Pour l'installation et le guide d'utilisation, il est conseillé de consulter la [documentation utilisateur](https://keylian15.github.io/ExplorateurImage/user/main/).

---

## Architecture

Le projet suit une architecture **MVVM** (Model – View – ViewModel) organisée en quatre couches :

```
ExplorateurImage/
├── models/          # Données et accès persistance
├── services/        # Logique métier, IA, cache
├── tools/           # Outils d'aide a la génration (docs / traduction)
├── viewmodels/      # État et logique de présentation
└── views/           # Interface utilisateur PyQt6
```

Chaque workspace est autonome et instancie ses propres ViewModels. La fenêtre principale (`MainWindow`) orchestre plusieurs workspaces via un système d'onglets, chacun possédant sa propre galerie, carte 2D, historique de recherche et images épinglées.

---

## Fonctionnalités principales

- **Galerie d'images** avec thumbnails paginés, zoom (Ctrl+molette) et cache LRU deux niveaux (mémoire + disque)
- **Indexation automatique** des images par description textuelle et embedding sémantique via un modèle vision-langage
- **Recherche sémantique** hybride combinant similarité cosinus sur les embeddings et correspondance textuelle
- **Images similaires** calculées par similarité cosinus (top-K voisins)
- **Carte 2D sémantique** projetant le corpus via UMAP + clustering HDBSCAN avec nommage automatique des clusters
- **Segmentation interactive** SAM3 avec recherche d'objets par prompt texte ou région dessinée, selon trois stratégies (Embedding, SAM3, Hybride)
- **Historique de recherche** structuré en arbre navigable avec affinage progressif
- **Images épinglées** par workspace, persistées entre les sessions
- **Renommage** de fichiers avec mise à jour de l'index et invalidation du cache
- **Multi-workspace** avec onglets indépendants
- **Personnalisation du thème** visuel (couleurs, thèmes prédéfinis, changement de langue à chaud)

---

## IA utilisées

### Pour le projet

| Composant | Technologie |
|-----------|-------------|
| Modèle vision-langage | Ollama (`qwen2.5vl:7b`) |
| Embeddings sémantiques | Ollama (`nomic-embed-text:v1.5`) |
| Segmentation interactive | SAM3 (Segment Anything Model 3) |

### Pour le développement

Ce projet a été développé en collaboration avec des assistants IA. 

| Composant | Technologie |
|-----------|-------------|
| Documentations & idées | ChatGPT (`GPT-5.3-mini`) |
| Architecture | Claude (`sonnet 4.6`) |
| Traduction | Ollama (`qwen3:8b`) |

---

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Interface | PyQt6 |
| Réduction dimensionnelle | UMAP |
| Clustering | HDBSCAN |
| Cache thumbnails | LRU mémoire + disque JPEG |
| Persistance index | `index.json` par dossier |
| Configuration | `config.json` racine |
| Traduction | `i18n.json` racine |
| Thème | `colors.json` racine |

