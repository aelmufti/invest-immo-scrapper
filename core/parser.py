"""Parseur d'annonces collées en texte libre.

Extrait par regex/heuristiques : prix, surface, nb de pièces, DPE, charges,
taxe foncière, ville, code postal. Tolérant aux fautes de frappe.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class AnnonceParsee:
    titre: Optional[str] = None
    description: Optional[str] = None
    type_bien: Optional[str] = None
    prix: Optional[float] = None
    surface_m2: Optional[float] = None
    nb_pieces: Optional[int] = None
    nb_chambres: Optional[int] = None
    etage: Optional[int] = None
    annee_construction: Optional[int] = None
    dpe: Optional[str] = None
    ges: Optional[str] = None
    charges_copro_annuelles: Optional[float] = None
    taxe_fonciere_annuelle: Optional[float] = None
    loyer_mensuel_estime: Optional[float] = None
    code_postal: Optional[str] = None
    ville_nom: Optional[str] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(num: str) -> Optional[float]:
    """Convertit '1 234,56' ou '1234.56' en float."""
    s = num.replace("\u202f", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _first(regex: str, text: str, flags: int = re.IGNORECASE) -> Optional[str]:
    m = re.search(regex, text, flags)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Extracteurs
# ---------------------------------------------------------------------------

_PRIX_PATTERNS = [
    r"prix\s*(?:de\s*vente)?\s*[:\-]?\s*([0-9][0-9 \u202f\xa0]{2,9})\s*(?:€|euros?|EUR)",
    r"([0-9][0-9 \u202f\xa0]{2,9})\s*(?:€|euros?|EUR)\s*(?:net|FAI|hors\s*frais)?",
    r"vendu\s*[:\-]?\s*([0-9][0-9 \u202f\xa0]{2,9})\s*€",
]


def extraire_prix(text: str) -> Optional[float]:
    for p in _PRIX_PATTERNS:
        s = _first(p, text)
        if s:
            v = _to_float(s)
            if v and 1_000 <= v <= 10_000_000:
                return v
    return None


def extraire_surface(text: str) -> Optional[float]:
    s = _first(r"([0-9]+(?:[.,][0-9]+)?)\s*m(?:²|2)\b", text)
    if not s:
        s = _first(r"surface(?:\s+habitable)?\s*[:\-]?\s*([0-9]+(?:[.,][0-9]+)?)", text)
    v = _to_float(s) if s else None
    if v and 5 <= v <= 1000:
        return v
    return None


def extraire_pieces(text: str) -> Optional[int]:
    s = _first(r"(?:T|F|Type\s*)?([1-9])\s*(?:pi[eè]ces?|\bP\b)", text)
    if not s:
        s = _first(r"\bT([1-9])\b", text)
    if not s:
        s = _first(r"([1-9])\s*pi[eè]ces?", text)
    try:
        return int(s) if s else None
    except ValueError:
        return None


def extraire_chambres(text: str) -> Optional[int]:
    s = _first(r"([1-9])\s*chambres?", text)
    try:
        return int(s) if s else None
    except ValueError:
        return None


def extraire_etage(text: str) -> Optional[int]:
    s = _first(r"([0-9]+)(?:e|er|ème|eme)\s*[ée]tage", text)
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def extraire_annee(text: str) -> Optional[int]:
    s = _first(r"construit(?:\s+en)?\s*[:\-]?\s*(1[89][0-9]{2}|20[0-2][0-9])", text)
    if not s:
        s = _first(r"ann[ée]e\s+(?:de\s+)?construction\s*[:\-]?\s*(1[89][0-9]{2}|20[0-2][0-9])", text)
    try:
        return int(s) if s else None
    except ValueError:
        return None


_DPE_RE = re.compile(
    r"\bDPE\s*[:\-]?\s*([A-G])\b|\b(?:classe|étiquette)\s+énerg[ée]tique\s*[:\-]?\s*([A-G])\b",
    re.IGNORECASE,
)


def extraire_dpe(text: str) -> Optional[str]:
    m = _DPE_RE.search(text)
    if not m:
        return None
    val = m.group(1) or m.group(2)
    return val.upper() if val else None


def extraire_ges(text: str) -> Optional[str]:
    m = re.search(r"\bGES\s*[:\-]?\s*([A-G])\b", text, re.IGNORECASE)
    return m.group(1).upper() if m else None


def extraire_taxe_fonciere(text: str) -> Optional[float]:
    s = _first(
        r"taxe\s+fonci[eè]re\s*[:\-]?\s*([0-9][0-9 \u202f\xa0]{1,6})\s*€?",
        text,
    )
    return _to_float(s) if s else None


def extraire_charges_copro(text: str) -> Optional[float]:
    # "charges 1200 €/an" ou "150 €/mois de charges"
    s = _first(
        r"charges?\s*(?:de\s*copropri[ée]t[ée])?\s*[:\-]?\s*([0-9][0-9 \u202f\xa0]{1,6})\s*€\s*/?\s*an",
        text,
    )
    if s:
        return _to_float(s)
    s = _first(
        r"charges?\s*(?:mensuelles?)?\s*[:\-]?\s*([0-9][0-9 \u202f\xa0]{1,6})\s*€\s*/?\s*mois",
        text,
    )
    v = _to_float(s) if s else None
    return v * 12 if v else None


def extraire_loyer(text: str) -> Optional[float]:
    s = _first(
        r"loyer\s*(?:mensuel|estim[ée])?\s*[:\-]?\s*([0-9][0-9 \u202f\xa0]{1,6})\s*€\s*/?\s*mois",
        text,
    )
    if not s:
        s = _first(r"lou[ée]\s*([0-9][0-9 \u202f\xa0]{1,6})\s*€\s*/?\s*mois", text)
    return _to_float(s) if s else None


_CP_VILLE_RE = re.compile(
    r"\b(\d{5})\s+([A-ZÉÈÊÀÂÔÛÎÇa-zéèêàâôûîç' \-]{2,50})",
)


def extraire_code_postal_ville(text: str) -> tuple[Optional[str], Optional[str]]:
    m = _CP_VILLE_RE.search(text)
    if m:
        return m.group(1), m.group(2).strip().title()
    cp = _first(r"\b(\d{5})\b", text)
    return cp, None


def extraire_type_bien(text: str) -> Optional[str]:
    t = text.lower()
    if re.search(r"\bappartement\b|\bappart\b|\bstudio\b", t):
        return "appartement"
    if re.search(r"\bmaison\b|\bvilla\b|\bpavillon\b", t):
        return "maison"
    if re.search(r"\bimmeuble\b", t):
        return "immeuble"
    return None


# ---------------------------------------------------------------------------
# Façade
# ---------------------------------------------------------------------------

def parser_annonce(texte: str) -> AnnonceParsee:
    """Parse une annonce libre et renvoie tous les champs extractibles.

    Conçu pour être tolérant : un champ manquant -> None, jamais d'exception.
    """
    if not texte or not texte.strip():
        return AnnonceParsee()

    cp, ville = extraire_code_postal_ville(texte)

    return AnnonceParsee(
        description=texte.strip()[:5000],
        type_bien=extraire_type_bien(texte),
        prix=extraire_prix(texte),
        surface_m2=extraire_surface(texte),
        nb_pieces=extraire_pieces(texte),
        nb_chambres=extraire_chambres(texte),
        etage=extraire_etage(texte),
        annee_construction=extraire_annee(texte),
        dpe=extraire_dpe(texte),
        ges=extraire_ges(texte),
        charges_copro_annuelles=extraire_charges_copro(texte),
        taxe_fonciere_annuelle=extraire_taxe_fonciere(texte),
        loyer_mensuel_estime=extraire_loyer(texte),
        code_postal=cp,
        ville_nom=ville,
    )
