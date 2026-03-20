"""Modèles de données pour l'analyse grammaticale."""

from dataclasses import dataclass, field


@dataclass
class MotAnalyse:
    """Un mot analysé grammaticalement."""
    mot: str
    categorie: str
    lemme: str
    genre: str = "n/a"
    nombre: str = "n/a"
    conjugaison: str | None = None
    prononciation: str = ""
    definition: str = ""
    groupe: str = ""  # sujeto, verbo, complemento, relativa, etc.


@dataclass
class Expression:
    """Expression idiomatique (sens ≠ mots individuels)."""
    indices: list[int]
    texte: str
    sens: str


@dataclass
class PhraseAnalysee:
    """Une phrase complète avec ses mots analysés et expressions."""
    texte_original: str
    traduction: str
    mots: list[MotAnalyse] = field(default_factory=list)
    expressions: list[Expression] = field(default_factory=list)

    def indices_expressions(self) -> set[int]:
        """Retourne l'ensemble des indices de mots faisant partie d'une expression."""
        result: set[int] = set()
        for expr in self.expressions:
            result.update(expr.indices)
        return result

    def expression_pour_indice(self, indice_mot: int) -> Expression | None:
        """Retourne l'expression contenant ce mot, ou None."""
        for expr in self.expressions:
            if indice_mot in expr.indices:
                return expr
        return None


def from_api_response(data: dict) -> list[PhraseAnalysee]:
    """Parse la réponse JSON de Claude en liste de PhraseAnalysee."""
    phrases = []
    for p in data.get("phrases", []):
        mots = [
            MotAnalyse(
                mot=m["mot"],
                categorie=m.get("categorie", ""),
                lemme=m.get("lemme", ""),
                genre=m.get("genre", "n/a"),
                nombre=m.get("nombre", "n/a"),
                conjugaison=m.get("conjugaison"),
                prononciation=m.get("prononciation", ""),
                definition=m.get("definition", ""),
                groupe=m.get("groupe", ""),
            )
            for m in p.get("mots", [])
        ]
        expressions = [
            Expression(
                indices=e["indices"],
                texte=e.get("texte", ""),
                sens=e.get("sens", ""),
            )
            for e in p.get("expressions", [])
        ]
        phrases.append(PhraseAnalysee(
            texte_original=p.get("texte_original", ""),
            traduction=p.get("traduction", ""),
            mots=mots,
            expressions=expressions,
        ))
    return phrases