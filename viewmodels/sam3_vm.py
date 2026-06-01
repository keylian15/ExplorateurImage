"""
ViewModel SAM3 pour la segmentation d'image interactive.

Ce composant orchestre le chargement du modèle SAM3, l'initialisation de l'état
à partir d'une image, et l'application des prompts (texte ou boîte) via des
workers Qt en arrière-plan, afin de ne jamais bloquer l'interface.

Toute la logique de transformation de données (conversion QPixmap→PIL, conversion
coordonnées boîte) est concentrée ici : la View ne manipule que des QPixmap et des
signaux Qt.

Contenu :
 - Chargement asynchrone du modèle (Sam3LoadWorker depuis services/workers)
 - Encodage asynchrone d'une image PIL ou QPixmap (Sam3EncodeWorker)
 - Application asynchrone de prompts texte/boîte (Sam3SegmentWorker)
 - Reset des prompts (Sam3ResetWorker)
 - Exposition des résultats via signaux Qt (liste de MaskOverlay, type View-friendly)

Responsabilités :
 1. Charger le modèle SAM3 en arrière-plan sans bloquer l'UI
 2. Convertir un QPixmap en PIL.Image (logique de données, pas de la View)
 3. Encoder l'image dans l'état SAM3
 4. Appliquer les prompts texte ou boîte via des workers
 5. Transformer SegmentationResult en MaskOverlay (type que la View peut consommer
    sans importer services/)
 6. Notifier la vue de chaque résultat intermédiaire via signaux
 7. Permettre le reset propre de tous les prompts
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image as PILImage

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from services.sam3_service import Sam3Service, SegmentationResult
from services.workers import (
    Sam3EncodeWorker,
    Sam3LoadWorker,
    Sam3ResetWorker,
    Sam3SegmentWorker,
)


# ── Type View-friendly (pas de dépendance vers services/) ────────────────────


@dataclass
class MaskOverlay:
    """
    Données de segmentation prêtes pour l'affichage dans la View.

    La View n'a pas besoin d'importer services/ pour utiliser ce type.
    Toutes les valeurs sont en coordonnées pixel de l'image originale.
    """

    masks: list[np.ndarray] = field(default_factory=list)  # (H, W) bool
    boxes_xyxy: list[list[float]] = field(default_factory=list)  # [[x0,y0,x1,y1],...]
    scores: list[float] = field(default_factory=list)
    img_w: int = 0
    img_h: int = 0


# ── ViewModel ────────────────────────────────────────────────────────────────


class Sam3ViewModel(QObject):
    """
    ViewModel SAM3 - pilote le chargement du modèle et la segmentation interactive.

    Cycle de vie :
        1. Instancier dans WorkspaceWidget (partagé entre GalleryWidget et DetailWidget).
        2. load_model() est appelé en fond au démarrage du workspace.
        3. encode_image(pixmap, img_path) quand l'utilisateur ouvre une image.
        4. apply_text_prompt() ou apply_box_prompt() pour segmenter.
        5. signal_overlay_ready → la View affiche les masques.
    """

    # ── Signaux ───────────────────────────────────────────────────────────────
    signal_model_loading = pyqtSignal()  # chargement démarré
    signal_model_ready = pyqtSignal()  # modèle disponible
    signal_model_error = pyqtSignal(str)  # erreur de chargement

    signal_encoding = pyqtSignal()  # encodage image démarré
    signal_encoded = pyqtSignal()  # image prête pour les prompts
    signal_encoding_error = pyqtSignal(str)

    signal_segmenting = pyqtSignal()  # prompt en cours
    signal_overlay_ready = pyqtSignal(object)  # MaskOverlay
    signal_segment_error = pyqtSignal(str)

    signal_resetting = pyqtSignal()
    signal_reset_done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._service = Sam3Service()
        self._state: dict | None = None
        self._confidence: float = 0.5

        self._load_worker: Sam3LoadWorker | None = None
        self._encode_worker: Sam3EncodeWorker | None = None
        self._segment_worker: Sam3SegmentWorker | None = None
        self._reset_worker: Sam3ResetWorker | None = None

    # ── Propriétés ────────────────────────────────────────────────────────────

    @property
    def is_model_loaded(self) -> bool:
        """Indique si le modèle SAM3 est chargé."""
        return self._service.is_loaded

    @property
    def is_image_encoded(self) -> bool:
        """Indique si une image est encodée et prête pour les prompts."""
        return self._state is not None

    @property
    def is_busy(self) -> bool:
        """True si un worker est en cours d'exécution."""
        return any(w is not None and w.isRunning() for w in (self._load_worker, self._encode_worker, self._segment_worker, self._reset_worker))

    # ── Chargement modèle ─────────────────────────────────────────────────────

    def load_model(self) -> None:
        """Lance le chargement du modèle en arrière-plan."""
        if self._service.is_loaded or self.is_busy:
            return
        self.signal_model_loading.emit()
        self._load_worker = Sam3LoadWorker(self._service, self)
        self._load_worker.signal_finished.connect(self._on_model_loaded)
        self._load_worker.signal_error.connect(self.signal_model_error)
        self._load_worker.start()

    def _on_model_loaded(self):
        self.signal_model_ready.emit()

    # ── Encodage image ────────────────────────────────────────────────────────

    def encode_image(self, pixmap: QPixmap, img_path: str | None = None) -> None:
        """
        Encode l'image dans l'état SAM3 (arrière-plan).

        La conversion QPixmap → PIL.Image est faite ici (logique de données,
        pas dans la View).

        Args:
            pixmap: QPixmap de l'image à segmenter.
            img_path: chemin disque optionnel - préféré à la conversion en mémoire
                      car plus fidèle (pas de recompression JPEG intermédiaire).
        """
        if not self._service.is_loaded or self.is_busy:
            return
        self._state = None
        self.signal_encoding.emit()

        pil = self._to_pil(pixmap, img_path)
        if pil is None:
            self.signal_encoding_error.emit("Impossible de convertir l'image.")
            return

        self._encode_worker = Sam3EncodeWorker(self._service, pil, self)
        self._encode_worker.signal_finished.connect(self._on_encoded)
        self._encode_worker.signal_error.connect(self.signal_encoding_error)
        self._encode_worker.start()

    def _on_encoded(self, state: dict):
        self._state = state
        self.signal_encoded.emit()

    # ── Prompts ───────────────────────────────────────────────────────────────

    def apply_text_prompt(self, prompt: str) -> None:
        """Applique un prompt texte."""
        if not self._can_segment():
            return
        svc = self._service

        def fn(state):
            return svc.apply_text_prompt(prompt, state)

        self._run_segment(fn)

    def apply_box_prompt(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        img_w: int,
        img_h: int,
        positive: bool = True,
    ) -> None:
        """
        Applique un prompt boîte en coordonnées pixel xyxy.

        Args:
            x0, y0, x1, y1: coordonnées pixel dans l'image originale.
            img_w, img_h: dimensions de l'image originale.
            positive: True = inclure, False = exclure.
        """
        if not self._can_segment():
            return
        svc = self._service

        def fn(state):
            return svc.apply_box_prompt(x0, y0, x1, y1, img_w, img_h, state, positive)

        self._run_segment(fn)

    def reset_prompts(self) -> None:
        """Supprime tous les prompts."""
        if self._state is None or self.is_busy:
            return
        self.signal_resetting.emit()
        self._reset_worker = Sam3ResetWorker(self._service, self._state, self)
        self._reset_worker.signal_finished.connect(self._on_reset_done)
        self._reset_worker.signal_error.connect(self.signal_segment_error)
        self._reset_worker.start()

    def _on_reset_done(self, new_state: dict):
        self._state = new_state
        self.signal_reset_done.emit()

    def set_confidence(self, value: float) -> None:
        """Modifie le seuil de confiance et relance la segmentation."""
        self._confidence = value
        if self._state is not None and not self.is_busy:
            svc = self._service

            def fn(state):
                return svc.set_confidence_threshold(value, state)

            self._run_segment(fn)

    # ── Interne ───────────────────────────────────────────────────────────────

    def _can_segment(self) -> bool:
        return self._service.is_loaded and self._state is not None and not self.is_busy

    def _run_segment(self, prompt_fn) -> None:
        self.signal_segmenting.emit()
        self._segment_worker = Sam3SegmentWorker(self._service, self._state, prompt_fn, self)
        self._segment_worker.signal_finished.connect(self._on_segment_done)
        self._segment_worker.signal_error.connect(self._on_segment_error)
        self._segment_worker.start()

    def _on_segment_done(self, new_state: dict, result: SegmentationResult):
        self._state = new_state
        overlay = self._to_overlay(result)
        self.signal_overlay_ready.emit(overlay)

    def _on_segment_error(self, msg: str):
        self.signal_segment_error.emit(msg)

    def _to_overlay(self, result: SegmentationResult) -> MaskOverlay:
        """Convertit SegmentationResult (type Service) en MaskOverlay (type View)."""
        return MaskOverlay(
            masks=result.masks,
            boxes_xyxy=result.boxes_xyxy,
            scores=result.scores,
            img_w=result.img_w,
            img_h=result.img_h,
        )

    @staticmethod
    def _to_pil(pixmap: QPixmap, img_path: str | None) -> PILImage.Image | None:
        """
        Convertit un QPixmap en PIL.Image RGB.

        Utilise le chemin disque si disponible (qualité maximale),
        sinon convertit via QImage en mémoire.
        """
        if img_path:
            try:
                return PILImage.open(img_path).convert("RGB")
            except Exception:
                pass  # fallback sur la conversion mémoire

        try:
            qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
            ptr = qimg.bits()
            ptr.setsize(qimg.width() * qimg.height() * 3)
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((qimg.height(), qimg.width(), 3))
            return PILImage.fromarray(arr.copy())
        except Exception:
            return None
