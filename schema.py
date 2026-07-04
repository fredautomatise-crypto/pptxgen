"""
Schéma JSON du "plan de module" produit par content_planner.py, éventuellement
affiné par plan_chat.py, et consommé par pptx_generator.py.

Un module = une liste de slides. Chaque slide a un `type` qui détermine son
layout visuel, plus un champ `speaker_notes` = texte détaillé (généré par le
LLM, aligné sur le contenu affiché) injecté comme note de présentateur dans
le PPTX — jamais affiché à l'écran, visible uniquement en mode Présentateur
ou à l'impression des notes. Ancien nom : `narration` (héritage de la
version avec synthèse vocale, retirée du MVP — voir CHANGELOG/README).

Types de slide supportés (calqués sur les exemples fournis) :

- "title"        : slide de titre du module (fond sombre)
- "objectives"    : prérequis + durée + liste d'objectifs à puces icônes
- "stats"         : 3 (ou 4) chiffres clés en callout avec icône
- "section"       : slide de transition "SECTION N" (fond sombre)
- "icon_list"     : liste verticale icône + titre + description
- "icon_grid"     : grille 2x2 ou 2x3 de cartes icône + titre + description
- "two_column"    : deux blocs côte à côte (comparaison avant/après, gauche/droite)
- "table"         : tableau simple (ex. raccourcis clavier)
- "process_flow"  : diagramme horizontal en étapes reliées par des flèches
- "conclusion"    : slide de synthèse / prochaines étapes (fond sombre)

Le moteur est volontairement limité à ces 10 types : ils couvrent la grande
majorité des patterns observés dans vos supports. Pour un nouveau layout,
ajouter un cas dans pptx_generator.py (fonction `render_slide`) plutôt que
de complexifier ce schéma.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

# Schéma JSON (JSON Schema) transmis à l'API OpenAI en "structured outputs"
# pour forcer la forme exacte de la réponse.
COURSE_PLAN_JSON_SCHEMA: Dict[str, Any] = {
    "name": "course_plan",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "module_title": {"type": "string"},
            "module_number": {"type": "integer"},
            "module_total": {"type": "integer"},
            "subtitle": {"type": "string"},
            "slides": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "title", "objectives", "stats", "section",
                                "icon_list", "icon_grid", "two_column",
                                "table", "process_flow", "conclusion",
                            ],
                        },
                        "title": {"type": "string"},
                        "subtitle": {"type": "string"},
                        "speaker_notes": {
                            "type": "string",
                            "description": "Notes de présentateur en français (60-140 mots), qui "
                                           "expliquent en détail ce que montre la slide, comme un "
                                           "support pour la personne qui présente. Jamais affiché à "
                                           "l'écran pendant la présentation.",
                        },
                        "items": {
                            "type": "array",
                            "description": "Contenu principal de la slide (icônes, stats, lignes, étapes...).",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "icon": {"type": "string"},
                                    "label": {"type": "string"},
                                    "value": {"type": "string"},
                                    "text": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                                "required": ["icon", "label", "value", "text", "description"],
                            },
                        },
                        "column_left_title": {"type": "string"},
                        "column_right_title": {"type": "string"},
                        "column_left_items": {"type": "array", "items": {"type": "string"}},
                        "column_right_items": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [
                        "type", "title", "subtitle", "speaker_notes", "items",
                        "column_left_title", "column_right_title",
                        "column_left_items", "column_right_items",
                    ],
                },
            },
        },
        "required": ["module_title", "module_number", "module_total", "subtitle", "slides"],
    },
}


# Schéma JSON d'UNE SEULE slide, extrait de COURSE_PLAN_JSON_SCHEMA pour être
# réutilisé tel quel par les outils de chat d'édition ciblée (plan_chat.py :
# update_slide / add_slide n'ont besoin de valider qu'une slide à la fois,
# pas le plan entier).
SLIDE_JSON_SCHEMA: Dict[str, Any] = COURSE_PLAN_JSON_SCHEMA["schema"]["properties"]["slides"]["items"]


@dataclass
class SlideItem:
    icon: str = ""
    label: str = ""
    value: str = ""
    text: str = ""
    description: str = ""


@dataclass
class Slide:
    type: str
    title: str = ""
    subtitle: str = ""
    speaker_notes: str = ""
    items: List[SlideItem] = field(default_factory=list)
    column_left_title: str = ""
    column_right_title: str = ""
    column_left_items: List[str] = field(default_factory=list)
    column_right_items: List[str] = field(default_factory=list)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Slide":
        items = [SlideItem(**it) for it in d.get("items", [])]
        return Slide(
            type=d["type"],
            title=d.get("title", ""),
            subtitle=d.get("subtitle", ""),
            speaker_notes=d.get("speaker_notes", d.get("narration", "")),
            items=items,
            column_left_title=d.get("column_left_title", ""),
            column_right_title=d.get("column_right_title", ""),
            column_left_items=d.get("column_left_items", []),
            column_right_items=d.get("column_right_items", []),
        )


@dataclass
class CoursePlan:
    module_title: str
    module_number: int
    module_total: int
    subtitle: str
    slides: List[Slide]
    product_name: str = ""  # nom du logiciel/produit documenté (ex: "Make.com"), affiché sur les badges

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "CoursePlan":
        return CoursePlan(
            module_title=d["module_title"],
            module_number=d["module_number"],
            module_total=d["module_total"],
            subtitle=d.get("subtitle", ""),
            slides=[Slide.from_dict(s) for s in d["slides"]],
            product_name=d.get("product_name", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)
