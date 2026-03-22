"""Base de données SQLite pour les sessions et pages analysées.

Structure :
- sessions : nom, dates
- pages : texte brut + JSON d'analyse, liées à une session

Le JSON d'analyse est le format retour de Claude (après expand),
compatible avec from_api_response.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Répertoire par défaut
SESSIONS_DIR = Path(__file__).parent.parent / "sessions"
DB_PATH = SESSIONS_DIR / "analizador.db"


@dataclass
class PageRecord:
    """Une page analysée en base."""
    id: int
    session_id: int
    numero: int
    texte_brut: str
    analyse_json: str  # JSON compatible from_api_response
    cree_le: str

    @property
    def label(self) -> str:
        dt = self.cree_le[:16].replace("T", " ")
        apercu = self.texte_brut[:60].replace("\n", " ").strip()
        return f"Page {self.numero} — {dt} — {apercu}…"

    def charger_analyses(self) -> list[dict]:
        """Parse le JSON et retourne la liste de phrases (format API)."""
        try:
            data = json.loads(self.analyse_json)
            return data.get("phrases", [])
        except (json.JSONDecodeError, AttributeError):
            return []


@dataclass
class SessionRecord:
    """Une session en base."""
    id: int
    nom: str
    cree_le: str
    modifie_le: str
    nb_pages: int = 0

    @property
    def label(self) -> str:
        dt = self.modifie_le[:16].replace("T", " ")
        return f"{self.nom} ({self.nb_pages} pages) — {dt}"


class Database:
    """Gestionnaire SQLite pour les sessions et pages."""

    def __init__(self, db_path: Path | None = None):
        self._path = db_path or DB_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._creer_tables()
        print(f"[DB] Ouvert: {self._path}")

    def _creer_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                nom         TEXT NOT NULL,
                cree_le     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                modifie_le  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS pages (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id   INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                numero       INTEGER NOT NULL,
                texte_brut   TEXT NOT NULL,
                analyse_json TEXT NOT NULL DEFAULT '{}',
                cree_le      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_pages_session
                ON pages(session_id, numero);
        """)
        self._conn.commit()

    # ─── Sessions ────────────────────────────────────────────────

    def creer_session(self, nom: str) -> SessionRecord:
        cur = self._conn.execute(
            "INSERT INTO sessions (nom) VALUES (?)", (nom,)
        )
        self._conn.commit()
        return self.session_par_id(cur.lastrowid)

    def session_par_id(self, session_id: int) -> SessionRecord:
        row = self._conn.execute(
            "SELECT s.*, COUNT(p.id) as nb_pages "
            "FROM sessions s LEFT JOIN pages p ON p.session_id = s.id "
            "WHERE s.id = ?", (session_id,)
        ).fetchone()
        return SessionRecord(
            id=row["id"], nom=row["nom"],
            cree_le=row["cree_le"], modifie_le=row["modifie_le"],
            nb_pages=row["nb_pages"],
        )

    def lister_sessions(self) -> list[SessionRecord]:
        rows = self._conn.execute(
            "SELECT s.*, COUNT(p.id) as nb_pages "
            "FROM sessions s LEFT JOIN pages p ON p.session_id = s.id "
            "GROUP BY s.id ORDER BY s.modifie_le DESC"
        ).fetchall()
        return [
            SessionRecord(
                id=r["id"], nom=r["nom"],
                cree_le=r["cree_le"], modifie_le=r["modifie_le"],
                nb_pages=r["nb_pages"],
            )
            for r in rows
        ]

    def renommer_session(self, session_id: int, nouveau_nom: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET nom = ?, modifie_le = datetime('now', 'localtime') "
            "WHERE id = ?", (nouveau_nom, session_id)
        )
        self._conn.commit()

    def supprimer_session(self, session_id: int) -> None:
        self._conn.execute("DELETE FROM pages WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._conn.commit()

    # ─── Pages ───────────────────────────────────────────────────

    def sauvegarder_page(
        self, session_id: int, texte_brut: str, analyse_json: str
    ) -> PageRecord:
        """Sauvegarde une page dans la session. Numéro auto-incrémenté."""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(numero), 0) + 1 as next_num "
            "FROM pages WHERE session_id = ?", (session_id,)
        ).fetchone()
        numero = row["next_num"]

        cur = self._conn.execute(
            "INSERT INTO pages (session_id, numero, texte_brut, analyse_json) "
            "VALUES (?, ?, ?, ?)",
            (session_id, numero, texte_brut, analyse_json),
        )
        # Mettre à jour la date de modification de la session
        self._conn.execute(
            "UPDATE sessions SET modifie_le = datetime('now', 'localtime') "
            "WHERE id = ?", (session_id,)
        )
        self._conn.commit()
        print(f"[DB] Page {numero} sauvegardée (session {session_id})")
        return self.page_par_id(cur.lastrowid)

    def page_par_id(self, page_id: int) -> PageRecord:
        row = self._conn.execute(
            "SELECT * FROM pages WHERE id = ?", (page_id,)
        ).fetchone()
        return PageRecord(
            id=row["id"], session_id=row["session_id"],
            numero=row["numero"], texte_brut=row["texte_brut"],
            analyse_json=row["analyse_json"], cree_le=row["cree_le"],
        )

    def lister_pages(self, session_id: int) -> list[PageRecord]:
        rows = self._conn.execute(
            "SELECT * FROM pages WHERE session_id = ? ORDER BY numero",
            (session_id,),
        ).fetchall()
        return [
            PageRecord(
                id=r["id"], session_id=r["session_id"],
                numero=r["numero"], texte_brut=r["texte_brut"],
                analyse_json=r["analyse_json"], cree_le=r["cree_le"],
            )
            for r in rows
        ]

    def supprimer_page(self, page_id: int) -> None:
        self._conn.execute("DELETE FROM pages WHERE id = ?", (page_id,))
        self._conn.commit()

    # ─── Fermeture ───────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()


# Singleton
_instance: Database | None = None


def db() -> Database:
    global _instance
    if _instance is None:
        _instance = Database()
    return _instance
