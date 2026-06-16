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
 - Recherche globale sur tout le dossier (ObjectSearchAllWorker)
 - Recherche par box avec trois stratégies : Embedding, SAM3, Hybride
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
 8. Lancer une recherche globale (search_objects) sur tout le dossier via un worker dédié
 9. Lancer une recherche par box (search_from_box) avec la stratégie choisie par l'utilisateur
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image as PILImage
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from models import workspace_repository as ws_repo
from services.i18n_manager import I18nManager
from services.ollama_wrapper import OllamaWrapper
from services.sam3_service import SegmentationResult
from services.workers import (
    EmbeddingBoxSearchWorker,
    HybridBoxSearchWorker,
    ObjectSearchAllWorker,
    Sam3BoxSearchWorker,
    Sam3EncodeWorker,
    Sam3LoadWorker,
    Sam3ResetWorker,
    Sam3SegmentWorker,
)
from viewmodels.gallery_vm import GalleryViewModel

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

    Pour la recherche globale (texte) :
        6. search_objects(text, threshold) lance ObjectSearchAllWorker.

    Pour la recherche par box :
        7. search_from_box(x0, y0, x1, y1, img_w, img_h, pixmap, strategy_name, ...)
           lance le worker correspondant à la stratégie choisie.
        8. Les mêmes signaux search_* sont utilisés pour les deux types de recherche.
    """

    # ── Signaux segmentation courante ─────────────────────────────────────────
    signal_model_loading = pyqtSignal()
    signal_model_ready = pyqtSignal()
    signal_model_error = pyqtSignal(str)

    signal_encoding = pyqtSignal()  # encodage image démarré
    signal_encoded = pyqtSignal()  # image prête pour les prompts
    signal_encoding_error = pyqtSignal(str)

    signal_segmenting = pyqtSignal()  # prompt en cours
    signal_overlay_ready = pyqtSignal(object)  # MaskOverlay
    signal_segment_error = pyqtSignal(str)

    signal_resetting = pyqtSignal()
    signal_reset_done = pyqtSignal()

    # ── Signaux recherche (partagés entre search_objects et search_from_box) ──
    signal_search_started = pyqtSignal(int)  # total d'images
    signal_search_progress = pyqtSignal(int, int, str)  # (done, total, img_name)
    signal_search_match = pyqtSignal(str, float)  # (img_name, score)
    signal_search_finished = pyqtSignal(list)  # list[str] des matches
    signal_search_error = pyqtSignal(str)
    signal_search_cancelled = pyqtSignal()

    # ── Signal spécifique box search (informe la View de la stratégie active) ─
    signal_box_search_strategy = pyqtSignal(str)  # nom de la stratégie en cours

    def __init__(self, client: OllamaWrapper, config: dict, gallery_vm: GalleryViewModel, ws_id: str, ws_data: dict, sam3_service, parent=None, translator: I18nManager = None):
        super().__init__(parent)

        self._client = client
        self._config = config
        self._gallery_vm = gallery_vm
        self._ws_id = ws_id
        self._params = ws_repo.get_map_params(ws_data)
        self.translator = translator

        self._service = sam3_service
        self._service.signal_loaded.connect(self._on_model_loaded)
        self._state: dict | None = None
        self._confidence: float = 0.5

        self._load_worker: Sam3LoadWorker | None = None
        self._encode_worker: Sam3EncodeWorker | None = None
        self._segment_worker: Sam3SegmentWorker | None = None
        self._reset_worker: Sam3ResetWorker | None = None
        self._search_worker: ObjectSearchAllWorker | EmbeddingBoxSearchWorker | Sam3BoxSearchWorker | HybridBoxSearchWorker | None = None

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
        """True si un worker de segmentation est en cours d'exécution."""
        return any(w is not None and w.isRunning() for w in (self._load_worker, self._encode_worker, self._segment_worker, self._reset_worker))

    @property
    def is_searching(self) -> bool:
        """True si une recherche globale est en cours."""
        return self._search_worker is not None and self._search_worker.isRunning()

    # ── Chargement modèle ─────────────────────────────────────────────────────

    def load_model(self) -> None:
        """Lance le chargement du modèle en arrière-plan (si pas déjà fait/en cours)."""
        if self._service.is_loaded:
            self.signal_model_ready.emit()
            return

        if self._service.is_loading or self.is_busy:
            self.signal_model_loading.emit()
            return

        self.signal_model_loading.emit()
        self._load_worker = Sam3LoadWorker(self._service, self)
        self._load_worker.signal_error.connect(self.signal_model_error)
        self._load_worker.start()

    def _on_model_loaded(self) -> None:
        self.signal_model_ready.emit()

    # ── Encodage image ────────────────────────────────────────────────────────

    def encode_image(self, pixmap: QPixmap, img_path: str | None = None) -> None:
        """
        Encode l'image dans l'état SAM3 (arrière-plan).

        Args:
            pixmap: QPixmap de l'image à segmenter.
            img_path: chemin disque optionnel - préféré à la conversion en mémoire.
        """
        if not self._service.is_loaded or self.is_busy:
            return
        self._state = None
        self.signal_encoding.emit()

        pil = self._to_pil(pixmap, img_path)
        if pil is None:
            self.signal_encoding_error.emit(self.translator.tr("Impossible de convertir l'image."))
            return

        self._encode_worker = Sam3EncodeWorker(self._service, pil, self)
        self._encode_worker.signal_finished.connect(self._on_encoded)
        self._encode_worker.signal_error.connect(self.signal_encoding_error)
        self._encode_worker.start()

    def _on_encoded(self, state: dict) -> None:
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
        """Applique un prompt boîte en coordonnées pixel xyxy."""
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

    def _on_reset_done(self, new_state: dict) -> None:
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

    # ── Recherche globale (texte direct) ──────────────────────────────────────

    def search_objects(self, text: str, threshold: float = 0.75, strategy_name: str = "sam3") -> None:
        """
        Lance la recherche de l'objet `text` sur toutes les images du dossier.

        Bloque si le modèle n'est pas chargé ou si une recherche est déjà en cours.
        Chaque correspondance est émise via signal_search_match au fil de l'eau.

        Args:
            text: texte décrivant l'objet (ex: "shoe", "dog").
            threshold: score minimum SAM3 pour qu'une image soit retenue (0–1).
        """
        if not self._service.is_loaded:
            self.signal_search_error.emit(self.translator.tr("Le modèle SAM3 n'est pas encore chargé."))
            return

        if self.is_searching:
            return

        folder = self._gallery_vm.current_folder
        if not folder:
            self.signal_search_error.emit(self.translator.tr("Aucun dossier ouvert."))
            return

        images = self._gallery_vm.all_images()
        if not images:
            self.signal_search_error.emit(self.translator.tr("Aucune image dans le dossier."))
            return

        strategy_name = strategy_name.lower()
        self.signal_box_search_strategy.emit(strategy_name)

        if strategy_name == "sam3":
            if not self._service.is_loaded:
                self.signal_search_error.emit(self.translator.tr("Le modèle SAM3 n'est pas encore chargé."))
                return
            self.signal_search_started.emit(len(images))
            worker = ObjectSearchAllWorker(
                folder=folder,
                images=images,
                service=self._service,
                text=text,
                threshold=threshold,
                parent=self,
            )
        elif strategy_name == "embedding":
            # Recherche texte via embedding : on crée un crop fictif (None)
            # et on passe directement par EmbeddingBoxSearchWorker avec le texte comme description
            index = self._gallery_vm.index
            if not index:
                self.signal_search_error.emit(self.translator.tr("Aucune image indexée dans ce dossier."))
                return
            self.signal_search_started.emit(len(index))
            from services.workers import EmbeddingTextSearchWorker

            worker = EmbeddingTextSearchWorker(
                text=text,
                folder=folder,
                images=images,
                index=index,
                client=self._client,
                threshold=threshold,
                parent=self,
            )
        elif strategy_name == "hybrid":
            if not self._service.is_loaded:
                self.signal_search_error.emit(self.translator.tr("Le modèle SAM3 n'est pas encore chargé."))
                return
            self.signal_search_started.emit(len(images))
            worker = ObjectSearchAllWorker(
                folder=folder,
                images=images,
                service=self._service,
                text=text,
                threshold=threshold,
                parent=self,
            )
        else:
            self.signal_search_error.emit(self.translator.tr("Stratégie inconnue : {name}.").format(name=strategy_name))
            return

        self._search_worker = worker
        self._search_worker.signal_progress.connect(self.signal_search_progress)
        self._search_worker.signal_match.connect(self.signal_search_match)
        self._search_worker.signal_finished.connect(self._on_search_finished)
        self._search_worker.signal_error.connect(self.signal_search_error)
        self._search_worker.start()

    # ── Recherche par box ─────────────────────────────────────────────────────

    def search_from_box(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        img_w: int,
        img_h: int,
        pixmap: QPixmap,
        strategy_name: str = "embedding",
        threshold: float = 0.3,
        sam3_threshold: float = 0.75,
        max_results: int = 0,
    ) -> None:
        """
        Lance une recherche d'objet à partir d'une région dessinée sur l'image.

        Recadre la région de la box, choisit la stratégie demandée et lance
        le worker correspondant. Utilise les mêmes signaux que search_objects.

        Args:
            x0, y0, x1, y1: Coordonnées pixel de la box sur l'image originale.
            img_w, img_h: Dimensions de l'image originale (pour validation).
            pixmap: QPixmap de l'image courante (source du crop).
            strategy_name: "embedding", "sam3" ou "hybrid".
            threshold: Seuil principal (cosinus pour embedding, SAM3 score pour sam3).
            sam3_threshold: Seuil SAM3 utilisé uniquement par les stratégies sam3/hybrid.
            max_results: Nombre maximum de résultats (0 = illimité).
        """
        if self.is_searching:
            self.signal_search_error.emit(self.translator.tr("Une recherche est déjà en cours."))
            return

        folder = self._gallery_vm.current_folder
        if not folder:
            self.signal_search_error.emit(self.translator.tr("Aucun dossier ouvert."))
            return

        images = self._gallery_vm.all_images()
        if not images:
            self.signal_search_error.emit(self.translator.tr("Aucune image dans le dossier."))
            return

        index = self._gallery_vm.index
        if not index:
            self.signal_search_error.emit(self.translator.tr("Aucune image indexée dans ce dossier."))
            return

        # Crop PIL de la région de la box
        pil_source = self._to_pil(pixmap, None)
        if pil_source is None:
            self.signal_search_error.emit(self.translator.tr("Impossible de convertir l'image courante."))
            return

        from services.box_search_strategies import crop_pil

        crop = crop_pil(pil_source, x0, y0, x1, y1)
        if crop.width < 4 or crop.height < 4:
            self.signal_search_error.emit(self.translator.tr("La région sélectionnée est trop petite."))
            return

        strategy_name = strategy_name.lower()

        # Validation : SAM3 doit être chargé pour les stratégies qui l'utilisent
        if strategy_name in ("sam3", "hybrid") and not self._service.is_loaded:
            self.signal_search_error.emit(self.translator.tr("Le modèle SAM3 n'est pas encore chargé."))
            return

        self.signal_box_search_strategy.emit(strategy_name)
        self.signal_search_started.emit(len(images) if strategy_name != "embedding" else len(index))

        if strategy_name == "embedding":
            worker = EmbeddingBoxSearchWorker(
                crop=crop,
                folder=folder,
                images=images,
                index=index,
                client=self._client,
                threshold=threshold,
                max_results=max_results,
                parent=self,
            )
        elif strategy_name == "sam3":
            worker = Sam3BoxSearchWorker(
                crop=crop,
                folder=folder,
                images=images,
                index=index,
                client=self._client,
                service=self._service,
                threshold=sam3_threshold,
                max_results=max_results,
                parent=self,
            )
        elif strategy_name == "hybrid":
            worker = HybridBoxSearchWorker(
                crop=crop,
                folder=folder,
                images=images,
                index=index,
                client=self._client,
                service=self._service,
                embed_threshold=threshold,
                sam3_threshold=sam3_threshold,
                max_results=max_results,
                parent=self,
            )
        else:
            self.signal_search_error.emit(self.translator.tr("Stratégie inconnue : {name}.").format(name=strategy_name))
            return

        self._search_worker = worker
        worker.signal_progress.connect(self.signal_search_progress)
        worker.signal_match.connect(self.signal_search_match)
        worker.signal_finished.connect(self._on_search_finished)
        worker.signal_error.connect(self.signal_search_error)
        worker.start()

    def cancel_search(self) -> None:
        """Annule la recherche globale ou par box en cours."""
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.cancel()
            self.signal_search_cancelled.emit()

    def _on_search_finished(self, matched: list) -> None:
        self.signal_search_finished.emit(matched)

    # ── Interne segmentation ──────────────────────────────────────────────────

    def _can_segment(self) -> bool:
        return self._service.is_loaded and self._state is not None and not self.is_busy

    def _run_segment(self, prompt_fn) -> None:
        self.signal_segmenting.emit()
        self._segment_worker = Sam3SegmentWorker(self._service, self._state, prompt_fn, self)
        self._segment_worker.signal_finished.connect(self._on_segment_done)
        self._segment_worker.signal_error.connect(self._on_segment_error)
        self._segment_worker.start()

    def _on_segment_done(self, new_state: dict, result: SegmentationResult) -> None:
        self._state = new_state
        overlay = self._to_overlay(result)
        self.signal_overlay_ready.emit(overlay)

    def _on_segment_error(self, msg: str) -> None:
        self.signal_segment_error.emit(self.translator.tr(msg))

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
                pass

        try:
            qimg = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
            ptr = qimg.bits()
            ptr.setsize(qimg.width() * qimg.height() * 3)
            arr = np.frombuffer(ptr, dtype=np.uint8).reshape((qimg.height(), qimg.width(), 3))
            return PILImage.fromarray(arr.copy())
        except Exception:
            return None
