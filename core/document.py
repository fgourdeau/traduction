"""Gestion des documents Analizador (.anlz).

Un document .anlz est une archive ZIP contenant :
    manifest.json   — métadonnées du document et liste des pages
    pages/
        001.json    — analyse grammaticale de la page 1
        001.png     — image optionnelle (mode bulle/BD)
        002.json
        ...

Le manifest.json a cette structure :
{
    "version": 1,
    "nom": "Mon document",
    "cree_le": "2025-06-15T10:30:00",
    "modifie_le": "2025-06-15T11:00:00",
    "pages": [
        {
            "numero": 1,
            "texte_brut": "El gato...",
            "has_image": true,
            "cree_le": "2025-06-15T10:30:00"
        }
    ]
}
"""

import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

MANIFEST_VERSION = 1
EXTENSION = ".anlz"


@dataclass
class PageDocument:
    """Une page dans un document."""
    numero: int
    texte_brut: str
    analyse_json: str          # JSON brut (format compatible from_api_response)
    image_data: bytes | None   # PNG compressé ou None
    cree_le: str = ""

    @property
    def has_image(self) -> bool:
        return self.image_data is not None and len(self.image_data) > 0


@dataclass
class Document:
    """Un document Analizador complet."""
    nom: str
    pages: list[PageDocument] = field(default_factory=list)
    cree_le: str = ""
    modifie_le: str = ""

    def __post_init__(self):
        now = datetime.now().isoformat(timespec="seconds")
        if not self.cree_le:
            self.cree_le = now
        if not self.modifie_le:
            self.modifie_le = now

    @property
    def nb_pages(self) -> int:
        return len(self.pages)

    def ajouter_page(self, page: PageDocument) -> None:
        """Ajoute une page et met à jour la date de modification."""
        self.pages.append(page)
        self.modifie_le = datetime.now().isoformat(timespec="seconds")

    def supprimer_page(self, index: int) -> None:
        """Supprime une page par index et renumérote."""
        if 0 <= index < len(self.pages):
            del self.pages[index]
            self._renumeroter()
            self.modifie_le = datetime.now().isoformat(timespec="seconds")

    def deplacer_page(self, ancien_index: int, nouvel_index: int) -> None:
        """Déplace une page et renumérote."""
        if (0 <= ancien_index < len(self.pages)
                and 0 <= nouvel_index < len(self.pages)):
            page = self.pages.pop(ancien_index)
            self.pages.insert(nouvel_index, page)
            self._renumeroter()
            self.modifie_le = datetime.now().isoformat(timespec="seconds")

    def _renumeroter(self) -> None:
        for i, page in enumerate(self.pages, start=1):
            page.numero = i


def sauvegarder_document(doc: Document, chemin: Path | str) -> Path:
    """Écrit le document dans une archive .anlz (ZIP).
    
    Retourne le chemin final du fichier créé.
    """
    chemin = Path(chemin)
    if chemin.suffix.lower() != EXTENSION:
        chemin = chemin.with_suffix(EXTENSION)

    with zipfile.ZipFile(chemin, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Écrire chaque page
        for page in doc.pages:
            num = f"{page.numero:03d}"

            # JSON d'analyse
            zf.writestr(f"pages/{num}.json", page.analyse_json)

            # Image optionnelle
            if page.has_image:
                zf.writestr(f"pages/{num}.png", page.image_data)

        # Manifest (écrit après les pages pour avoir les infos à jour)
        manifest = {
            "version": MANIFEST_VERSION,
            "nom": doc.nom,
            "cree_le": doc.cree_le,
            "modifie_le": doc.modifie_le,
            "pages": [
                {
                    "numero": p.numero,
                    "texte_brut": p.texte_brut,
                    "has_image": p.has_image,
                    "cree_le": p.cree_le,
                }
                for p in doc.pages
            ],
        }
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False),
        )

    taille = chemin.stat().st_size
    print(f"[Document] Sauvegardé: {chemin.name} "
          f"({doc.nb_pages} pages, {taille // 1024} Ko)")
    return chemin


def charger_document(chemin: Path | str) -> Document:
    """Lit un document depuis une archive .anlz.
    
    Raises:
        FileNotFoundError: si le fichier n'existe pas.
        ValueError: si le format est invalide.
    """
    chemin = Path(chemin)
    if not chemin.exists():
        raise FileNotFoundError(f"Document introuvable: {chemin}")

    with zipfile.ZipFile(chemin, 'r') as zf:
        # Lire le manifest
        try:
            manifest_raw = zf.read("manifest.json")
        except KeyError:
            raise ValueError("Archive invalide: manifest.json manquant")

        try:
            manifest = json.loads(manifest_raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"Manifest corrompu: {e}")

        version = manifest.get("version", 0)
        if version > MANIFEST_VERSION:
            raise ValueError(
                f"Version de document trop récente ({version} > {MANIFEST_VERSION})"
            )

        # Reconstruire les pages
        pages: list[PageDocument] = []
        for page_info in manifest.get("pages", []):
            numero = page_info["numero"]
            num = f"{numero:03d}"

            # Charger le JSON d'analyse
            try:
                analyse_json = zf.read(f"pages/{num}.json").decode("utf-8")
            except KeyError:
                analyse_json = "{}"

            # Charger l'image si elle existe
            image_data = None
            if page_info.get("has_image", False):
                try:
                    image_data = zf.read(f"pages/{num}.png")
                except KeyError:
                    pass

            pages.append(PageDocument(
                numero=numero,
                texte_brut=page_info.get("texte_brut", ""),
                analyse_json=analyse_json,
                image_data=image_data,
                cree_le=page_info.get("cree_le", ""),
            ))

    doc = Document(
        nom=manifest.get("nom", chemin.stem),
        pages=pages,
        cree_le=manifest.get("cree_le", ""),
        modifie_le=manifest.get("modifie_le", ""),
    )
    print(f"[Document] Chargé: {chemin.name} ({doc.nb_pages} pages)")
    return doc


def session_vers_document(session_id: int, nom: str | None = None) -> Document:
    """Convertit une session DB en Document (pour export).
    
    Charge toutes les pages avec leurs images.
    """
    from core.db import db

    database = db()
    session = database.session_par_id(session_id)
    pages_db = database.lister_pages(session_id)

    doc = Document(
        nom=nom or session.nom,
        cree_le=session.cree_le,
        modifie_le=session.modifie_le,
    )

    for p in pages_db:
        # Charger l'image complète (lazy loading dans lister_pages)
        image_data = database.charger_image_page(p.id)

        doc.ajouter_page(PageDocument(
            numero=p.numero,
            texte_brut=p.texte_brut,
            analyse_json=p.analyse_json,
            image_data=image_data,
            cree_le=p.cree_le,
        ))

    return doc


def document_vers_session(doc: Document, nom_session: str | None = None) -> int:
    """Importe un Document dans la DB comme nouvelle session.
    
    Retourne l'ID de la session créée.
    """
    from core.db import db

    database = db()
    session = database.creer_session(nom_session or doc.nom)

    for page in doc.pages:
        database.sauvegarder_page(
            session_id=session.id,
            texte_brut=page.texte_brut,
            analyse_json=page.analyse_json,
            image_data=page.image_data,
        )

    print(f"[Document] Importé en session #{session.id}: "
          f"{doc.nb_pages} pages")
    return session.id