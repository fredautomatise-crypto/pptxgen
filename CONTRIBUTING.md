# Contribuer à PptxGen

Merci de vouloir contribuer ! Quelques repères avant de se lancer.

## Mettre en place l'environnement de dev

```bash
git clone https://github.com/<ton-compte>/automate-course-forge.git
cd automate-course-forge
python -m venv venv && source venv/bin/activate   # venv\Scripts\activate sous Windows
pip install -r requirements-dev.txt
cp .env.example .env   # renseigner OPENAI_API_KEY pour les tests d'intégration manuels
```

## Lancer les tests

```bash
pytest tests/ -v
```

Les tests couvrent surtout `pptx_generator.py` (non-régression sur le bug
historique des slides vides et du débordement de titre), `schema.py` et
`plan_chat.py` (avec l'API OpenAI mockée — aucun appel réel dans la suite de
tests, voir `tests/test_plan_chat.py` pour le pattern à suivre). Toute
nouvelle fonctionnalité touchant le rendu PPTX ou le chat doit s'accompagner
d'un test qui aurait échoué avant le correctif.

## Ajouter un nouveau type de slide

1. Ajouter la clé dans `COURSE_PLAN_JSON_SCHEMA` (`schema.py`, propriété `type.enum`)
2. Écrire la fonction `render_<type>()` dans `pptx_generator.py`, l'enregistrer dans `RENDERERS`
3. Documenter le mapping exact des champs `items` (icon/label/value/text/description)
   attendus pour ce type dans `SYSTEM_PROMPT_TEMPLATE` de `content_planner.py` —
   c'est la cause n°1 de "slides vides" si oublié
4. Ajouter un cas dans `tests/test_pptx_generator.py::TestGeneratePptxNoEmptySlides`

## Ajouter un thème visuel

Copier `themes/default.json`, adapter les couleurs/polices/nom de marque,
sauvegarder sous `themes/<nom>.json`. Aucune modification de code nécessaire.

## Modifier le comportement du chat d'affinage

Toute la logique vit dans `plan_chat.py`, utilisé à la fois par `chat_cli.py`
(terminal) et `webapp/app.py` (Streamlit) — ne jamais dupliquer cette
logique dans les deux interfaces, seulement l'affichage/la persistance.

Points d'attention si tu y touches :
- Le system prompt (`CHAT_SYSTEM_TEMPLATE`) réutilise `build_system_prompt()`
  de `content_planner.py` pour garder les mêmes règles de style/densité —
  ne duplique pas ces règles, importe-les.
- Le plan actuel est resérialisé en JSON dans le system prompt à CHAQUE
  tour : c'est ce qui permet de ne pas avoir à rejouer les `tool_calls`
  précédents dans l'historique (voir commentaire dans `chat_turn()`).
- L'outil `update_plan` doit toujours recevoir le plan COMPLET (choix
  assumé de simplicité pour ce MVP) — si tu passes à un diff ciblé pour des
  raisons de coût, adapte aussi `chat_cli.py` et `webapp/app.py` qui
  attendent aujourd'hui un `CoursePlan` complet en retour.

## Style de code

- Python 3.10+, pas de dépendance à des fonctionnalités plus récentes sans discussion
- Docstrings en français (le projet et son public sont francophones), noms de
  variables/fonctions en anglais (convention Python standard)
- `python -m py_compile <fichier>` avant de proposer une PR, a minima

## Signaler un bug

Merci d'inclure : commande exacte lancée, message d'erreur complet, OS,
version de Python (`python --version`), et si possible le `plan.json` du
module concerné (sans données sensibles).
