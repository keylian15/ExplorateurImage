
# ------------------------------
# Exceptions spécifiques (pédagogie + robustesse)
# ------------------------------
# Permet les annotations de types en avant-référence (Python < 3.11)
from __future__ import annotations

import base64  # Encodage base64 requis pour envoyer des images à /api/generate
import json  # Sérialisation/désérialisation JSON
import shutil  # Pour trouver l'exécutable "ollama" dans le PATH
import socket  # Pour tester rapidement si un port TCP est ouvert
import subprocess  # Pour lancer "ollama serve"
import time  # Pour boucler avec un timeout lors du démarrage serveur
from dataclasses import dataclass  # Modèles de données simples et typés
from pathlib import Path  # Manipulation robuste des chemins
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union  # Types


# ------------------------------
# Exceptions spécifiques (pédagogie + robustesse)
# ------------------------------

class OllamaError(RuntimeError):
    """Erreur générique pour les opérations Ollama."""


class OllamaConnectionError(OllamaError):
    """Erreur de connexion au serveur Ollama."""


class OllamaResponseError(OllamaError):
    """Erreur lorsque la réponse HTTP/JSON d'Ollama est invalide ou inattendue."""


class OllamaServerStartError(OllamaError):
    """Erreur lorsque le serveur Ollama ne démarre pas correctement."""


# ------------------------------
# Dataclasses pour structurer les réponses (lisible + typé)
# ------------------------------

@dataclass(frozen=True, slots=True)
class OllamaModelDetails:
    """Détails d'un modèle, tels que renvoyés dans /api/tags."""
    format: Optional[str] = None
    family: Optional[str] = None
    families: Optional[List[str]] = None
    parameter_size: Optional[str] = None
    quantization_level: Optional[str] = None


@dataclass(frozen=True, slots=True)
class OllamaModelInfo:
    """Informations de base sur un modèle installé (issu de /api/tags)."""
    name: str
    modified_at: Optional[str] = None
    size: Optional[int] = None
    digest: Optional[str] = None
    details: Optional[OllamaModelDetails] = None


@dataclass(frozen=True, slots=True)
class OllamaGenerateResult:
    """Résultat simplifié de /api/generate en mode stream=false."""
    response: str
    model: Optional[str] = None
    done: Optional[bool] = None
    total_duration: Optional[int] = None  # ns (souvent)
    load_duration: Optional[int] = None
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None


# ------------------------------
# Wrapper principal
# ------------------------------

class OllamaWrapper:
    """
    Wrapper Python (simple, robuste, typé) autour de l'API HTTP d'Ollama.

    Base URL par défaut : xxxx
    Endpoints utilisés :
      - GET  /api/version       (vérifier serveur)
      - GET  /api/tags          (liste des modèles installés)
      - POST /api/generate      (génération texte + multimodal via images base64)
    La doc officielle liste aussi d'autres endpoints (chat, pull, delete, etc.). :contentReference[oaicite:2]{index=2}
    """

    # Constructeur : on fixe l'hôte/timeout et on prépare des valeurs par défaut.
    def __init__(
        self,
        base_url: str = "http://10.22.28.190:11434",
        timeout_s: float = 240.0,
    ) -> None:
        self._base_url: str = base_url.rstrip(
            "/")  # Normalise : pas de "/" final
        self._timeout_s: float = timeout_s  # Timeout réseau pour les requêtes HTTP

    # --------------------------
    # Méthodes "système"
    # --------------------------

    def is_server_running(self) -> bool:
        """
        Retourne True si le serveur Ollama répond.

        Stratégie : on essaie GET /api/version (léger et dédié à ça).
        """
        try:
            _ = self.get_version()  # Appel dédié à la version
            return True  # Si pas d'exception : serveur OK
        except OllamaConnectionError:
            return False  # Pas de serveur (ou port inaccessible)
        except OllamaResponseError:
            # Serveur répond mais réponse inattendue : on considère "running"
            return True

    def start_server(
        self,
        *,
        wait: bool = True,
        wait_timeout_s: float = 10.0,
        extra_env: Optional[Mapping[str, str]] = None,
    ) -> subprocess.Popen[bytes]:
        """
        Lance `ollama serve` via subprocess.

        Args:
            wait: si True, attend que le port réponde avant de rendre la main.
            wait_timeout_s: durée max d'attente si wait=True.
            extra_env: variables d'environnement supplémentaires (optionnel).

        Returns:
            Un objet Popen (process serveur).

        Raises:
            OllamaServerStartError: si ollama n'est pas trouvé ou ne démarre pas.
        """
        # Vérifie que l'exécutable "ollama" est présent dans le PATH.
        ollama_path: Optional[str] = shutil.which("ollama")
        if ollama_path is None:
            raise OllamaServerStartError(
                "Exécutable 'ollama' introuvable. Installe Ollama et/ou ajoute-le au PATH."
            )

        # Prépare l'environnement du processus.
        env: Dict[str, str] = dict(**(extra_env or {}))  # Copie défensive
        # Note : on laisse le reste de l'environnement hérité du parent (comportement standard).

        # Lance le serveur : stdout/stderr sont capturés pour debug/enseignement.
        process: subprocess.Popen[bytes] = subprocess.Popen(
            [ollama_path, "serve"],  # Commande
            stdout=subprocess.PIPE,  # Capture stdout
            stderr=subprocess.PIPE,  # Capture stderr
            env={**dict(**subprocess.os.environ), **env},  # Hérite + ajoute
        )

        # Si on ne veut pas attendre, on rend immédiatement la main.
        if not wait:
            return process

        # Attend que le serveur soit accessible, avec timeout.
        deadline: float = time.time() + wait_timeout_s
        while time.time() < deadline:
            if self._is_port_open():
                return process  # Serveur accessible : OK
            # Vérifie si le process est mort prématurément.
            if process.poll() is not None:
                # Process terminé -> on récupère stderr pour diagnostic.
                stderr: bytes = process.stderr.read() if process.stderr else b""
                raise OllamaServerStartError(
                    "Le serveur Ollama s'est arrêté pendant le démarrage.\n"
                    f"stderr:\n{stderr.decode(errors='replace')}"
                )
            time.sleep(0.1)  # Petite attente avant de retester

        # Timeout : serveur non accessible à temps.
        raise OllamaServerStartError(
            f"Le serveur Ollama ne répond pas après {wait_timeout_s:.1f}s."
        )

    def _is_port_open(self) -> bool:
        """
        Test rapide TCP du port du base_url (sans HTTP).

        Utile pour savoir si quelque chose écoute déjà, sans dépendre d'une réponse JSON.
        """
        host, port = self._parse_host_port()  # Extrait hôte/port de base_url
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            return False

    def _parse_host_port(self) -> tuple[str, int]:
        """Parse très simple de base_url -> (host, port)."""
        # On gère uniquement le cas standard http://host:port
        # (pédagogiquement : clair ; production : on pourrait utiliser urllib.parse).
        url: str = self._base_url
        if url.startswith("http://"):
            url = url[len("http://"):]
        elif url.startswith("https://"):
            url = url[len("https://"):]
        # Si pas de port explicite, Ollama utilise 11434.
        if ":" in url:
            host, port_str = url.split(":", 1)
            return host, int(port_str)
        return url, 11434

    # --------------------------
    # Endpoints "information"
    # --------------------------

    def get_version(self) -> str:
        """
        Retourne la version du serveur Ollama via GET /api/version. :contentReference[oaicite:3]{index=3}
        """
        payload = self._http_request_json("GET", "/api/version", body=None)
        # La doc renvoie typiquement { "version": "x.y.z" }.
        version = payload.get("version")
        if not isinstance(version, str):
            raise OllamaResponseError(
                f"Réponse /api/version inattendue: {payload!r}")
        return version

    def list_models(self) -> List[OllamaModelInfo]:
        """
        Liste les modèles installés via GET /api/tags. :contentReference[oaicite:4]{index=4}
        """
        payload = self._http_request_json("GET", "/api/tags", body=None)
        raw_models = payload.get("models")
        if not isinstance(raw_models, list):
            raise OllamaResponseError(
                f"Réponse /api/tags inattendue: {payload!r}")

        models: List[OllamaModelInfo] = []
        for item in raw_models:
            # Chaque entrée doit être un dict.
            if not isinstance(item, dict):
                continue

            name = item.get("name")
            if not isinstance(name, str):
                continue

            # Détails optionnels.
            raw_details = item.get("details")
            details: Optional[OllamaModelDetails] = None
            if isinstance(raw_details, dict):
                details = OllamaModelDetails(
                    format=raw_details.get("format") if isinstance(
                        raw_details.get("format"), str) else None,
                    family=raw_details.get("family") if isinstance(
                        raw_details.get("family"), str) else None,
                    families=raw_details.get("families") if isinstance(
                        raw_details.get("families"), list) else None,
                    parameter_size=raw_details.get("parameter_size") if isinstance(
                        raw_details.get("parameter_size"), str) else None,
                    quantization_level=raw_details.get("quantization_level") if isinstance(
                        raw_details.get("quantization_level"), str) else None,
                )

            models.append(
                OllamaModelInfo(
                    name=name,
                    modified_at=item.get("modified_at") if isinstance(
                        item.get("modified_at"), str) else None,
                    size=item.get("size") if isinstance(
                        item.get("size"), int) else None,
                    digest=item.get("digest") if isinstance(
                        item.get("digest"), str) else None,
                    details=details,
                )
            )

        return models

    # --------------------------
    # Génération
    # --------------------------

    def generate_text(
        self,
        *,
        model: str,
        prompt: str,
        system: Optional[str] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> OllamaGenerateResult:
        """
        Appelle POST /api/generate en texte seul (stream=false). :contentReference[oaicite:5]{index=5}

        Args:
            model: nom du modèle (ex: "llama3", "mistral", etc.)
            prompt: le prompt utilisateur
            system: message système (optionnel, dépend des modèles/versions)
            options: paramètres avancés Ollama (température, top_p, seed, etc.)

        Returns:
            OllamaGenerateResult : réponse texte + quelques métriques si présentes.
        """
        body: Dict[str, Any] = {
            "model": model,       # Modèle ciblé
            "prompt": prompt,     # Prompt texte
            "stream": False,      # On veut une réponse complète en une fois
        }

        # Ajoute le système si fourni.
        if system is not None:
            body["system"] = system

        # Ajoute les options avancées si fournies.
        if options is not None:
            body["options"] = dict(options)

        payload = self._http_request_json("POST", "/api/generate", body=body)

        # Extrait la réponse principale.
        response_text = payload.get("response")
        if not isinstance(response_text, str):
            raise OllamaResponseError(
                f"Réponse /api/generate inattendue: {payload!r}")

        return OllamaGenerateResult(
            response=response_text,
            model=payload.get("model") if isinstance(
                payload.get("model"), str) else None,
            done=payload.get("done") if isinstance(
                payload.get("done"), bool) else None,
            total_duration=payload.get("total_duration") if isinstance(
                payload.get("total_duration"), int) else None,
            load_duration=payload.get("load_duration") if isinstance(
                payload.get("load_duration"), int) else None,
            prompt_eval_count=payload.get("prompt_eval_count") if isinstance(
                payload.get("prompt_eval_count"), int) else None,
            eval_count=payload.get("eval_count") if isinstance(
                payload.get("eval_count"), int) else None,
        )

    def generate_with_image(
        self,
        *,
        model: str,
        prompt: str,
        image: Union[str, Path, bytes],
        image_mime_hint: Optional[str] = None,
        system: Optional[str] = None,
        options: Optional[Mapping[str, Any]] = None,
    ) -> OllamaGenerateResult:
        """
        Appelle POST /api/generate avec une image (multimodal).
        Ollama attend une liste "images" contenant des chaînes base64. :contentReference[oaicite:6]{index=6}

        Args:
            model: modèle vision (ex: "llava", "qwen2.5-vl", etc.)
            prompt: instruction texte
            image: chemin (str/Path) ou bytes de l'image
            image_mime_hint: non requis par Ollama, mais utile si tu veux tracer/enseigner
            system: message système optionnel
            options: options de génération

        Returns:
            OllamaGenerateResult
        """
        # Convertit l'image en bytes.
        image_bytes: bytes
        if isinstance(image, (str, Path)):
            image_path = Path(image)  # Normalise en Path
            image_bytes = image_path.read_bytes()  # Lit le fichier
        elif isinstance(image, (bytes, bytearray)):
            image_bytes = bytes(image)  # Normalise en bytes
        else:
            raise TypeError(
                "image doit être un chemin (str/Path) ou des bytes.")

        # Encode en base64 (ASCII) comme attendu par l'API.
        image_b64: str = base64.b64encode(image_bytes).decode("ascii")

        body: Dict[str, Any] = {
            "model": model,           # Modèle multimodal
            "prompt": prompt,         # Prompt
            # Liste base64 (même pour une seule image)
            "images": [image_b64],
            "stream": False,          # Réponse complète
        }

        # Ajoute le système si fourni.
        if system is not None:
            body["system"] = system

        # Ajoute les options avancées si fournies.
        if options is not None:
            body["options"] = dict(options)

        # (Optionnel) on peut conserver un hint MIME à des fins de debug, sans l'envoyer.
        _ = image_mime_hint  # Evite un "unused var" si tu montres aux étudiants

        payload = self._http_request_json("POST", "/api/generate", body=body)

        response_text = payload.get("response")
        if not isinstance(response_text, str):
            raise OllamaResponseError(
                f"Réponse /api/generate (image) inattendue: {payload!r}")

        return OllamaGenerateResult(
            response=response_text,
            model=payload.get("model") if isinstance(
                payload.get("model"), str) else None,
            done=payload.get("done") if isinstance(
                payload.get("done"), bool) else None,
            total_duration=payload.get("total_duration") if isinstance(
                payload.get("total_duration"), int) else None,
            load_duration=payload.get("load_duration") if isinstance(
                payload.get("load_duration"), int) else None,
            prompt_eval_count=payload.get("prompt_eval_count") if isinstance(
                payload.get("prompt_eval_count"), int) else None,
            eval_count=payload.get("eval_count") if isinstance(
                payload.get("eval_count"), int) else None,
        )

    # --------------------------
    # Bonus : embeddings (optionnel pour ton cours)
    # --------------------------

    def embed(
        self,
        *,
        model: str,
        text: str,
    ) -> List[float]:
        """
        Génère un embedding.

        Note doc : l'endpoint "Generate Embedding" a été supersédé par /api/embed
        (selon docs/api.md). :contentReference[oaicite:7]{index=7}
        """
        body: Dict[str, Any] = {"model": model, "input": text}
        payload = self._http_request_json("POST", "/api/embed", body=body)

        # Selon versions, la forme peut varier ; on vise un cas courant : {"embeddings":[[...]]} ou {"embedding":[...]}.
        if isinstance(payload.get("embedding"), list):
            emb = payload["embedding"]
            if all(isinstance(x, (int, float)) for x in emb):
                return [float(x) for x in emb]

        if isinstance(payload.get("embeddings"), list) and payload["embeddings"]:
            first = payload["embeddings"][0]
            if isinstance(first, list) and all(isinstance(x, (int, float)) for x in first):
                return [float(x) for x in first]

        raise OllamaResponseError(
            f"Réponse /api/embed inattendue: {payload!r}")

    def build_embedding(self, description, keywords):
        return f"{description}\n\nConcepts clés : {', '.join(keywords)}"

    # --------------------------
    # Couche HTTP (sans dépendance externe)
    # --------------------------

    def _http_request_json(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        """
        Exécute une requête HTTP et retourne un dict JSON.

        On utilise urllib (stdlib) pour éviter une dépendance à requests/httpx dans un contexte étudiant.
        """
        # Import local pour ne pas polluer le namespace global et montrer le principe.
        import urllib.error  # Exceptions réseau HTTP
        import urllib.request  # Client HTTP standard
        from urllib.parse import urljoin  # Construit proprement l'URL finale

        # Construit l'URL complète.
        url: str = urljoin(self._base_url + "/", path.lstrip("/"))

        # Prépare les headers.
        headers: Dict[str, str] = {
            "Accept": "application/json",            # On attend du JSON
            "Content-Type": "application/json",      # Si body présent
        }

        # Sérialise le body en JSON si nécessaire.
        data: Optional[bytes]
        if body is None:
            data = None
        else:
            data = json.dumps(body).encode("utf-8")  # JSON -> bytes UTF-8

        # Construit l'objet Request.
        request = urllib.request.Request(
            url=url,
            data=data,
            headers=headers,
            method=method.upper(),
        )

        try:
            # Exécute la requête avec timeout.
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                raw: bytes = response.read()  # Lit tout le corps
        except urllib.error.URLError as e:
            # Typiquement : connection refused, host unreachable, timeout, etc.
            raise OllamaConnectionError(
                f"Impossible de joindre Ollama à {url}: {e}") from e
        except Exception as e:
            # Autres erreurs réseau inattendues.
            raise OllamaConnectionError(
                f"Erreur réseau vers {url}: {e}") from e

        # Décode en texte.
        text = raw.decode("utf-8", errors="replace")

        # Parse JSON.
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise OllamaResponseError(
                f"Réponse non-JSON depuis {url} (début): {text[:200]!r}"
            ) from e

        # On attend un dict JSON.
        if not isinstance(payload, dict):
            raise OllamaResponseError(
                f"JSON inattendu depuis {url}: {payload!r}")

        return payload

    def contenu_json(self, filename: str):
        """Renvoie le contenu d'un fichier json

        Args:
            filename (str): Le nom du fichier

        Returns:
            Any: Le contenu du fichier.
        """

        import json

        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        return data

    def classifier_mail(self):
        """
        Fonction qui répond au TP1. Elle classe les mails en 3 catégories :
        - Email personnel
        - Demande de rendez-vous
        - Propositions commerciales (devis)

        Les résultats ne sont pas les meilleurs, il faudrait que ma question soit plus précise ou que mon system_promt soit plus strict.
        """

        # Je défini ma question de base
        question = "Je vais te passer des mails, tu va me dire si c'est un email personnel et/ou une demande de rendez vous et/ou une propositions commerciales (devis). Tu n'expliras pas la réponse\n"

        # Je défini mon system :
        system_prompt = (
            "Tu es un classificateur d'emails.\n"
            "Ta tache est de classer chaque email dans une seule catégorie.\n\n"
            "Catégories possibles :\n"
            "- personnel\n"
            "- rendez_vous\n"
            "- propositions commerciales\n\n"
            "Règles Obligatoires :\n"
            "- Une seule catégorie obligatoire\n"
            "- Aucun texte explicatif\n"
            "- Aucune phrase\n"
            "- Réponds uniquement par la catégorie\n\n"
        )

        # Je récupere mes mails
        emails = self.contenu_json("data/emails.json")

        # Je récupere mes models
        models = self.list_models()

        # Je test deux fois, la premiere sans le system_promt et la deuxieme avec
        for i in range(2):

            if i == 0:

                print(f"\n----- SANS Systeme Promt ----- ")
                s_p = None
            else:

                print(f"\n----- AVEC Systeme Promt ----- ")
                s_p = system_prompt

            # Je boucle sur mes models
            for model in models:

                print(f"\n----- Model : {model.name} ----- ")
                # Je boucle sur mes mails
                for email in emails:
                    # Try/Except pour l'impossibilité de joindre un serveur
                    try:
                        r = self.generate_text(
                            model=model.name, prompt=question +
                            email['content'],
                            system=s_p)
                        print(f"Email n°{email['id']} : {r.response}")
                    except OllamaConnectionError as e:
                        print(
                            f"Erreur lors de la requête pour l'email n°{email['id']} : {e}")

    def classifier_image(self):
        """
        Fonction qui répond au TP1. Elle classe les mails en 3 catégories :
            - Email personnel
            - Demande de rendez-vous
            - Propositions commerciales (devis)

        Les résultats ne sont pas les meilleurs, il faudrait que ma question soit plus précise.

        """

        # Je défini ma question de base
        question = "Je vais te passer une image, peux-tu me dire si c'est des bureaux (travail) ou des scènes de vacances (loisirs) ?"

        # Je défini mon system prompt
        system_prompt = "Tu es un expert en reconnaissance d'images. Tu fera une réponse courte. Bureaux ou Vacances ?"

        # Je récupere mes models
        model = self.list_models()[1]  # On prend qwen2.5vl:7b

        # Les 4 images
        images = [
            "bureau_01.png",
            "bureau_02.png",
            "vacances_01.png",
            "vacances_02.png",
            "chien.png",  # Chien dans la nature
            "chien_bureau.png",  # Chien dans le bureau
        ]

        # Je boucle sur les images
        for image in images:

            r = self.generate_with_image(
                model=model.name, prompt=question, image="images/" + image, system=system_prompt)
            image_nom = image.split(".")[0]
            print(f"\nImage {image_nom} : {r.response}")

    def similarite_cosinus(self, vec_a: list[float], vec_b: list[float]) -> float:
        """
        Calcule la similarité cosinus entre deux vecteurs numériques.
        Retourne un score entre -1 et 1, pour les embeddings c'est entre 0 et 1.
        """
        import math

        # Produit scalaire
        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))

        # Normes des vecteurs
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        # Sécurité
        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    def score_mots_cles(self, requete: str, document: str) -> int:
        """
        Score basé sur la fréquence des mots de la requête dans le document (TF simple)
        GENERER PAR CHATGPT, A VERIFIER ET TESTER

        Args : 
            requete (str): Mots clés de la requête
            document (str): Contenu du document

        Returns : 
            int : Score de similarité
        """
        import re
        from collections import Counter

        # Nettoyage + tokenisation
        requete_tokens = re.findall(r"\w+", requete.lower())
        doc_tokens = re.findall(r"\w+", document.lower())

        doc_counter = Counter(doc_tokens)

        # Somme des occurrences des mots de la requête
        score = sum(doc_counter[token] for token in requete_tokens)

        return score

    def best_result(self, requete: str, nb_results: int = 5, semantique: bool = True) -> list:
        """Fonction permettant d'avoir les 5 meilleurs résultats pour une requete

        Args:
            requete (str): La requete à envoyer
            nb_results (int, optional): Le nombre de résultats à renvoyer. Defaults to 5.
            semantique (bool, optional): Si on veut utiliser la similarité cosinus ou non. Defaults to True.

        Returns:
            list: Liste des 5 meilleurs résultats
        """

        # Charger les données
        contenu = self.contenu_json("data/documents.json")

        # Je récupere mes models
        models = self.list_models()

        # Calculer l'embedding pour la requête
        requete_embedding = self.embed(model=models[0].name, text=requete)

        if semantique:

            # Calculer un embedding pour chaque document
            for doc in contenu:

                # Calculer l'embedding pour le document
                doc_embedding = self.embed(
                    model=models[0].name,
                    text=doc['content'])

                # Calculer la similarité cosinus entre la requête et le document
                similarite = self.similarite_cosinus(
                    requete_embedding, doc_embedding)

                # Stocker la similarité
                doc['similarite'] = similarite

        else:
            for doc in contenu:
                doc['similarite'] = self.score_mots_cles(
                    requete, doc['content'])

        # Trier les documents par score
        contenu.sort(key=lambda x: x['similarite'], reverse=True)

        return contenu[:nb_results]

    def RAG(self, requete: str):
        """Fonction RAG, qui permet de lier les meilleurs résultats avec le LLM

        Args:
            requete (str): La réquête utilisateur.
        """

        # Je récupere mes models
        models = self.list_models()

        # Récupérer les 3 documents les + probables
        documents = self.best_result(requete=requete, nb_results=3)

        # Construit le promt
        prompt = f"Répond a la réquete : {requete} en fonction de ces 3 documents : {documents}"

        # On fait le system_promt
        system_prompt = system_prompt = """
            Tu es un assistant de question-réponse basé sur des documents.
            Tu dois répondre exclusivement à partir des informations contenues dans les documents fournis dans le prompt.

            Les documents sont une liste de dictionnaires contenant les clés suivantes :
            - id
            - title
            - content
            - similarité

            Règles strictes :
            - N'utilise aucune connaissance externe.
            - N'invente aucune information.
            - Si les documents ne permettent pas de répondre clairement à la requête, indique-le explicitement.
            - Si aucun des documents n'est pertinent pour la réponse, indique le.

            Format de la réponse :
            1. Réponse synthétique à la requête.
            2. En fin de réponse, ajoute une section exactement sous la forme :

            **Sources :**
            - Doc N°<id> - <title>

            3. Ajoute enfin un score de confiance global basé sur la similarité des documents utilisés (exprimé en pourcentage).
            """

        # On boucle sur les modéles
        for model in models:

            try:

                # Information
                print(f"\n\t\t====== Modele : {model.name} ======")

                # On fait la requete
                r = self.generate_text(
                    model=model.name, prompt=prompt, system=system_prompt)

                # On affiche la réponse
                print(r.response)

            except Exception as e:
                print(f"Erreur pour le modèle {model.name} : {e}")

    def get_images_from_folder(self, folder_path: str) -> list:
        import os

        images = []

        for file_name in os.listdir(folder_path):
            if file_name.endswith('.jpg') or file_name.endswith('.png'):
                images.append(os.path.join(folder_path, file_name))
        return images

    def get_description_and_keywords_from_image(self, image_path: str):
        question = (
            "Décris cette image pour un moteur de recherche. "
            "Réponds uniquement dans ce format :\n\n"
            "Description: <2 à 4 phrases>\n"
            "Keywords: <mot1>, <mot2>, <mot3>, <mot4>, <mot5>"
        )

        system_prompt = (
            "Tu es un système d'indexation d'images pour la recherche sémantique.\n\n"

            "DESCRIPTION — 2 à 4 phrases, pas plus :\n"
            "- Sujet principal : qui/quoi, nombre, couleur, race/espèce si identifiable\n"
            "- Contexte : lieu, environnement, moment de la journée si visible\n"
            "- Actions ou interactions visibles\n"
            "- Un seul détail d'ambiance utile (météo, lumière, saison)\n"
            "- Pas de suppositions, pas de métaphores, pas d'émotions prêtées\n\n"

            "MOTS-CLÉS — exactement 5 :\n"
            "- Noms uniquement (pas d'adjectifs, pas de verbes)\n"
            "- Ordre : sujet → environnement → détails distinctifs\n"
            "- Privilégier les termes de recherche qu'un utilisateur taperait\n"
            "- Pas de doublons avec les premiers mots de la description\n"
            "- Éviter les génériques inutiles : 'lumière', 'image', 'photo', 'nature', 'atmosphère'\n\n"

            "FORMAT STRICT — aucun autre texte :\n"
            "Description: <texte>\n"
            "Keywords: <mot1>, <mot2>, <mot3>, <mot4>, <mot5>"
        )

        model = "qwen2.5vl:7b"

        r = self.generate_with_image(
            model=model,
            prompt=question,
            image=image_path,
            system=system_prompt
        )

        response = r.response.strip()

        try:
            desc_part = response.split("Description:")[1].split("Keywords:")[0].strip()
            keywords_part = response.split("Keywords:")[1].strip()
            keywords = [k.strip() for k in keywords_part.split(",")]
        except:
            desc_part = response
            keywords = []

        return {
            "description": desc_part,
            "keywords": keywords
        }
        
    def get_description_and_keywords(self, folder_path: str):
        images = self.get_images_from_folder(folder_path)

        data = []

        for i, image_path in enumerate(images):

            result = self.get_description_and_keywords_from_image(image_path)

            data.append({
                "id": f"img_{i}",
                "path": image_path,
                "description": result["description"],
                "keywords": result["keywords"]
            })

        return data

# ------------------------------
# Exemple d'utilisation (utile en TD)
# ------------------------------
if __name__ == "__main__":
    client = OllamaWrapper()

    print("Server running?", client.is_server_running())

    if client.is_server_running():
        print("Version:", client.get_version())
        print("Models:", [m.name for m in client.list_models()])
        
        