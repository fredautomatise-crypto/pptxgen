"""
Chat d'affinage : permet de discuter avec l'IA du plan d'un module (structure,
angle, contenu) AVANT de générer le PPTX, et de lui demander des modifications
en langage naturel.

Utilisé à la fois par :
- webapp/app.py (chat intégré à l'interface Streamlit)
- chat_cli.py (chat en ligne de commande, REPL terminal)

Fonctionnement — ÉDITION CIBLÉE (pas de régénération du plan entier) :
- Le modèle voit le plan actuel (chaque slide numérotée 1, 2, 3...) +
  l'historique de la conversation + le nouveau message utilisateur.
- Il dispose de 4 outils, chacun ciblant UNE ou PLUSIEURS slides précises,
  jamais le plan complet :
    - update_slide(slide_number, slide)   : remplace une slide existante
    - add_slide(position, slide)          : insère une nouvelle slide
    - delete_slide(slide_number)          : supprime une slide
    - move_slide(from_number, to_number)  : réordonne
- Un tour de chat peut déclencher plusieurs appels d'outils (ex: "corrige le
  titre de la slide 2 et ajoute une slide de conclusion à la fin"), appliqués
  dans l'ordre reçu.
- Si l'utilisateur ne demande qu'un avis/une discussion, aucun outil n'est
  appelé et le plan reste inchangé.

Pourquoi ce choix plutôt que renvoyer le plan complet (ancienne approche) :
un module de 15-20 slides fait resynthétiser TOUTES les slides à chaque
petite correction coûte cher en tokens ET risque de faire dériver légèrement
le contenu des slides non concernées (le modèle "réécrit" au lieu de
recopier à l'identique). Cibler une slide précise élimine les deux problèmes.

Ce module ne fait AUCUNE hypothèse sur l'UI : il retourne des données brutes
(texte de réponse + plan éventuellement mis à jour) et laisse l'appelant
(CLI ou Streamlit) gérer l'affichage et la persistance.
"""
import json
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any

from openai import OpenAI

import config
from retry_utils import openai_retry
from schema import CoursePlan, Slide, SLIDE_JSON_SCHEMA
from content_planner import cost_tracker, build_system_prompt

CHAT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_slide",
            "description": (
                "Remplace intégralement UNE slide existante par une nouvelle version. "
                "Utiliser pour corriger/modifier le contenu, le titre ou le type d'une "
                "slide précise SANS toucher aux autres slides."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "slide_number": {
                        "type": "integer",
                        "description": "Numéro de la slide à remplacer (1 = première slide du module).",
                    },
                    "slide": SLIDE_JSON_SCHEMA,
                },
                "required": ["slide_number", "slide"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_slide",
            "description": (
                "Insère une NOUVELLE slide à la position donnée. Les slides à partir "
                "de cette position (incluse) sont décalées d'un cran."
            ),
            "strict": True,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "position": {
                        "type": "integer",
                        "description": "Position d'insertion (1 = tout au début ; "
                                       "N+1 = à la fin s'il y a N slides actuellement).",
                    },
                    "slide": SLIDE_JSON_SCHEMA,
                },
                "required": ["position", "slide"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_slide",
            "description": "Supprime la slide au numéro donné.",
            "strict": True,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "slide_number": {"type": "integer"},
                },
                "required": ["slide_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_slide",
            "description": "Déplace une slide d'une position à une autre (réordonnancement).",
            "strict": True,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "from_number": {"type": "integer"},
                    "to_number": {"type": "integer"},
                },
                "required": ["from_number", "to_number"],
            },
        },
    },
]

CHAT_SYSTEM_TEMPLATE = """{base_style_prompt}

CONTEXTE SUPPLÉMENTAIRE — TU ES ICI DANS UN CHAT D'AFFINAGE :
Un plan de module a déjà été généré une première fois (voir les slides
numérotées ci-dessous). L'utilisateur va discuter avec toi pour l'améliorer
AVANT de générer le PPTX final. Ton rôle :

- Si l'utilisateur demande juste ton avis, pose une question, ou discute
  d'une idée sans te demander un changement concret : réponds normalement en
  texte, n'appelle AUCUN outil.
- Si l'utilisateur demande un changement concret, cible TOUJOURS une ou
  plusieurs slides précises avec les outils dédiés (update_slide / add_slide
  / delete_slide / move_slide) — ne renvoie JAMAIS le plan entier. Si la
  demande touche plusieurs slides ("simplifie les slides 3 à 5"), appelle
  l'outil approprié plusieurs fois dans le même tour, une fois par slide.
- Une slide modifiée ou ajoutée doit respecter les mêmes règles de style et
  de mapping de champs que celles décrites plus haut (mapping exact des
  champs "items" selon le type de slide).
- Si l'utilisateur ne précise pas de numéro de slide ("corrige la partie sur
  les webhooks"), déduis la bonne slide à partir du contenu affiché
  ci-dessous plutôt que de demander une clarification à chaque fois — ne
  demande une précision que si plusieurs slides correspondent vraiment.
- Reste concis dans tes réponses en texte (1-3 phrases) : confirme ce que tu
  as changé, le détail se voit dans le plan lui-même.

Plan actuel du module — {n_slides} slides :
---
{plan_text}
---
"""


@dataclass
class ChatTurnResult:
    reply: str
    updated_plan: Optional[CoursePlan]
    raw_assistant_message: Dict[str, Any]  # à ajouter tel quel à l'historique


def _format_plan_for_chat(plan: CoursePlan) -> str:
    """Liste chaque slide avec son numéro explicite (1-based), pour que le
    modèle puisse cibler précisément un update_slide/delete_slide/move_slide."""
    parts = []
    for i, slide in enumerate(plan.slides, start=1):
        parts.append(f"### Slide {i} (type: {slide.type})")
        parts.append(json.dumps(asdict(slide), ensure_ascii=False, indent=2))
    return "\n".join(parts)


def _build_system_prompt(plan: CoursePlan, product_name: str) -> str:
    base_style_prompt = build_system_prompt(product_name)
    return CHAT_SYSTEM_TEMPLATE.format(
        base_style_prompt=base_style_prompt,
        n_slides=len(plan.slides),
        plan_text=_format_plan_for_chat(plan),
    )


def _apply_tool_call(slides: List[Slide], name: str, args: Dict[str, Any]) -> str:
    """Applique un appel d'outil sur la liste de slides (mutation en place).
    Retourne une phrase résumant le changement (utilisée si le modèle ne
    fournit pas de texte de réponse)."""
    n = len(slides)

    if name == "update_slide":
        idx = args["slide_number"] - 1
        if not (0 <= idx < n):
            return f"⚠️ Slide {args['slide_number']} inexistante (le module en compte {n}) — ignoré."
        slides[idx] = Slide.from_dict(args["slide"])
        return f"Slide {args['slide_number']} mise à jour."

    if name == "add_slide":
        pos = max(1, min(args["position"], n + 1)) - 1
        slides.insert(pos, Slide.from_dict(args["slide"]))
        return f"Nouvelle slide insérée en position {pos + 1}."

    if name == "delete_slide":
        idx = args["slide_number"] - 1
        if not (0 <= idx < n):
            return f"⚠️ Slide {args['slide_number']} inexistante (le module en compte {n}) — ignoré."
        del slides[idx]
        return f"Slide {args['slide_number']} supprimée."

    if name == "move_slide":
        i, j = args["from_number"] - 1, args["to_number"] - 1
        if not (0 <= i < n) or not (0 <= j < n):
            return f"⚠️ Déplacement invalide (slides 1 à {n} seulement) — ignoré."
        slides.insert(j, slides.pop(i))
        return f"Slide déplacée de la position {args['from_number']} vers {args['to_number']}."

    return f"⚠️ Outil inconnu « {name} » — ignoré."


@openai_retry
def chat_turn(
    plan: CoursePlan,
    history: List[Dict[str, Any]],
    user_message: str,
    model: Optional[str] = None,
    product_name: str = "",
) -> ChatTurnResult:
    """
    Un tour de conversation. `history` est la liste des messages précédents
    (hors system prompt, qui est reconstruit à chaque appel pour toujours
    refléter le plan ACTUEL — important après une modification).

    Retourne le texte de réponse (toujours non-vide) et, le cas échéant, le
    CoursePlan mis à jour (None si aucune slide n'a été modifiée ce tour).
    """
    config.require_openai_api_key()
    cost_tracker.check_budget()
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    model = model or config.CHAT_MODEL
    system_prompt = _build_system_prompt(plan, product_name or plan.product_name or plan.module_title)

    # Ne renvoie que les derniers échanges : le plan complet est déjà
    # réinjecté dans le system prompt à chaque tour, donc l'historique ne
    # sert qu'au fil de la discussion, pas à retrouver l'état du plan.
    trimmed_history = history[-config.CHAT_HISTORY_MAX_MESSAGES:] if history else history

    messages = [{"role": "system", "content": system_prompt}] + trimmed_history + [
        {"role": "user", "content": user_message},
    ]

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        tools=CHAT_TOOLS,
        tool_choice="auto",
        temperature=0.5,
    )

    if getattr(response, "usage", None):
        cost = cost_tracker.add(model, response.usage)
        print(f"        (coût de ce tour de chat : ≈ ${cost:.3f})")

    choice = response.choices[0].message
    updated_plan = None

    if choice.tool_calls:
        new_slides = list(plan.slides)  # copie : on ne mute pas plan.slides directement
        change_summaries = []
        # Application SÉQUENTIELLE, dans l'ordre reçu : si le modèle appelle
        # move_slide puis update_slide, le slide_number du second appel désigne
        # la position APRÈS le déplacement du premier (voir test dédié dans
        # tests/test_plan_chat.py::TestMultipleToolCallsInOneTurn).
        for tool_call in choice.tool_calls:
            args = json.loads(tool_call.function.arguments)
            change_summaries.append(_apply_tool_call(new_slides, tool_call.function.name, args))

        updated_plan = CoursePlan(
            module_title=plan.module_title,
            module_number=plan.module_number,
            module_total=plan.module_total,
            subtitle=plan.subtitle,
            slides=new_slides,
            product_name=plan.product_name,
        )
        reply = choice.content or "\n".join(change_summaries)
    else:
        reply = choice.content or "(réponse vide)"

    # NB pour les futurs devs : on ne rejoue pas la trace technique des
    # tool_calls dans l'historique (pas de message role="tool"). Le system
    # prompt étant reconstruit à CHAQUE tour avec le plan à jour (voir
    # _build_system_prompt), le modèle voit toujours l'état courant sans
    # avoir besoin de la trace des appels précédents. Simplifie beaucoup la
    # gestion de l'historique pour ce MVP.
    raw_assistant_message = {
        "role": "assistant",
        "content": choice.content or "",
    }
    return ChatTurnResult(reply=reply, updated_plan=updated_plan, raw_assistant_message=raw_assistant_message)


def save_conversation(history: List[Dict[str, Any]], path: str) -> None:
    """Sauvegarde l'historique de chat à côté de plan.json — traçabilité :
    permet à quiconque reprend le projet de voir pourquoi le plan a changé."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_conversation(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
