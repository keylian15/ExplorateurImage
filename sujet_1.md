# Sujet 2 — Explorateur sémantique d’un corpus d’images

---

**auteur: Rémi Cozot — date: Avril 2026**

---

## Contexte

Un explorateur de fichiers classique permet de parcourir des images selon leur emplacement dans des dossiers ou leur nom de fichier. Or, dans de nombreux cas, l’utilisateur souhaite plutôt naviguer selon la **proximité de contenu** :

* images visuellement ou sémantiquement proches ;
* images contenant des scènes comparables ;
* regroupements thématiques ;
* recherche d’exemples similaires.

L’objectif de ce projet est de développer un **explorateur sémantique d’images**.
Le système ne se contente pas de répondre à une requête unique ; il propose une **navigation interactive** dans un corpus : recherche, voisinage, regroupement, consultation des descriptions, visualisation des proximités.

Ce projet met davantage l’accent sur :

* l’interaction homme-machine,
* la visualisation,
* la structuration d’un espace sémantique,
* la compréhension par l’utilisateur de ce que signifie “deux images proches”.

---

## Objectif général

Développer une application interactive permettant :

* d’indexer un corpus local d’images ;
* d’associer à chaque image une description générée automatiquement ;
* de calculer des embeddings sémantiques ;
* d’explorer le corpus par recherche, similarité et regroupement ;
* de proposer une interface de navigation claire, proche d’un explorateur intelligent.

---

## Contraintes techniques

Le projet devra utiliser :

* **Ollama**
* **Qwen2.5-VL** ou **Qwen3.5-VL**
* **nomic-embed-text**

L’application devra fonctionner localement.

---

## Différence avec le sujet 1

Dans le sujet 1, le cœur du projet est le **moteur de recherche**.
Dans ce sujet 2, le cœur du projet est **l’interface d’exploration sémantique**.

La qualité attendue repose donc sur :

* la navigation,
* la visualisation des relations entre images,
* la consultation interactive,
* la capacité à passer d’une image à ses voisines,
* la compréhension globale du corpus.

---

## Pipeline attendu

### 1. Ingestion du corpus

Chargement d’un dossier d’images.

### 2. Analyse par modèle vision-language

Pour chaque image, génération d’une description textuelle et éventuellement :

* de mots-clés ;
* d’une catégorie ;
* d’une phrase courte résumant la scène.

### 3. Embedding des descriptions

Transformation du texte associé à chaque image en vecteur.

### 4. Construction d’un espace sémantique

À partir des embeddings, le système doit pouvoir :

* calculer les voisins les plus proches d’une image ;
* identifier des groupes d’images similaires ;
* éventuellement projeter le corpus en 2D pour faciliter la visualisation.

### 5. Interface d’exploration

L’utilisateur doit pouvoir :

* lancer une recherche par texte ;
* cliquer sur une image ;
* afficher ses voisines sémantiques ;
* voir les groupes ou catégories émergentes ;
* consulter les métadonnées et descriptions.

---

## Fonctionnalités minimales attendues

### A. Galerie principale

Afficher le corpus d’images sous forme de miniatures.

### B. Recherche textuelle

L’utilisateur peut saisir une requête, et l’interface affiche les images les plus proches sémantiquement.

### C. Voisinage sémantique

À partir d’une image sélectionnée, l’application affiche les images voisines dans l’espace d’embeddings.

### D. Fiche image

Lorsqu’une image est sélectionnée, on doit pouvoir consulter :

* son aperçu en taille plus grande ;
* sa description générée ;
* éventuellement ses mots-clés ;
* les images similaires.

### E. Persistance de l’index

L’application ne doit pas recalculer toute l’indexation à chaque démarrage.

---

## Fonctionnalités complémentaires possibles

### 1. Carte 2D du corpus

Projeter les embeddings dans un plan 2D avec :

* PCA,
* t-SNE,
* ou UMAP.

L’utilisateur peut alors visualiser une “carte” du corpus et cliquer sur les zones ou points.

### 2. Clustering automatique

Regrouper les images en clusters et afficher ces groupes dans l’interface.

Le projet peut tester des algorithmes simples comme :

* KMeans,
* DBSCAN,
* Agglomerative Clustering.

### 3. Nommage automatique des groupes

À partir des descriptions des images d’un cluster, générer un titre ou un résumé de groupe.

### 4. Correction utilisateur

Permettre à l’utilisateur de modifier la description d’une image et de relancer l’indexation de cette image.

### 5. Historique de navigation

Conserver :

* les dernières requêtes,
* les dernières images consultées,
* les parcours récents.

### 6. Filtres interactifs

Ajouter des filtres par :

* mot-clé,
* dossier,
* extension,
* cluster,
* catégorie probable.

### 7. Mode comparaison

Afficher côte à côte :

* une image de référence ;
* ses voisins les plus proches ;
* leurs descriptions.

---

## Attendus sur l’interface

L’interface est un élément central du projet.
Elle devra être pensée comme un outil d’exploration et non comme une simple fenêtre de test.

Elle devra donc proposer une navigation fluide entre plusieurs niveaux :

* vue d’ensemble du corpus ;
* recherche ciblée ;
* consultation détaillée ;
* voisinage sémantique ;
* éventuellement carte globale.

Une attention particulière devra être portée à :

* la lisibilité ;
* la gestion des miniatures ;
* la rapidité d’affichage ;
* l’organisation de l’information.

---

## Architecture logicielle conseillée

Une organisation modulaire est recommandée :

* `corpus/`

  * gestion des fichiers image
* `captioning/`

  * génération des descriptions avec Qwen-VL
* `embeddings/`

  * calcul des vecteurs
* `similarity/`

  * voisinage, top-k, clustering
* `projection/`

  * réduction de dimension éventuelle
* `ui/`

  * interface interactive
* `storage/`

  * sauvegarde des données

Le projet devra séparer clairement :

* calcul offline de l’index,
* exploitation interactive de l’index.

---

## Représentation des données

Chaque image pourra être associée à une fiche contenant :

* identifiant,
* chemin,
* miniature éventuelle,
* description,
* mots-clés,
* embedding,
* cluster éventuel,
* voisins pré-calculés ou recalculables.

Exemple :

```json
{
  "id": "img_0042",
  "path": "dataset/forest_03.jpg",
  "description": "A forest path with sunlight coming through the trees.",
  "keywords": ["forest", "path", "trees", "sunlight"],
  "cluster": 2,
  "neighbors": ["img_0045", "img_0018", "img_0091"]
}
```

---

## Scénarios d’usage attendus

L’application devra permettre au moins les scénarios suivants :

### Scénario 1

L’utilisateur charge un corpus puis lance une recherche :

> “images de rue la nuit”

Il consulte les résultats et ouvre une image intéressante.

### Scénario 2

Depuis cette image, il demande :

> “montrer les images similaires”

Il observe les voisines sémantiques et compare les descriptions générées.

### Scénario 3

Il revient à la vue générale du corpus et explore un regroupement ou une zone de la carte sémantique.

Ces scénarios devront être montrables pendant la démonstration.


---

## Livrables attendus

* code source ;
* application fonctionnelle ;
* documentation ;
* corpus de test ;
* rapport technique ;
* démonstration avec scénarios d’usage.

---

## Compétences mobilisées

* développement Python ;
* IA locale avec Ollama ;
* structuration de pipeline ;
* embeddings et similarité ;
* réduction de dimension ou clustering ;
* conception d’interface ;
* analyse critique des résultats.

---


