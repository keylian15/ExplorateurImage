"""ViewModel SAM3 pour la segmentation d'image interactive.

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
from services.box_search_strategies import crop_pil
from services.i18n_manager import I18nManager
from services.ollama_wrapper import OllamaWrapper
from services.sam3_service import Sam3Service, SegmentationResult
from services.workers import (
    EmbeddingBoxSearchWorker,
    EmbeddingTextSearchWorker,
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
    """Données de segmentation prêtes pour l'affichage dans la View.

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
    """ViewModel SAM3 - pilote le chargement du modèle et la segmentation interactive.

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

    def __init__(self, client: OllamaWrapper, config: dict, gallery_vm: GalleryViewModel, ws_id: str, ws_data: dict, sam3_service: Sam3Service, translator: I18nManager) -> None:
        """Initialise le ViewModel de segmentation et de recherche d'objets.

        Configure les dépendances principales (client LLM, configuration, galerie,
        service SAM3), ainsi que les workers utilisés pour le chargement, l'encodage,
        la segmentation et la recherche.

        Connecte également les signaux du service SAM3.

        Args:
            client (OllamaWrapper): Client utilisé pour les modèles LLM.
            config (dict): Configuration globale de l'application.
            gallery_vm (GalleryViewModel): ViewModel de la galerie d'images.
            ws_id (str): Identifiant du workspace courant.
            ws_data (dict): Données associées au workspace.
            sam3_service (Sam3Service): Service responsable du modèle SAM3.
            translator (I18nManager): Gestionnaire de traduction.

        """
        super().__init__()

        self._client = client
        self._config = config
        self._gallery_vm = gallery_vm
        self._ws_id = ws_id
        self._params = ws_repo.get_map_params(ws_data)
        self.translator = translator

        self._service = sam3_service
        self._service.signal_loaded.connect(self.on_model_loaded)
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
        """Indique si le modèle SAM3 est chargé et prêt à être utilisé.

        Returns:
            bool: True si le modèle est chargé, False sinon.

        """
        return self._service.is_loaded

    @property
    def is_image_encoded(self) -> bool:
        """Indique si une image a été encodée et est prête pour les prompts.

        Returns:
            bool: True si un état d'image est disponible, False sinon.

        """
        return self._state is not None

    @property
    def is_busy(self) -> bool:
        """Indique si un worker lié à la segmentation est en cours d'exécution.

        Returns:
            bool: True si au moins un worker (load, encode, segment ou reset)
            est actif, False sinon.

        """
        return any(w is not None and w.isRunning() for w in (self._load_worker, self._encode_worker, self._segment_worker, self._reset_worker))

    @property
    def is_searching(self) -> bool:
        """Indique si une recherche est actuellement en cours.

        Returns:
            bool: True si un worker de recherche existe et est en cours d'exécution, False sinon.

        """
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
        self._load_worker = Sam3LoadWorker(self._service)
        self._load_worker.signal_error.connect(self.signal_model_error)
        self._load_worker.start()

    def on_model_loaded(self) -> None:
        """Déclenche le signal indiquant que le modèle est chargé et prêt à être utilisé."""
        self.signal_model_ready.emit()

    # ── Encodage image ────────────────────────────────────────────────────────

    def encode_image(self, pixmap: QPixmap, img_path: str | None = None) -> None:
        """Encode une image pour l'utiliser dans le modèle SAM3 (préparation du contexte).

        L'image est stockée comme base de segmentation (arrière-plan) afin de permettre
        les opérations de prompt et de détection.

        Args:
            pixmap (QPixmap): Image à encoder pour la segmentation.
            img_path (str | None): Chemin disque optionnel de l'image.
                S'il est fourni, il est préféré à une conversion en mémoire.

        """
        if not self._service.is_loaded or self.is_busy:
            return
        self._state = None
        self.signal_encoding.emit()

        pil = self.to_pil(pixmap, img_path)
        if pil is None:
            self.signal_encoding_error.emit(self.translator.tr("Impossible de convertir l'image."))
            return

        self._encode_worker = Sam3EncodeWorker(self._service, pil)
        self._encode_worker.signal_finished.connect(self.on_encoded)
        self._encode_worker.signal_error.connect(self.signal_encoding_error)
        self._encode_worker.start()

    def on_encoded(self, state: dict) -> None:
        """Emet un signal lorsque l'image est encodé.

        Args:
            state (dict): Le nouvel etat de l'image.

        """
        self._state = state
        self.signal_encoded.emit()

    # ── Prompts ───────────────────────────────────────────────────────────────

    def apply_text_prompt(self, prompt: str) -> None:
        """Applique un prompt texte.

        Args:
            prompt (str): Le prompt a appliquer.

        """
        if not self.can_segment():
            return
        svc = self._service

        def fn(state: dict) -> dict:
            """Applique un prompt textuel au service.

            Args:
                state (dict): État courant du traitement.

            Returns:
                dict: État mis à jour après application du prompt.

            """
            return svc.apply_text_prompt(prompt, state)

        self.run_segment(fn)

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
        """Applique un prompt de type bounding box sur une image.

        La boîte est définie en coordonnées pixel (format xyxy) et utilisée comme
        prompt pour guider le modèle (positif ou négatif selon le paramètre).

        Args:
            x0 (float): Coordonnée X de départ de la box.
            y0 (float): Coordonnée Y de départ de la box.
            x1 (float): Coordonnée X de fin de la box.
            y1 (float): Coordonnée Y de fin de la box.
            img_w (int): Largeur de l'image (validation des limites).
            img_h (int): Hauteur de l'image (validation des limites).
            positive (bool): Si True, la box est un prompt positif, sinon négatif.

        """
        if not self.can_segment():
            return
        svc = self._service

        def fn(state: dict) -> dict:
            """Applique un prompt basé sur une sélection de boîte sur l'image.

            Args:
                state (dict): État courant du traitement.

            Returns:
                dict: État mis à jour après application du prompt.

            """
            return svc.apply_box_prompt(x0, y0, x1, y1, img_w, img_h, state, positive)

        self.run_segment(fn)

    def reset_prompts(self) -> None:
        """Supprime tous les prompts."""
        if self._state is None or self.is_busy:
            return
        self.signal_resetting.emit()
        self._reset_worker = Sam3ResetWorker(self._service, self._state)
        self._reset_worker.signal_finished.connect(self.on_reset_done)
        self._reset_worker.signal_error.connect(self.signal_segment_error)
        self._reset_worker.start()

    def on_reset_done(self, new_state: dict) -> None:
        """Emet un signal lorsque le reset du model est fait.

        Args:
            new_state (dict): Le nouvel etat de l'image.

        """
        self._state = new_state
        self.signal_reset_done.emit()

    def set_confidence(self, value: float) -> None:
        """Set le seuil de confiance et relance la segmentation.

        Args:
            value (float): La nouvelle valeur de confiance.

        """
        self._confidence = value
        if self._state is not None and not self.is_busy:
            svc = self._service

            def fn(state: dict) -> dict[str, any]:
                """Définit le seuil de confiance utilisé par le service.

                Args:
                    state (dict): Nouvel état à appliquer au seuil de confiance.

                Returns:
                    dict[str, Any]: Le retour de set confidence_treshold.

                """
                return svc.set_confidence_threshold(value, state)

            self.run_segment(fn)

    # ── Recherche globale (texte direct) ──────────────────────────────────────

    def search_objects(self, text: str, threshold: float = 0.75, strategy_name: str = "sam3") -> None:
        """Lance une recherche d'objet sur toutes les images du dossier.

        La recherche est basée sur le texte fourni et utilise la stratégie sélectionnée.
        La méthode est bloquée si le modèle n'est pas chargé ou si une recherche est déjà en cours.
        Chaque correspondance est envoyée progressivement via le signal `signal_search_match`.

        Args:
            text (str): Description de l'objet à rechercher (ex: "shoe", "dog").
            threshold (float): Score minimum pour valider une correspondance (0-1).
            strategy_name (str): Stratégie utilisée pour la recherche (ex: "sam3").

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
            )
        elif strategy_name == "embedding":
            # Recherche texte via embedding : on crée un crop fictif (None)
            # et on passe directement par EmbeddingBoxSearchWorker avec le texte comme description
            index = self._gallery_vm.index
            if not index:
                self.signal_search_error.emit(self.translator.tr("Aucune image indexée dans ce dossier."))
                return
            self.signal_search_started.emit(len(index))

            worker = EmbeddingTextSearchWorker(
                text=text,
                folder=folder,
                images=images,
                index=index,
                client=self._client,
                threshold=threshold,
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
            )
        else:
            self.signal_search_error.emit(self.translator.tr("Stratégie inconnue : {name}.").format(name=strategy_name))
            return

        self._search_worker = worker
        self._search_worker.signal_progress.connect(self.signal_search_progress)
        self._search_worker.signal_match.connect(self.signal_search_match)
        self._search_worker.signal_finished.connect(self.on_search_finished)
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
        """Lance une recherche d'objet à partir d'une région sélectionnée (bounding box) sur une image.

        La zone définie par les coordonnées est recadrée depuis l'image source, puis une recherche est effectuée selon la stratégie choisie.
        La méthode utilise les mêmes signaux que `search_objects`.

        Args:
            x0 (float): Coordonnée X de départ de la box (image originale).
            y0 (float): Coordonnée Y de départ de la box (image originale).
            x1 (float): Coordonnée X de fin de la box (image originale).
            y1 (float): Coordonnée Y de fin de la box (image originale).
            img_w (int): Largeur de l'image originale (validation des limites).
            img_h (int): Hauteur de l'image originale (validation des limites).
            pixmap (QPixmap): Image source utilisée pour extraire la région.
            strategy_name (str): Stratégie de recherche à utiliser : "embedding", "sam3" ou "hybrid".
            threshold (float): Seuil principal (cosine similarity pour embedding, score SAM3 pour sam3).
            sam3_threshold (float): Seuil spécifique à SAM3 (utilisé uniquement pour les stratégies sam3 et hybrid).
            max_results (int): Nombre maximum de résultats à retourner. 0 = illimité.

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
        pil_source = self.to_pil(pixmap, None)
        if pil_source is None:
            self.signal_search_error.emit(self.translator.tr("Impossible de convertir l'image courante."))
            return

        crop = crop_pil(pil_source, x0, y0, x1, y1)
        crop_size = 4
        if crop.width < crop_size or crop.height < crop_size:
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
            )
        else:
            self.signal_search_error.emit(self.translator.tr("Stratégie inconnue : {name}.").format(name=strategy_name))
            return

        self._search_worker = worker
        worker.signal_progress.connect(self.signal_search_progress)
        worker.signal_match.connect(self.signal_search_match)
        worker.signal_finished.connect(self.on_search_finished)
        worker.signal_error.connect(self.signal_search_error)
        worker.start()

    def cancel_search(self) -> None:
        """Annule la recherche globale ou par box en cours."""
        if self._search_worker and self._search_worker.isRunning():
            self._search_worker.cancel()
            self.signal_search_cancelled.emit()

    def on_search_finished(self, matched: list) -> None:
        """Emet un signal lorsque la recherche est fini avec la liste des images trouvé.

        Args:
            matched (list): Liste de noms des images.

        """
        self.signal_search_finished.emit(matched)

    # ── Interne segmentation ──────────────────────────────────────────────────

    def can_segment(self) -> bool:
        """Retourne si la segmentation est possible.

        Returns:
            bool: La possibilité de segmenter.

        """
        return self._service.is_loaded and self._state is not None and not self.is_busy

    def run_segment(self, prompt_fn) -> None:
        """Lance la segmentation.

        Args:
            prompt_fn (function): La fonction de prompt.

        """
        self.signal_segmenting.emit()
        self._segment_worker = Sam3SegmentWorker(self._service, self._state, prompt_fn)
        self._segment_worker.signal_finished.connect(self.on_segment_done)
        self._segment_worker.signal_error.connect(self.on_segment_error)
        self._segment_worker.start()

    def on_segment_done(self, new_state: dict, result: SegmentationResult) -> None:
        """Met a jour l'overlay et emet le signal overlay ready.

        Args:
            new_state (dict): Le nouvel etat de l'image.
            result (SegmentationResult): Le résultat de la ségmentation.

        """
        self._state = new_state
        overlay = self.to_overlay(result)
        self.signal_overlay_ready.emit(overlay)

    def on_segment_error(self, msg: str) -> None:
        """Emet le signal d'erreur.

        Args:
            msg (str): Le message d'erreur.

        """
        self.signal_segment_error.emit(self.translator.tr(msg))

    def to_overlay(self, result: SegmentationResult) -> MaskOverlay:
        """Convertit SegmentationResult (type Service) en MaskOverlay (type View).

        Args:
            result (SegmentationResult): Les résultats de la ségmentation.

        Returns:
            MaskOverlay.

        """
        return MaskOverlay(
            masks=result.masks,
            boxes_xyxy=result.boxes_xyxy,
            scores=result.scores,
            img_w=result.img_w,
            img_h=result.img_h,
        )

    @staticmethod
    def to_pil(pixmap: QPixmap, img_path: str | None) -> PILImage.Image | None:
        """Convertit un QPixmap en PIL.Image RGB.

        Utilise le chemin disque si disponible (qualité maximale),
        sinon convertit via QImage en mémoire.

        Args:
            pixmap (QPixmap): L'image.
            img_path (str | None): Chemin de l'image.

        Returns:
            PILImage.Image | None: L'image PIL.

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
