"""
Valide que les schémas JSON exposés à l'API OpenAI (COURSE_PLAN_JSON_SCHEMA,
SLIDE_JSON_SCHEMA, et les paramètres des outils de plan_chat.py) sont
eux-mêmes des JSON Schema valides, ET qu'un exemple de charge utile typique
les respecte. Objectif : attraper une erreur de schéma (propriété oubliée
dans `required`, typo dans un nom de champ...) en local et gratuitement,
plutôt que de la découvrir via un appel API qui échoue (ou pire, un appel
qui "réussit" avec un schéma légèrement incorrect côté validation stricte).
"""
import sys
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft7Validator

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from schema import COURSE_PLAN_JSON_SCHEMA, SLIDE_JSON_SCHEMA
import plan_chat

SAMPLE_SLIDE = {
    "type": "icon_list", "title": "Titre exemple", "subtitle": "", "speaker_notes": "Notes exemple",
    "items": [
        {"icon": "bolt", "label": "Label", "value": "", "text": "", "description": "Description"},
    ],
    "column_left_title": "", "column_right_title": "",
    "column_left_items": [], "column_right_items": [],
}

SAMPLE_COURSE_PLAN = {
    "module_title": "Module exemple", "module_number": 1, "module_total": 3,
    "subtitle": "Sous-titre", "slides": [SAMPLE_SLIDE],
}


class TestSchemasAreValidJsonSchema:
    """Les schémas eux-mêmes doivent être des JSON Schema syntaxiquement
    valides (erreur fréquente : propriété citée dans required mais absente
    de properties, ou l'inverse)."""

    def test_course_plan_schema_is_valid(self):
        Draft7Validator.check_schema(COURSE_PLAN_JSON_SCHEMA["schema"])

    def test_slide_schema_is_valid(self):
        Draft7Validator.check_schema(SLIDE_JSON_SCHEMA)

    @pytest.mark.parametrize("tool", plan_chat.CHAT_TOOLS)
    def test_chat_tool_schemas_are_valid(self, tool):
        Draft7Validator.check_schema(tool["function"]["parameters"])


class TestSamplePayloadsMatchSchema:
    """Un exemple de charge utile réaliste doit valider contre le schéma —
    attrape les cas où le schéma est valide EN SOI mais trop strict/permissif
    par rapport à ce que content_planner.py ou plan_chat.py produisent
    réellement."""

    def test_sample_slide_matches_slide_schema(self):
        jsonschema.validate(SAMPLE_SLIDE, SLIDE_JSON_SCHEMA)

    def test_sample_course_plan_matches_schema(self):
        jsonschema.validate(SAMPLE_COURSE_PLAN, COURSE_PLAN_JSON_SCHEMA["schema"])

    def test_update_slide_tool_payload(self):
        tool = next(t for t in plan_chat.CHAT_TOOLS if t["function"]["name"] == "update_slide")
        payload = {"slide_number": 2, "slide": SAMPLE_SLIDE}
        jsonschema.validate(payload, tool["function"]["parameters"])

    def test_add_slide_tool_payload(self):
        tool = next(t for t in plan_chat.CHAT_TOOLS if t["function"]["name"] == "add_slide")
        payload = {"position": 1, "slide": SAMPLE_SLIDE}
        jsonschema.validate(payload, tool["function"]["parameters"])

    def test_delete_slide_tool_payload(self):
        tool = next(t for t in plan_chat.CHAT_TOOLS if t["function"]["name"] == "delete_slide")
        jsonschema.validate({"slide_number": 1}, tool["function"]["parameters"])

    def test_move_slide_tool_payload(self):
        tool = next(t for t in plan_chat.CHAT_TOOLS if t["function"]["name"] == "move_slide")
        jsonschema.validate({"from_number": 1, "to_number": 3}, tool["function"]["parameters"])


class TestSchemasRejectMalformedPayloads:
    """S'assure que additionalProperties=False fonctionne vraiment (piège
    classique : l'oublier sur un sous-objet imbriqué comme 'slide' dans les
    paramètres d'un outil, alors qu'il est présent au niveau racine)."""

    def test_slide_schema_rejects_unknown_field(self):
        bad_slide = {**SAMPLE_SLIDE, "unknown_field": "surprise"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_slide, SLIDE_JSON_SCHEMA)

    def test_update_slide_tool_rejects_unknown_field_in_nested_slide(self):
        tool = next(t for t in plan_chat.CHAT_TOOLS if t["function"]["name"] == "update_slide")
        bad_payload = {"slide_number": 1, "slide": {**SAMPLE_SLIDE, "unknown_field": "surprise"}}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad_payload, tool["function"]["parameters"])

    def test_slide_schema_rejects_missing_required_field(self):
        incomplete_slide = {k: v for k, v in SAMPLE_SLIDE.items() if k != "title"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(incomplete_slide, SLIDE_JSON_SCHEMA)
