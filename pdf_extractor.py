"""
Extraction du texte et de la structure (titres/sections) depuis un PDF de
documentation officielle Make.com, pour servir de matière première au
planificateur de contenu (content_planner.py).

Deux bibliothèques complémentaires :
- pdfplumber : extraction de texte fiable, fonctionne bien sur PDF "propres"
- PyMuPDF (fitz) : accès à la taille de police -> permet de détecter les
  titres/sous-titres même sans structure PDF explicite (outline/bookmarks)
"""
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import logging
import statistics

import fitz  # PyMuPDF
import pdfplumber

# pdfminer (utilisé sous le capot par pdfplumber) émet des avertissements
# bénins sur des polices mal formées ("Could not get FontBBox...") très
# fréquents sur des PDF exportés depuis Word/CMS. Ça n'affecte pas
# l'extraction de texte : on les masque pour garder la console lisible.
logging.getLogger("pdfminer").setLevel(logging.ERROR)


@dataclass
class DocSection:
    heading: str
    level: int          # 1 = titre principal, 2 = sous-titre, 0 = pas de titre détecté
    text: str
    page_start: int


def _extract_outline(pdf_path: str) -> List[dict]:
    """Utilise la table des matières (bookmarks) du PDF si elle existe."""
    doc = fitz.open(pdf_path)
    toc = doc.get_toc(simple=True)  # [[level, title, page], ...]
    doc.close()
    return [{"level": lvl, "title": title, "page": page} for lvl, title, page in toc]


def _font_size_headings(pdf_path: str) -> List[dict]:
    """
    Fallback si le PDF n'a pas de bookmarks : détecte les titres par taille de
    police relative (les lignes dont la police est nettement plus grande que
    la taille médiane du document sont considérées comme des titres).
    """
    doc = fitz.open(pdf_path)
    sizes = []
    lines_info = []

    for page_num, page in enumerate(doc):
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = "".join(s["text"] for s in spans).strip()
                if not text:
                    continue
                size = max(s["size"] for s in spans)
                sizes.append(size)
                lines_info.append({"page": page_num, "text": text, "size": size})

    doc.close()
    if not sizes:
        return []

    median_size = statistics.median(sizes)
    headings = []
    for li in lines_info:
        if li["size"] >= median_size * 1.25 and len(li["text"]) < 120:
            level = 1 if li["size"] >= median_size * 1.5 else 2
            headings.append({"level": level, "title": li["text"], "page": li["page"]})
    return headings


def extract_sections(pdf_path: str, max_pages: Optional[int] = None) -> List[DocSection]:
    """
    Découpe le PDF en sections (titre + texte) en s'appuyant en priorité sur
    les bookmarks PDF, sinon sur la détection par taille de police.
    """
    pdf_path = str(pdf_path)
    outline = _extract_outline(pdf_path)
    headings = (
        [{"level": h["level"], "title": h["title"], "page": h["page"]} for h in outline]
        if outline
        else _font_size_headings(pdf_path)
    )
    # trie par page pour pouvoir découper le texte entre deux titres consécutifs
    headings = sorted(headings, key=lambda h: h["page"])

    full_text_by_page = {}
    with pdfplumber.open(pdf_path) as pdf:
        n_pages = len(pdf.pages) if max_pages is None else min(max_pages, len(pdf.pages))
        for i in range(n_pages):
            full_text_by_page[i] = pdf.pages[i].extract_text() or ""

    if not headings:
        # Pas de titres détectables : on retourne tout le texte comme une seule section.
        all_text = "\n".join(full_text_by_page.values())
        return [DocSection(heading="(document complet)", level=0, text=all_text, page_start=0)]

    sections: List[DocSection] = []
    for idx, h in enumerate(headings):
        start_page = h["page"]
        end_page = headings[idx + 1]["page"] if idx + 1 < len(headings) else max(full_text_by_page.keys(), default=start_page)
        pages_text = [full_text_by_page.get(p, "") for p in range(start_page, end_page + 1) if p in full_text_by_page]
        sections.append(DocSection(
            heading=h["title"],
            level=h["level"],
            text="\n".join(pages_text).strip(),
            page_start=start_page,
        ))

    return [s for s in sections if s.text]


def match_sections_by_topic(sections: List[DocSection], topic_keywords: List[str]) -> List[DocSection]:
    """
    Filtre une liste de sections DÉJÀ EXTRAITES (voir extract_sections) sur des
    mots-clés de titre, avec repli sur le corps du texte si rien ne matche le
    titre. Séparé de extract_topic() pour permettre d'extraire le PDF une
    seule fois puis de filtrer plusieurs fois (voir batch_generate.py).
    """
    keywords_lower = [k.lower() for k in topic_keywords]
    matched = [s for s in sections if any(k in s.heading.lower() for k in keywords_lower)]
    if not matched:
        matched = [s for s in sections if any(k in s.text.lower() for k in keywords_lower)]
    return matched


def extract_topic(pdf_path: str, topic_keywords: List[str], max_pages: Optional[int] = None) -> str:
    """
    Extrait uniquement les sections dont le titre contient un des mots-clés
    donnés (ex: ["router", "iterator", "aggregator"]). Utile pour ne
    récupérer, dans une doc complète, que la matière d'un module précis.
    Retourne le texte concaténé (titres + contenu).

    ⚠️ Cette fonction re-parse tout le PDF à chaque appel. Si tu dois
    extraire plusieurs sujets du MÊME PDF (cas de batch_generate.py), appelle
    extract_sections() une seule fois puis match_sections_by_topic() pour
    chaque sujet — c'est ce que fait batch_generate.py.
    """
    sections = extract_sections(pdf_path, max_pages=max_pages)
    matched = match_sections_by_topic(sections, topic_keywords)
    parts = [f"## {s.heading}\n{s.text}" for s in matched]
    return "\n\n".join(parts)


def get_headings(pdf_path: str) -> List[dict]:
    """
    Retourne uniquement la structure (titres + niveau + page) du PDF, sans le
    texte complet. Beaucoup plus léger que extract_sections() — utilisé pour
    planifier l'ensemble d'un cours (course_planner.py) sans envoyer tout le
    PDF au LLM.
    """
    outline = _extract_outline(str(pdf_path))
    headings = (
        [{"level": h["level"], "title": h["title"], "page": h["page"]} for h in outline]
        if outline
        else _font_size_headings(str(pdf_path))
    )
    return sorted(headings, key=lambda h: h["page"])


def _pdf_cache_key(pdf_path: str) -> str:
    """Clé de cache basée sur le chemin absolu + taille + date de modif du
    PDF — se réinvalide automatiquement si le fichier change."""
    import hashlib
    p = Path(pdf_path)
    stat = p.stat()
    raw = f"{p.resolve()}:{stat.st_size}:{stat.st_mtime}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def extract_sections_cached(pdf_path: str, cache_dir, max_pages: Optional[int] = None) -> List[DocSection]:
    """
    Identique à extract_sections(), mais met en cache le résultat sur disque
    (cache_dir/sections_<hash>.json). Un PDF de plusieurs centaines de pages
    peut prendre plusieurs minutes à parser avec pdfplumber — sans ce cache,
    relancer batch_generate.py après une interruption (Ctrl+C, coupure
    réseau, machine éteinte) le refait entièrement à chaque fois, même si le
    PDF lui-même n'a pas changé.
    """
    import json
    from dataclasses import asdict

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"sections_{_pdf_cache_key(pdf_path)}.json"

    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return [DocSection(**d) for d in data]

    sections = extract_sections(pdf_path, max_pages=max_pages)
    cache_file.write_text(
        json.dumps([asdict(s) for s in sections], ensure_ascii=False), encoding="utf-8",
    )
    return sections


if __name__ == "__main__":
    import sys, json
    if len(sys.argv) < 2:
        print("Usage: python pdf_extractor.py chemin_vers_doc.pdf [mot_cle1,mot_cle2]")
        sys.exit(1)
    path = sys.argv[1]
    if len(sys.argv) > 2:
        kws = sys.argv[2].split(",")
        print(extract_topic(path, kws))
    else:
        secs = extract_sections(path)
        print(json.dumps(
            [{"heading": s.heading, "level": s.level, "page": s.page_start, "chars": len(s.text)} for s in secs],
            ensure_ascii=False, indent=2,
        ))
