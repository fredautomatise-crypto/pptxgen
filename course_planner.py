"""
Construit la STRUCTURE COMPLÈTE du cours (liste de modules, chacun avec un
titre et les sections du PDF qu'il doit couvrir) à partir du seul sommaire
du PDF — pas besoin d'envoyer tout le texte au LLM pour cette étape, donc
c'est quasi gratuit même sur une documentation de plusieurs centaines de pages.

Usage :
    python course_planner.py doc.pdf "Cours complet" --product "Nom du logiciel"
"""
import json
from pathlib import Path
from typing import Optional, Dict, Any, List

from openai import OpenAI

import config
import pdf_extractor
from retry_utils import openai_retry
from content_planner import cost_tracker

COURSE_MAP_JSON_SCHEMA: Dict[str, Any] = {
    "name": "course_map",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "course_title": {"type": "string"},
            "modules": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "number": {"type": "integer"},
                        "title": {"type": "string"},
                        "topic_keywords": {"type": "array", "items": {"type": "string"}},
                        "source_headings": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["number", "title", "topic_keywords", "source_headings"],
                },
            },
        },
        "required": ["course_title", "modules"],
    },
}

SYSTEM_PROMPT_TEMPLATE = """Tu es un concepteur pédagogique senior qui structure une formation \
professionnelle complète sur "{product_name}", dans le style de la marque \
"{brand_name}". Rôle : découper le sommaire d'une documentation officielle \
en une progression pédagogique de modules cohérents (ex: "Module 1 : \
Fondamentaux", "Module 2 : Interface & Prise en main", "Module 3 : \
Fonctionnalités avancées"...).

RÈGLES :
- Progression logique du plus simple au plus avancé (bases -> interface -> \
logique -> intégrations -> cas d'usage avancés).
- Chaque module doit couvrir un thème cohérent et autonome, ni trop large \
(évite les modules fourre-tout) ni trop étroit (évite les modules d'une \
seule fonctionnalité mineure). Vise des modules qui prendraient chacun \
20-40 minutes de cours.
- "source_headings" doit contenir les titres EXACTS (copiés tels quels) du \
sommaire fourni qui appartiennent à ce module — ne pas inventer ou \
reformuler les titres.
- "topic_keywords" : 3-6 mots-clés (en minuscules) pour retrouver le \
contenu de ce module si jamais aucun heading exact ne matche.
- Ne crée pas plus de modules que nécessaire : regroupe les sections \
mineures/connexes dans le module thématique le plus proche plutôt que de \
multiplier les modules.
"""

USER_PROMPT_TEMPLATE = """Voici le sommaire complet extrait du PDF (liste de titres, avec leur \
niveau hiérarchique et leur page) :

---
{outline_text}
---

Propose la structure complète du cours "{course_title}" : découpe ce \
sommaire en modules pédagogiques cohérents, en couvrant l'intégralité des \
sujets listés (ne rien laisser de côté qui apporte de la valeur \
pédagogique — les titres purement administratifs comme "Sommaire" ou \
"Mentions légales" peuvent être ignorés)."""


def _format_outline(headings: List[dict]) -> str:
    lines = []
    for h in headings:
        indent = "  " * max(h["level"] - 1, 0)
        lines.append(f"{indent}- (p.{h['page']}) {h['title']}")
    return "\n".join(lines)


@openai_retry
def build_course_map(
    pdf_path: str,
    course_title: str,
    model: Optional[str] = None,
    product_name: str = "l'outil documenté",
) -> Dict[str, Any]:
    config.require_openai_api_key()
    cost_tracker.check_budget()
    headings = pdf_extractor.get_headings(pdf_path)
    if not headings:
        raise RuntimeError(
            "Aucun titre détectable dans ce PDF (ni bookmarks, ni tailles de police "
            "distinctes). La planification automatique du cours nécessite un minimum "
            "de structure — envisage de découper le PDF manuellement avec --topic."
        )

    outline_text = _format_outline(headings)
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    model = model or config.OPENAI_MODEL
    brand_name = getattr(config, "BRAND_NAME", "PptxGen")
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(product_name=product_name, brand_name=brand_name)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(
                outline_text=outline_text[:40000], course_title=course_title)},
        ],
        response_format={"type": "json_schema", "json_schema": COURSE_MAP_JSON_SCHEMA},
        temperature=0.4,
    )

    if getattr(response, "usage", None):
        cost = cost_tracker.add(model, response.usage)
        print(f"  (coût planification structure : ≈ ${cost:.3f})")

    course_map = json.loads(response.choices[0].message.content)
    course_map["product_name"] = product_name
    for m in course_map["modules"]:
        m["total"] = len(course_map["modules"])
    return course_map


def save_course_map(course_map: Dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(course_map, f, ensure_ascii=False, indent=2)


def load_course_map(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Planifie la structure complète d'un cours à partir d'un PDF")
    parser.add_argument("pdf_path", help="Chemin vers le PDF de documentation")
    parser.add_argument("course_title", nargs="?", default=None,
                         help="Titre du cours (optionnel si --profile fournit course_title)")
    parser.add_argument("--product", default="", help="Nom du logiciel/produit documenté (ex: 'Make.com'). "
                                                        "Par défaut, déduit du titre du cours ou du profil.")
    parser.add_argument("--theme", default=None, help="Thème visuel (voir themes/*.json)")
    parser.add_argument("--profile", default="", help="Profil préconfiguré (voir profiles/*.json), "
                                                        "ex: --profile make_com")
    args = parser.parse_args()

    profile = config.load_profile(args.profile) if args.profile else {}
    theme = args.theme or profile.get("theme")
    if theme:
        config.load_theme(theme)

    course_title = args.course_title or profile.get("course_title")
    if not course_title:
        parser.error("Fournir un titre de cours, ou --profile avec un course_title défini")
    product_name = args.product or profile.get("product_name") or course_title
    example_apps = profile.get("example_apps", [])

    course_map = build_course_map(args.pdf_path, course_title, product_name=product_name)
    course_map["example_apps"] = example_apps
    out_path = config.CACHE_DIR / "course_map.json"
    save_course_map(course_map, str(out_path))
    print(f"\n{len(course_map['modules'])} modules planifiés → {out_path}\n")
    for m in course_map["modules"]:
        print(f"  {m['number']:2d}. {m['title']}  ({len(m['source_headings'])} sections)")
    print(f"\n{cost_tracker.summary()}")
