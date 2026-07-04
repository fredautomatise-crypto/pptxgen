"""
Transforme la matière brute extraite du PDF (pdf_extractor.py) en un plan de
module structuré : slides typées + notes de présentateur par slide, dans le
style pédagogique de la marque configurée (voir config.BRAND_NAME / themes/*.json).

Utilise l'API OpenAI avec "structured outputs" (response_format=json_schema)
pour garantir que la réponse respecte exactement COURSE_PLAN_JSON_SCHEMA.
"""
import json
from typing import Optional

from openai import OpenAI

import config
from retry_utils import openai_retry
from schema import CoursePlan, COURSE_PLAN_JSON_SCHEMA


class CostTracker:
    """Suit le coût réel des appels LLM (basé sur les tokens réellement
    facturés par l'API, pas une estimation a priori)."""

    def __init__(self):
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    def check_budget(self):
        """À appeler AVANT de lancer un nouvel appel API — bloque si le
        plafond configuré (config.MAX_SESSION_COST_USD) est déjà dépassé,
        plutôt que de découvrir une facture qui a dérivé après coup."""
        limit = config.MAX_SESSION_COST_USD
        if limit > 0 and self.cost_usd >= limit:
            raise RuntimeError(
                f"Plafond de coût de session atteint (${self.cost_usd:.2f} ≥ ${limit:.2f}). "
                f"Augmente MAX_SESSION_COST_USD dans .env si c'est voulu, ou relance une "
                f"nouvelle session pour repartir le compteur à zéro."
            )

    def add(self, model: str, usage) -> float:
        prices = config.MODEL_PRICING.get(model, config.MODEL_PRICING["default"])
        cost = (usage.prompt_tokens / 1_000_000) * prices["input"] \
             + (usage.completion_tokens / 1_000_000) * prices["output"]
        self.calls += 1
        self.input_tokens += usage.prompt_tokens
        self.output_tokens += usage.completion_tokens
        self.cost_usd += cost
        return cost

    def summary(self) -> str:
        return (f"{self.calls} appel(s) LLM — "
                f"{self.input_tokens:,} tokens in / {self.output_tokens:,} tokens out — "
                f"≈ ${self.cost_usd:.3f}").replace(",", " ")


# Instance partagée : importée par batch_generate.py / main.py pour afficher
# un total cumulé à la fin d'une génération multi-modules.
cost_tracker = CostTracker()

SYSTEM_PROMPT_TEMPLATE = """Tu es un concepteur pédagogique senior qui crée une formation professionnelle \
sur "{product_name}", à partir de sa documentation officielle, dans le style \
de la marque "{brand_name}".

STYLE À RESPECTER STRICTEMENT :
- Ton pédagogique, concret, orienté action. Phrases courtes.
- Illustre systématiquement avec des exemples concrets et réalistes liés au \
sujet du document{example_hint}.
- Structure d'un module type : slide de titre -> slide "objectifs + prérequis \
+ durée estimée" -> slides de contexte/chiffres clés -> slides de section \
(transition) -> slides de contenu détaillé (listes à icônes, grilles, \
comparaisons, tableaux, schémas de flux) -> slide de conclusion / prochaines \
étapes.
- Varier les types de slides (ne jamais enchaîner deux fois le même type de \
suite si possible).

QUANTITÉ DE CONTENU — RÈGLE DE DENSITÉ DYNAMIQUE :
- Il n'y a PAS de nombre de slides cible fixe. Le nombre de slides doit \
refléter la richesse réelle du contenu source : un module qui couvre un \
sujet dense doit avoir plus de slides qu'un module sur un sujet simple.
- PLANCHER MINIMUM : un module ne descend jamais en dessous de 8 slides, \
même sur un sujet source court (si besoin, développe davantage chaque \
concept avec des exemples concrets plutôt que de meubler artificiellement).
- PAS DE PLAFOND : si le contenu source est riche, n'hésite pas à produire \
20, 25 slides ou plus — mieux vaut plusieurs slides claires qu'une slide \
surchargée.
- RÈGLE ANTI-SURCHARGE (priorité absolue sur la brièveté) : chaque slide \
doit rester lisible d'un coup d'œil. Limites strictes par type :
  - "icon_list" : maximum 5 items par slide.
  - "icon_grid" : maximum 6 items par slide (grille 2x3).
  - "table" : maximum 8 lignes par slide.
  - "process_flow" : maximum 6 étapes par slide.
  - "objectives" : maximum 6 items.
  Si le contenu source dépasse une de ces limites pour un même thème, NE \
JAMAIS tasser au-delà de la limite : crée plusieurs slides du même type à la \
suite (ex: deux slides "icon_grid" consécutives) pour couvrir l'intégralité \
du contenu en respectant la limite par slide.
- Chaque slide de contenu détaillé (icon_list/icon_grid/table/process_flow) \
doit apporter une information substantielle par item (pas de labels vagues \
type "Autre fonctionnalité" sans description utile) : mieux vaut moins \
d'items bien expliqués que remplir la slide avec du contenu creux.
- Les icônes ("icon" dans les items) doivent être choisies parmi cette liste \
de clés uniquement : target, grid, hexagon, swap, lock, diamond, bolt, \
check, warning, clock, calendar, gear, fork, loop, cross, arrow, down, \
search, chat, star, link, doc, cloud, shield.
- Ne jamais inventer de statistiques : si le document source ne donne pas de \
chiffre, formule le point sans chiffre précis.
- Remplis toujours TOUS les champs du schéma même s'ils sont vides ("" ou \
[]) pour les slides qui n'utilisent pas ce champ (ex: "items": [] pour une \
slide de type "two_column").
- IMPORTANT — mapping exact des champs "items" selon le type de slide \
(un champ non rempli au bon endroit = slide vide à l'affichage) :
  - "objectives" : remplir "text" (la phrase de l'objectif). "label", \
"value", "description" restent vides.
  - "stats" : remplir "value" (le chiffre/donnée, ex: "100 000"), "label" \
(le nom court, ex: "Records max") ET "description" (1 phrase de contexte). \
"text" reste vide.
  - "icon_list" / "icon_grid" / "process_flow" : remplir "label" (titre \
court de l'item) ET "description" (1-2 phrases). "text" et "value" \
restent vides.
  - "conclusion" : remplir "text" (la phrase à retenir). "label", "value", \
"description" restent vides.
  - "table" : remplir "label" (colonne 1) ET "description" (colonne 2). \
"text" et "value" restent vides.
  Ne jamais tout mettre dans "text" par défaut : chaque type de slide lit \
des champs précis, un mauvais champ rempli produit une slide sans texte \
visible.
"""


def build_system_prompt(product_name: str, example_apps: Optional[list] = None) -> str:
    brand_name = getattr(config, "BRAND_NAME", "PptxGen")
    example_hint = ""
    if example_apps:
        example_hint = f" (par exemple : {', '.join(example_apps)})"
    return SYSTEM_PROMPT_TEMPLATE.format(
        product_name=product_name, brand_name=brand_name, example_hint=example_hint,
    )

USER_PROMPT_TEMPLATE = """Voici le contenu brut extrait de la documentation officielle (section : {topic}) :

---
{source_text}
---

Génère le plan complet du module {module_number} sur {module_total}, intitulé \
"{module_title}", à partir de ce contenu. Le module doit être fidèle au \
contenu source (ne pas inventer de fonctionnalités qui n'existent pas), \
tout en respectant le style pédagogique décrit dans les instructions système.
"""


@openai_retry
def build_course_plan(
    source_text: str,
    module_title: str,
    module_number: int,
    module_total: int,
    topic: str = "",
    model: Optional[str] = None,
    product_name: str = "l'outil documenté",
    example_apps: Optional[list] = None,
) -> CoursePlan:
    config.require_openai_api_key()
    cost_tracker.check_budget()
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    model = model or config.OPENAI_MODEL
    system_prompt = build_system_prompt(product_name, example_apps)

    user_prompt = USER_PROMPT_TEMPLATE.format(
        topic=topic or module_title,
        source_text=source_text[:60000],  # garde-fou taille contexte
        module_number=module_number,
        module_total=module_total,
        module_title=module_title,
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_schema", "json_schema": COURSE_PLAN_JSON_SCHEMA},
        temperature=0.6,
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)
    if getattr(response, "usage", None):
        cost = cost_tracker.add(model, response.usage)
        print(f"        (coût de cet appel : ≈ ${cost:.3f} — "
              f"{response.usage.prompt_tokens} in / {response.usage.completion_tokens} out)")
    plan = CoursePlan.from_dict(data)
    plan.product_name = product_name
    return plan


def save_plan(plan: CoursePlan, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)


def load_plan(path: str) -> CoursePlan:
    with open(path, "r", encoding="utf-8") as f:
        return CoursePlan.from_dict(json.load(f))


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 5:
        print("Usage: python content_planner.py source.txt \"Titre du module\" numero total")
        sys.exit(1)
    src_path, title, num, total = sys.argv[1:5]
    with open(src_path, "r", encoding="utf-8") as f:
        text = f.read()
    plan = build_course_plan(text, title, int(num), int(total))
    out_path = str(config.CACHE_DIR / "plan.json")
    save_plan(plan, out_path)
    print(f"Plan sauvegardé : {out_path} ({len(plan.slides)} slides)")
