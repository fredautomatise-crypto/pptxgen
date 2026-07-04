import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from schema import CoursePlan, Slide, SlideItem, COURSE_PLAN_JSON_SCHEMA


class TestSlideFromDict:
    def test_minimal_slide(self):
        s = Slide.from_dict({"type": "title", "title": "T", "subtitle": "", "narration": "",
                              "items": [], "column_left_title": "", "column_right_title": "",
                              "column_left_items": [], "column_right_items": []})
        assert s.type == "title"
        assert s.items == []

    def test_slide_with_items(self):
        s = Slide.from_dict({
            "type": "stats", "title": "T", "subtitle": "", "narration": "",
            "items": [{"icon": "bolt", "label": "L", "value": "V", "text": "", "description": "D"}],
            "column_left_title": "", "column_right_title": "",
            "column_left_items": [], "column_right_items": [],
        })
        assert len(s.items) == 1
        assert isinstance(s.items[0], SlideItem)
        assert s.items[0].value == "V"


class TestCoursePlanFromDict:
    def test_roundtrip(self):
        data = {
            "module_title": "Module test", "module_number": 1, "module_total": 3,
            "subtitle": "Sous-titre", "product_name": "TestProduct",
            "slides": [
                {"type": "title", "title": "", "subtitle": "", "narration": "", "items": [],
                 "column_left_title": "", "column_right_title": "",
                 "column_left_items": [], "column_right_items": []},
            ],
        }
        plan = CoursePlan.from_dict(data)
        assert plan.module_title == "Module test"
        assert plan.product_name == "TestProduct"
        assert len(plan.slides) == 1

    def test_product_name_defaults_to_empty(self):
        data = {
            "module_title": "M", "module_number": 1, "module_total": 1, "subtitle": "",
            "slides": [],
        }
        plan = CoursePlan.from_dict(data)
        assert plan.product_name == ""

    def test_to_dict_roundtrip(self):
        data = {
            "module_title": "M", "module_number": 1, "module_total": 1, "subtitle": "",
            "slides": [],
        }
        plan = CoursePlan.from_dict(data)
        d = plan.to_dict()
        assert d["module_title"] == "M"
        plan2 = CoursePlan.from_dict(d)
        assert plan2.module_title == plan.module_title


class TestJsonSchema:
    def test_schema_has_required_slide_types(self):
        slide_type_enum = COURSE_PLAN_JSON_SCHEMA["schema"]["properties"]["slides"]["items"]["properties"]["type"]["enum"]
        expected = {"title", "objectives", "stats", "section", "icon_list", "icon_grid",
                    "two_column", "table", "process_flow", "conclusion"}
        assert expected.issubset(set(slide_type_enum))

    def test_schema_is_strict(self):
        assert COURSE_PLAN_JSON_SCHEMA["strict"] is True
