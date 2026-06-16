"""
Service d'encapsulation de SAM3 (Segment Anything Model 3).

Ce module fournit une couche d'abstraction propre autour de l'API SAM3,
permettant de charger le modèle, d'appliquer des prompts texte ou boîte,
et de récupérer les résultats de segmentation sous forme de données exploitables
par les ViewModels.

Contenu :
 - Chargement du modèle SAM3 (build_sam3_image_model + Sam3Processor)
 - Initialisation de l'état à partir d'une image PIL
 - Segmentation par prompt texte
 - Segmentation par prompt boîte (coordonnées pixel → normalisées cxcywh)
 - Reset des prompts
 - Extraction des résultats (masques, boîtes, scores) en numpy

Responsabilités :
 1. Encapsuler l'API SAM3 dans une interface simple et stable
 2. Résoudre le chemin du fichier BPE de manière robuste (double niveau sam3/sam3/)
 3. Gérer la conversion des coordonnées boîte (pixel xyxy → cxcywh normalisé)
 4. Retourner des résultats sous forme de dicts Python natifs (numpy arrays)
 5. Isoler les imports torch/sam3 afin de ne pas bloquer le démarrage si absent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PyQt6.QtCore import QObject

# ── Résultat de segmentation ──────────────────────────────────────────────────


@dataclass
class SegmentationResult:
    """Résultat d'une segmentation SAM3."""

    masks: list[np.ndarray] = field(default_factory=list)  # (H, W) bool chacun
    boxes_xyxy: list[list[float]] = field(default_factory=list)  # [[x0,y0,x1,y1], ...]
    scores: list[float] = field(default_factory=list)
    img_w: int = 0
    img_h: int = 0


# ── Service principal ─────────────────────────────────────────────────────────


class Sam3Service(QObject):
    """
    Wrapper autour de Sam3Processor.

    Usage type :
        service = Sam3Service()
        service.load_model()
        state   = service.set_image(pil_image)
        state   = service.apply_text_prompt("dog", state)
        result  = service.extract_result(state)
        state   = service.reset_prompts(state)
    """

    def __init__(self):
        super().__init__()
        self._model = None
        self._processor = None
        self._is_loaded = False
        self._is_loading = False

    # ── Chargement ────────────────────────────────────────────────────────────

    @staticmethod
    def _find_bpe_path() -> str:
        """Retourne le chemin du fichier BPE relatif au dossier d'exécution."""
        return str(Path("sam3") / "sam3" / "assets" / "bpe_simple_vocab_16e6.txt.gz")

    @property
    def is_loading(self) -> bool:
        """Indique si le modèle est en cours de chargement."""
        return self._is_loading

    def load_model(self, confidence_threshold: float = 0.5) -> None:
        """
        Charge le modèle SAM3. Bloquant - à appeler depuis un worker.

        Args:
            confidence_threshold: seuil de confiance par défaut.

        Raises:
            ImportError: si sam3 ou torch ne sont pas installés.
            FileNotFoundError: si le fichier BPE est introuvable.
            RuntimeError: si le chargement échoue.
        """
        self._is_loading = True
        try:
            from sam3.sam3 import build_sam3_image_model
            from sam3.sam3.model.sam3_image_processor import Sam3Processor

            bpe_path = self._find_bpe_path()

            self._model = build_sam3_image_model(bpe_path=bpe_path)
            self._processor = Sam3Processor(
                self._model,
                confidence_threshold=confidence_threshold,
            )
            self._is_loaded = True
            self.signal_loaded.emit()
        finally:
            self._is_loading = False

    @property
    def is_loaded(self) -> bool:
        """Indique si le modèle est chargé."""
        return self._is_loaded

    # ── Image ─────────────────────────────────────────────────────────────────

    def set_image(self, pil_image) -> dict[str, Any]:
        """
        Initialise l'état SAM3 à partir d'une image PIL RGB.

        Args:
            pil_image: PIL.Image en mode RGB.

        Returns:
            dict state utilisable par les méthodes suivantes.
        """
        self._check_loaded()
        import torch

        with torch.autocast("cuda" if torch.cuda.is_available() else "cpu", dtype=torch.bfloat16):
            return self._processor.set_image(pil_image)

    # ── Prompts ───────────────────────────────────────────────────────────────

    def apply_text_prompt(self, prompt: str, state: dict[str, Any]) -> dict[str, Any]:
        """
        Applique un prompt texte sur l'état courant.

        Args:
            prompt: texte décrivant l'objet (ex : "shoe").
            state: état SAM3 retourné par set_image.

        Returns:
            Nouvel état avec masques mis à jour.
        """
        self._check_loaded()
        import torch

        with torch.autocast("cuda" if torch.cuda.is_available() else "cpu", dtype=torch.bfloat16):
            return self._processor.set_text_prompt(prompt, state)

    def apply_box_prompt(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        img_w: int,
        img_h: int,
        state: dict[str, Any],
        positive: bool = True,
    ) -> dict[str, Any]:
        """
        Applique un prompt boîte en coordonnées pixel xyxy.

        Convertit en cxcywh normalisé comme attendu par SAM3.

        Args:
            x0, y0, x1, y1: coordonnées pixel (coin haut-gauche → bas-droit).
            img_w, img_h: dimensions de l'image originale.
            state: état SAM3 courant.
            positive: True = inclure, False = exclure.

        Returns:
            Nouvel état avec masques mis à jour.
        """
        self._check_loaded()

        # Conversion xyxy pixel → cxcywh normalisé
        cx = (x0 + x1) / 2.0 / img_w
        cy = (y0 + y1) / 2.0 / img_h
        w = abs(x1 - x0) / img_w
        h = abs(y1 - y0) / img_h
        box_cxcywh = [cx, cy, w, h]

        import torch

        with torch.autocast("cuda" if torch.cuda.is_available() else "cpu", dtype=torch.bfloat16):
            return self._processor.add_geometric_prompt(box_cxcywh, positive, state)

    def reset_prompts(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Supprime tous les prompts et réinitialise les masques.

        Args:
            state: état SAM3 courant.

        Returns:
            État nettoyé (encodage image conservé).
        """
        self._check_loaded()
        new_state = self._processor.reset_all_prompts(state)
        if new_state is None:
            new_state = {k: v for k, v in state.items()}
        new_state.pop("prompted_boxes", None)
        new_state.pop("masks", None)
        new_state.pop("boxes", None)
        new_state.pop("scores", None)
        return new_state

    def set_confidence_threshold(self, threshold: float, state: dict[str, Any]) -> dict[str, Any]:
        """
        Modifie le seuil de confiance.

        Args:
            threshold: float entre 0 et 1.
            state: état SAM3 courant.

        Returns:
            État mis à jour.
        """
        self._check_loaded()
        import torch

        with torch.autocast("cuda" if torch.cuda.is_available() else "cpu", dtype=torch.bfloat16):
            return self._processor.set_confidence_threshold(threshold, state)

    # ── Extraction ────────────────────────────────────────────────────────────

    def extract_result(self, state: dict[str, Any]) -> SegmentationResult:
        """
        Extrait les masques, boîtes et scores depuis l'état SAM3.

        Gère proprement les tenseurs vides retournés quand SAM3
        ne détecte pas l'objet dans l'image.

        Args:
            state: état SAM3 après un prompt.

        Returns:
            SegmentationResult avec données numpy (listes vides si rien détecté).
        """
        result = SegmentationResult(
            img_w=state.get("original_width", 0),
            img_h=state.get("original_height", 0),
        )
        masks_raw = state.get("masks", [])
        boxes_raw = state.get("boxes", [])
        scores_raw = state.get("scores", [])

        # Guard : tenseur vide → rien à extraire
        try:
            n = len(masks_raw)
        except TypeError:
            return result

        if n == 0:
            return result

        try:
            for mask_t, box_t, score_t in zip(masks_raw, boxes_raw, scores_raw, strict=False):
                mask_np = mask_t[0].cpu().numpy() > 0.5
                result.masks.append(mask_np)
                result.boxes_xyxy.append(box_t.cpu().numpy().tolist())
                score = float(score_t.item() if hasattr(score_t, "item") else score_t)
                result.scores.append(score)
        except Exception:
            pass

        return result

    # ── Interne ───────────────────────────────────────────────────────────────

    def _check_loaded(self) -> None:
        if not self._is_loaded:
            raise RuntimeError("Le modèle SAM3 n'est pas encore chargé. Appelez load_model() d'abord.")
