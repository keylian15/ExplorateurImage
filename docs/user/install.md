# Installation

Cette page décrit l’installation complète de l’application Explorateur Image Sémantique, incluant les dépendances Python, SAM3, les modèles IA et l’authentification Hugging Face.

---

## ⚠️ Prérequis importants (lecture obligatoire)

### Accès réseau

L’application utilise un serveur Ollama mis à disposition sur le réseau de l’IUT.

**Il est nécessaire d’être connecté au réseau IUT pour accéder à ce service.**

Sans cet accès :

* la génération de descriptions peut ne pas fonctionner ;
* certaines fonctionnalités IA seront indisponibles.

Dans ce cas, il est possible d’adapter le fichier :

```
ollama_wrapper.py
```

pour utiliser une instance Ollama locale (non couvert dans cette documentation).

---

### Système

* Conda (version 26.3.2 recommandée ou équivalent)
* Git
* GPU compatible CUDA 12.6 ou supérieur (obligatoire pour SAM3)

---

## Installation du projet

### 1. Cloner le dépôt principal

```bash
git clone https://github.com/keylian15/ExplorateurImage.git
cd ExplorateurImage
```

---

### 2. Création de l’environnement Conda

```bash
conda create -n ExplorateurImage python=3.12
conda activate ExplorateurImage
```

---

### 3. Installation de PyTorch (CUDA)

```bash
pip install torch==2.10.0 torchvision --index-url https://download.pytorch.org/whl/cu128
```

---

### 4. Installation des dépendances Python

```bash
pip install -r requirements.txt
```

---

### 5. Installation de SAM3

```bash
git clone https://github.com/facebookresearch/sam3.git
cd sam3
pip install -e .
cd ..
```

---

### 6. Authentification Hugging Face

Certaines ressources du projet nécessitent une authentification Hugging Face.

```bash
huggingface-cli login
```

Documentation officielle :
[Hugging Face Authentication Guide](https://huggingface.co/docs/huggingface_hub/en/quick-start?utm_source=chatgpt.com#authentication)

---

### 7. Jeu de données de test (COCO)

Pour tester l’application à grande échelle, il est recommandé d’utiliser le dataset COCO.

Téléchargement :

[COCO Test 2017 Dataset](http://images.cocodataset.org/zips/test2017.zip?utm_source=chatgpt.com)

Après téléchargement :

1. Copier le fichier `example_index.json` fourni avec le projet dans ce dossier d’images

Ce fichier permet de démarrer l’application avec un index déjà construit.

---

### 8. Lancement de l’application

```bash
python main.py
```

---

## Données déjà indexées

Le projet fournit un dossier d’exemple déjà indexé permettant de tester rapidement l’application sans phase d’analyse initiale.

Il peut être utilisé directement comme corpus de démonstration.

---

## Notes importantes

### CUDA / GPU

* SAM3 nécessite un GPU compatible CUDA 12.6 ou supérieur
* Sans GPU, SAM3 ne fonctionne pas (cette partie est indispensable au fonctionnement de la recherche d’objets)
