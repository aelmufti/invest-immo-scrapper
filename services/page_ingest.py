"""Ingestion d'une page d'annonce capturée côté navigateur (bookmarklet).

Stratégie d'extraction, par ordre de fiabilité :
1) JSON-LD (schema.org) — la plupart des portails immo en embarquent
   (Bien'ici, SeLoger, Leboncoin utilisent Product / RealEstateListing).
2) OpenGraph meta — fallback pour titre / URL / image / prix.
3) Parser texte (core.parser) sur `text` (innerText) — fallback ultime.

NB : ce module reçoit le payload depuis le bookmarklet ; il ne fait JAMAIS
de requête HTTP sortante vers le site source. L'extraction se fait
exclusivement sur le contenu que l'utilisateur a déjà chargé dans son
navigateur (donc en tant qu'humain authentifié à ses propres CGU).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from core.parser import parser_annonce
from data.database import session_scope
from data.repositories import upsert_bien
from services.ingest_service import _attach_ville

logger = logging.getLogger(__name__)


# Types JSON-LD qui nous intéressent (schema.org)
_LD_TYPES_IMMO = {
    "Product", "Offer", "RealEstateListing", "Apartment", "House",
    "Residence", "SingleFamilyResidence", "Accommodation",
}


def _walk_jsonld(obj: Any):
    """Itère récursivement sur un graphe JSON-LD (dict ou liste)."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk_jsonld(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_jsonld(item)


def _coerce_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = re.sub(r"[^\d,.\-]", "", val).replace(",", ".")
        try:
            return float(s) if s else None
        except ValueError:
            return None
    return None


def _coerce_int(val: Any) -> int | None:
    f = _coerce_float(val)
    return int(f) if f is not None else None


def _extract_from_jsonld(blocks: list[Any]) -> dict:
    """Cherche dans tous les blocs JSON-LD un objet pertinent et en tire les champs."""
    out: dict = {}
    for block in blocks:
        for node in _walk_jsonld(block):
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            if isinstance(types, str):
                types = [types]
            if not types or not any(t in _LD_TYPES_IMMO for t in types):
                continue

            # Titre
            out.setdefault("titre", node.get("name") or node.get("headline"))

            # Description
            desc = node.get("description")
            if desc and isinstance(desc, str):
                out.setdefault("description", desc[:5000])

            # Prix : node.price ou node.offers.price
            prix = _coerce_float(node.get("price"))
            if prix is None:
                offers = node.get("offers")
                if isinstance(offers, dict):
                    prix = _coerce_float(offers.get("price"))
                elif isinstance(offers, list):
                    for o in offers:
                        if isinstance(o, dict):
                            prix = _coerce_float(o.get("price"))
                            if prix:
                                break
            if prix and 1_000 <= prix <= 10_000_000:
                out.setdefault("prix", prix)

            # Surface
            surf = node.get("floorSize")
            if isinstance(surf, dict):
                surf_val = _coerce_float(surf.get("value"))
                if surf_val and 5 <= surf_val <= 5000:
                    out.setdefault("surface_m2", surf_val)
            elif surf is not None:
                v = _coerce_float(surf)
                if v and 5 <= v <= 5000:
                    out.setdefault("surface_m2", v)

            # Nombre de pièces
            rooms = node.get("numberOfRooms") or node.get("numberOfRoomsTotal")
            if isinstance(rooms, dict):
                rooms = rooms.get("value")
            r = _coerce_int(rooms)
            if r and 1 <= r <= 20:
                out.setdefault("nb_pieces", r)

            # Chambres
            beds = node.get("numberOfBedrooms")
            b = _coerce_int(beds)
            if b and 0 <= b <= 20:
                out.setdefault("nb_chambres", b)

            # Adresse
            addr = node.get("address")
            if isinstance(addr, dict):
                cp = addr.get("postalCode")
                if cp:
                    out.setdefault("code_postal", str(cp).strip())
                ville = addr.get("addressLocality")
                if ville:
                    out.setdefault("ville_nom", str(ville).strip().title())
                rue = addr.get("streetAddress")
                if rue:
                    out.setdefault("adresse", str(rue).strip())

            # Géo
            geo = node.get("geo")
            if isinstance(geo, dict):
                lat = _coerce_float(geo.get("latitude"))
                lng = _coerce_float(geo.get("longitude"))
                if lat and lng:
                    out.setdefault("latitude", lat)
                    out.setdefault("longitude", lng)

            # URL
            u = node.get("url")
            if u and isinstance(u, str):
                out.setdefault("url", u)

    return out


def _extract_from_og(og: dict[str, str]) -> dict:
    """Fallback OpenGraph (limité, mais utile pour titre / URL)."""
    out: dict = {}
    if og.get("og:title"):
        out["titre"] = og["og:title"]
    if og.get("og:description"):
        out["description"] = og["og:description"][:5000]
    if og.get("og:url"):
        out["url"] = og["og:url"]
    # OG price (rare mais existe sur quelques sites)
    p = _coerce_float(og.get("product:price:amount") or og.get("og:price:amount"))
    if p:
        out["prix"] = p
    return out


# ---------------------------------------------------------------------------
# Façade
# ---------------------------------------------------------------------------

def ingest_page_payload(payload: dict) -> dict:
    """Ingère une page capturée par le bookmarklet.

    Payload attendu (tous champs optionnels sauf au moins un parmi html/text/json_ld) :
        url:      str
        title:    str
        text:     str    (innerText)
        html:     str    (outerHTML, peut être tronqué)
        json_ld:  list   (liste de dicts JSON-LD)
        og:       dict   (mapping property -> content)

    Renvoie {bien_id, nouveau, source_url, champs_extraits}.
    """
    url = (payload.get("url") or "").strip()
    title = (payload.get("title") or "").strip()
    text = payload.get("text") or ""
    json_ld = payload.get("json_ld") or []
    og = payload.get("og") or {}

    # 1) JSON-LD (le plus fiable)
    fields = _extract_from_jsonld(json_ld) if json_ld else {}
    # 2) OpenGraph en complément (n'écrase pas)
    for k, v in _extract_from_og(og).items():
        fields.setdefault(k, v)
    # 3) Fallback texte sur ce qui manque
    if text:
        parsed = parser_annonce(text).to_dict()
        for k, v in parsed.items():
            if v is None:
                continue
            # Le parser texte est moins fiable -> ne complète que ce qui manque
            if k not in fields:
                fields[k] = v
    if title and "titre" not in fields:
        fields["titre"] = title[:255]
    if url:
        fields["url"] = url

    # Source : nom de domaine
    source = "page"
    if url:
        m = re.search(r"https?://([^/]+)", url)
        if m:
            source = m.group(1).lower().replace("www.", "")[:50]

    # Déduplique sur (source, url)
    source_id = url or None

    # Attache la ville
    fields = _attach_ville(fields)

    # `ges` est dans le parser mais le champ DB s'appelle bien `ges` :
    # `parser_annonce(...).to_dict()` n'inclut que les non-None.
    with session_scope() as s:
        bien, is_new = upsert_bien(s, source=source, source_id=source_id, **fields)
        bien_id = bien.id

    return {
        "bien_id": bien_id,
        "nouveau": is_new,
        "source": source,
        "source_url": url,
        "champs_extraits": {k: v for k, v in fields.items() if k != "description"},
    }
