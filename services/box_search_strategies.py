"""
Stratégies de recherche d'objet à partir d'une région (box) dessinée sur une image.

Ce module fournit une abstraction propre pour trois approches de recherche :
 - Embedding : description VLM → embedding → similarité cosinus sur l'index
 - SAM3 : description VLM → recherche SAM3 sur tout le dossier
 - Hybride : embedding pour présélectionner des candidats + SAM3 pour raffiner

Contenu :
 - Classe de base abstraite BoxSearchStrategy
 - EmbeddingBoxSearch : rapide, basé sur la similarité sémantique
 - Sam3BoxSearch : précis, basé sur la détection visuelle SAM3
 - HybridBoxSearch : très précis mais lent, combine les deux approches

Responsabilités :
 1. Définir l'interface commune de toutes les stratégies
 2. Encapsuler la logique de crop et d'appel aux services externes
 3. Retourner une liste triée de (img_name, score) sans dépendance à Qt
 4. Déléguer les appels réseaux à OllamaWrapper et Sam3Service
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image as PILImage

MODEL_VLM = "qwen2.5vl:7b"
MODEL_EMBED = "nomic-embed-text:v1.5"

# Prompt pour la stratégie Embedding (description en Français pour l'index FR)
_PROMPT_EMBED_FR = (
    "Décris précisément l'objet principal de l'image en Français. Donne des hypernymes et concepts associés, retourne une liste des termes uniquement séparés par une virgule sans phrase."
)

# Prompt pour la stratégie SAM3 (anglais car SAM3 prend de l'anglais)
_PROMPT_SAM3_EN = "In one or two English words, name the main object in this image. Return only the object name, nothing else."

# Prompt pour la stratégie Hybride
_PROMPT_HYBRID_EN = (
    "Describe precisely the main object in this image. Provide: "
    "1) A one or two word English name for the object. "
    "2) A comma-separated list of English hypernyms and associated concepts. "
    "Return exactly in this format: NAME: <name>\nCONCEPTS: <concepts>"
)


def crop_pil(pil_image: PILImage.Image, x0: float, y0: float, x1: float, y1: float) -> PILImage.Image:
    """Recadre une image PIL selon des coordonnées pixel.

    Args:
        pil_image: Image PIL source.
        x0, y0: Coin haut-gauche de la box (pixels).
        x1, y1: Coin bas-droit de la box (pixels).

    Returns:
        PIL.Image recadrée, clampée aux dimensions de l'image.
    """
    w, h = pil_image.size
    left = max(0, int(min(x0, x1)))
    top = max(0, int(min(y0, y1)))
    right = min(w, int(max(x0, x1)))
    bottom = min(h, int(max(y0, y1)))
    return pil_image.crop((left, top, right, bottom))


# ── Classe de base ────────────────────────────────────────────────────────────


class BoxSearchStrategy(ABC):
    """Interface commune pour les stratégies de recherche par box."""

    @abstractmethod
    def search(
        self,
        crop: PILImage.Image,
        folder: str,
        images: list[str],
        index: dict,
        client,
        service=None,
        threshold: float = 0.3,
        max_results: int = 0,
        progress_callback=None,
        cancel_check=None,
    ) -> list[tuple[str, float]]:
        """Lance la recherche et retourne les résultats triés.

        Args:
            crop: Image PIL recadrée sur la région d'intérêt.
            folder: Chemin du dossier contenant les images.
            images: Liste des noms de fichiers du dossier.
            index: Index des métadonnées des images (description, embedding…).
            client: Instance OllamaWrapper.
            service: Instance Sam3Service (None si non nécessaire).
            threshold: Score minimum pour retenir une image.
            max_results: Nombre maximum de résultats (0 = illimité).
            progress_callback: callable(done, total, img_name) optionnel.
            cancel_check: callable() -> bool pour annulation coopérative.

        Returns:
            Liste de (img_name, score) triée par score décroissant.
        """


# ── Stratégie 1 : Embedding ───────────────────────────────────────────────────


class EmbeddingBoxSearch(BoxSearchStrategy):
    """Recherche rapide par similarité d'embedding.

    Workflow :
     1. Appel VLM sur le crop pour obtenir une description en Français.
     2. Embedding du texte via nomic-embed-text.
     3. Similarité cosinus contre tous les embeddings de l'index.
     4. Retourne les images triées au-dessus du seuil.
    """

    def search(
        self,
        crop: PILImage.Image,
        folder: str,
        images: list[str],
        index: dict,
        client,
        service=None,
        threshold: float = 0.3,
        max_results: int = 0,
        progress_callback=None,
        cancel_check=None,
    ) -> list[tuple[str, float]]:
        """Cf. BoxSearchStrategy.search."""
        # 1. Description VLM du crop
        result = client.generate_with_image(
            model=MODEL_VLM,
            prompt=_PROMPT_EMBED_FR,
            image=_pil_to_bytes(crop),
        )
        description = result.response.strip()

        if cancel_check and cancel_check():
            return []

        # 2. Embedding du texte
        query_emb = client.embed(model=MODEL_EMBED, text=description)

        # 3. Similarité cosinus sur l'index
        scores: list[tuple[str, float]] = []
        total = len(index)
        for i, (img_name, data) in enumerate(index.items()):
            if cancel_check and cancel_check():
                return []
            if progress_callback:
                progress_callback(i, total, img_name)
            emb = data.get("embedding")
            if not emb:
                continue
            score = client.similarite_cosinus(query_emb, emb)
            if score >= threshold:
                scores.append((img_name, float(score)))

        scores.sort(key=lambda x: x[1], reverse=True)
        if max_results > 0:
            scores = scores[:max_results]
        return scores


# ── Stratégie 2 : SAM3 ───────────────────────────────────────────────────────


class Sam3BoxSearch(BoxSearchStrategy):
    """Recherche précise par détection SAM3.

    Workflow :
     1. Appel VLM pour nommer l'objet en anglais (1-2 mots).
     2. Parcours de toutes les images du dossier avec SAM3.
     3. Retourne les images où le score SAM3 est au-dessus du seuil.
    """

    def search(
        self,
        crop: PILImage.Image,
        folder: str,
        images: list[str],
        index: dict,
        client,
        service=None,
        threshold: float = 0.75,
        max_results: int = 0,
        progress_callback=None,
        cancel_check=None,
    ) -> list[tuple[str, float]]:
        """Cf. BoxSearchStrategy.search."""
        import os

        # 1. Nom de l'objet en anglais via VLM
        result = client.generate_with_image(
            model=MODEL_VLM,
            prompt=_PROMPT_SAM3_EN,
            image=_pil_to_bytes(crop),
        )
        object_name = result.response.strip().splitlines()[0].strip()[:50]

        if cancel_check and cancel_check():
            return []

        if service is None:
            raise ValueError("Sam3BoxSearch nécessite une instance Sam3Service.")

        # 2. SAM3 sur tout le dossier
        matched: list[tuple[str, float]] = []
        total = len(images)

        for i, img_name in enumerate(images):
            if cancel_check and cancel_check():
                return matched

            if progress_callback:
                progress_callback(i, total, img_name)

            img_path = os.path.join(folder, img_name)
            try:
                pil = PILImage.open(img_path).convert("RGB")
                state = service.set_image(pil)
                state = service.apply_text_prompt(object_name, state)
                seg_result = service.extract_result(state)
            except Exception:
                continue

            if not seg_result.scores:
                continue

            best = max(seg_result.scores)
            if best >= threshold:
                matched.append((img_name, float(best)))

        matched.sort(key=lambda x: x[1], reverse=True)
        if max_results > 0:
            matched = matched[:max_results]
        return matched


# ── Stratégie 3 : Hybride ────────────────────────────────────────────────────


class HybridBoxSearch(BoxSearchStrategy):
    """Recherche hybride embedding + SAM3.

    Workflow :
     1. Appel VLM pour obtenir un nom anglais ET des concepts.
     2. Embedding des concepts → présélection des N candidats (seuil bas).
     3. SAM3 sur les candidats seulement avec le nom anglais.
     4. Score final = score_embedding × score_sam3 (ou score_sam3 si > 0).
     5. Retourne triés par score final.
    """

    def search(
        self,
        crop: PILImage.Image,
        folder: str,
        images: list[str],
        index: dict,
        client,
        service=None,
        threshold: float = 0.3,
        max_results: int = 0,
        progress_callback=None,
        cancel_check=None,
    ) -> list[tuple[str, float]]:
        """Cf. BoxSearchStrategy.search."""
        import os

        if service is None:
            raise ValueError("HybridBoxSearch nécessite une instance Sam3Service.")

        # 1. Description hybride via VLM
        result = client.generate_with_image(
            model=MODEL_VLM,
            prompt=_PROMPT_HYBRID_EN,
            image=_pil_to_bytes(crop),
        )
        raw = result.response.strip()
        object_name, concepts = _parse_hybrid_response(raw)

        if cancel_check and cancel_check():
            return []

        # 2. Embedding des concepts → présélection
        embed_text = f"{object_name} {concepts}" if concepts else object_name
        query_emb = client.embed(model=MODEL_EMBED, text=embed_text)

        embed_candidates: list[tuple[str, float]] = []
        for img_name, data in index.items():
            emb = data.get("embedding")
            if not emb:
                continue
            score = client.similarite_cosinus(query_emb, emb)
            if score >= threshold:
                embed_candidates.append((img_name, float(score)))

        embed_candidates.sort(key=lambda x: x[1], reverse=True)
        candidate_set = {name for name, _ in embed_candidates}
        embed_score_map = dict(embed_candidates)

        if cancel_check and cancel_check():
            return []

        # 3. SAM3 sur les candidats uniquement
        final_scores: list[tuple[str, float]] = []
        total = len(candidate_set)

        for i, img_name in enumerate(candidate_set):
            if cancel_check and cancel_check():
                return final_scores

            if progress_callback:
                progress_callback(i, total, img_name)

            img_path = os.path.join(folder, img_name)
            try:
                pil = PILImage.open(img_path).convert("RGB")
                state = service.set_image(pil)
                state = service.apply_text_prompt(object_name, state)
                seg_result = service.extract_result(state)
            except Exception:
                # En cas d'échec SAM3, on garde le score embedding seul dégradé
                final_scores.append((img_name, embed_score_map[img_name] * 0.5))
                continue

            if seg_result.scores:
                sam3_score = max(seg_result.scores)
                # Score final = embedding × SAM3 si SAM3 > 0, sinon embedding dégradé
                if sam3_score > 0:
                    combined = embed_score_map[img_name] * sam3_score
                else:
                    combined = embed_score_map[img_name] * 0.3
                final_scores.append((img_name, float(combined)))
            else:
                final_scores.append((img_name, embed_score_map[img_name] * 0.3))

        final_scores.sort(key=lambda x: x[1], reverse=True)
        if max_results > 0:
            final_scores = final_scores[:max_results]
        return final_scores


# ── Helpers internes ──────────────────────────────────────────────────────────


def _pil_to_bytes(pil_image: PILImage.Image) -> bytes:
    """Convertit une PIL.Image en bytes JPEG pour OllamaWrapper.generate_with_image.

    Args:
        pil_image: Image PIL à convertir.

    Returns:
        Bytes JPEG de l'image.
    """
    import io

    buf = io.BytesIO()
    pil_image.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _parse_hybrid_response(raw: str) -> tuple[str, str]:
    """Parse la réponse du prompt hybride.

    Extrait le nom anglais de l'objet et les concepts associés.

    Args:
        raw: Réponse brute du modèle VLM.

    Returns:
        Tuple (object_name, concepts_string). En cas d'échec du parsing,
        retourne (raw[:40], "").
    """
    name = ""
    concepts = ""
    for line in raw.splitlines():
        line = line.strip()
        if line.upper().startswith("NAME:"):
            name = line[5:].strip()
        elif line.upper().startswith("CONCEPTS:"):
            concepts = line[9:].strip()
    if not name:
        # Fallback : première ligne comme nom
        name = raw.splitlines()[0].strip()[:40] if raw else "object"
    return name, concepts


# ── Factory ───────────────────────────────────────────────────────────────────

STRATEGIES: dict[str, type[BoxSearchStrategy]] = {
    "embedding": EmbeddingBoxSearch,
    "sam3": Sam3BoxSearch,
    "hybrid": HybridBoxSearch,
}


def get_strategy(name: str) -> BoxSearchStrategy:
    """Instancie une stratégie par son nom.

    Args:
        name: "embedding", "sam3" ou "hybrid".

    Returns:
        Instance de BoxSearchStrategy.

    Raises:
        KeyError: si le nom est inconnu.
    """
    cls = STRATEGIES.get(name.lower())
    if cls is None:
        raise KeyError(f"Stratégie inconnue : {name!r}. Valeurs acceptées : {list(STRATEGIES)}")
    return cls()
