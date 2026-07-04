"""
Tests du générateur PPTX : vérifie qu'aucune slide ne peut être générée vide
(régression du bug corrigé en production) et que l'estimation de hauteur de
titre reste cohérente pour des titres de longueurs très différentes.
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import config
config.load_theme("default")

import pptx_generator as pg
from schema import SlideItem, CoursePlan, Slide


class TestItemLabelDesc:
    """Le helper de repli doit toujours produire un label non vide dès qu'AU
    MOINS un champ pertinent est rempli, quel que soit celui utilisé par le LLM."""

    def test_label_and_description_filled(self):
        item = SlideItem(icon="bolt", label="Titre", value="", text="", description="Description")
        label, desc = pg.item_label_desc(item)
        assert label == "Titre"
        assert desc == "Description"

    def test_only_text_filled(self):
        """Cas réel observé en production : le LLM ne remplit que 'text'."""
        item = SlideItem(icon="bolt", label="", value="", text="Contenu dans text", description="")
        label, desc = pg.item_label_desc(item)
        assert label == "Contenu dans text"

    def test_only_value_filled(self):
        item = SlideItem(icon="bolt", label="", value="Valeur", text="", description="")
        label, desc = pg.item_label_desc(item)
        assert label == "Valeur"

    def test_all_empty_does_not_crash(self):
        item = SlideItem(icon="bolt", label="", value="", text="", description="")
        label, desc = pg.item_label_desc(item)
        assert label == ""
        assert desc == ""


class TestTitleLineEstimate:
    """L'estimation de lignes doit rester cohérente : un titre plus long
    n'estime jamais MOINS de lignes qu'un titre plus court à taille égale."""

    @pytest.mark.parametrize("title,font_size,width,max_expected_lines", [
        ("Webhooks", 44, 9.8, 1),
        ("Router, Iterator, Aggregator", 44, 9.8, 2),
        ("Approfondir : Scénarios avancés et logique conditionnelle", 28, 9.8, 3),
    ])
    def test_line_estimate_reasonable(self, title, font_size, width, max_expected_lines):
        lines = pg._estimate_lines(title, font_size, width)
        assert 1 <= lines <= max_expected_lines + 1  # tolérance

    def test_longer_title_never_fewer_lines(self):
        short = pg._estimate_lines("Court", 44, 9.8)
        long = pg._estimate_lines("Un titre beaucoup beaucoup plus long que le précédent", 44, 9.8)
        assert long >= short


class TestGeneratePptxNoEmptySlides:
    """Génère un pptx complet (tous les types de slide) et vérifie qu'aucune
    slide ne se retrouve sans aucun texte visible."""

    @pytest.fixture
    def sample_plan(self):
        return CoursePlan(
            module_title="Module de test",
            module_number=1, module_total=1,
            subtitle="Sous-titre de test",
            product_name="TestProduct",
            slides=[
                Slide(type="title", subtitle="Sous-titre de test"),
                Slide(type="objectives", title="Objectifs", items=[
                    SlideItem(icon="bolt", text="Objectif 1"),
                    SlideItem(icon="check", text="Objectif 2"),
                ]),
                Slide(type="stats", title="Chiffres clés", items=[
                    SlideItem(icon="grid", value="100", label="Label", description="Description"),
                ]),
                Slide(type="section", title="Section 1"),
                Slide(type="icon_list", title="Liste", items=[
                    SlideItem(icon="bolt", label="Item 1", description="Desc 1"),
                    SlideItem(icon="bolt", text="Seulement text rempli"),  # cas limite réel
                ]),
                Slide(type="icon_grid", title="Grille", items=[
                    SlideItem(icon="bolt", label="Item 1", description="Desc 1"),
                ]),
                Slide(type="two_column", title="Comparaison",
                      column_left_title="Gauche", column_right_title="Droite",
                      column_left_items=["Point A"], column_right_items=["Point B"]),
                Slide(type="table", title="Tableau", items=[
                    SlideItem(icon="", label="Col1", description="Col2"),
                ]),
                Slide(type="process_flow", title="Flux", items=[
                    SlideItem(icon="bolt", label="Étape 1", description="Desc étape 1"),
                    SlideItem(icon="bolt", label="Étape 2", description="Desc étape 2"),
                ]),
                Slide(type="conclusion", title="Conclusion", items=[
                    SlideItem(icon="check", text="Point à retenir"),
                ]),
            ],
        )

    def test_generate_pptx_succeeds(self, sample_plan, tmp_path):
        output_path = tmp_path / "test.pptx"
        result = pg.generate_pptx(sample_plan, str(output_path))
        assert Path(result).exists()
        assert Path(result).stat().st_size > 0

    def test_no_slide_without_any_text(self, sample_plan, tmp_path):
        output_path = tmp_path / "test.pptx"
        pg.generate_pptx(sample_plan, str(output_path))

        prs = pg.Presentation(str(output_path))
        for i, slide in enumerate(prs.slides, start=1):
            texts = [
                shape.text_frame.text.strip()
                for shape in slide.shapes
                if shape.has_text_frame and shape.text_frame.text.strip()
            ]
            # Chaque slide doit avoir AU MOINS un texte visible autre que le footer.
            non_boilerplate = [t for t in texts if "made with" not in t.lower()]
            assert len(non_boilerplate) > 0, f"Slide {i} ({slide_types_debug(sample_plan, i)}) semble vide"

    def test_all_slide_types_render_without_exception(self, sample_plan, tmp_path):
        """Chaque type de slide connu doit se générer sans lever d'exception."""
        for slide_type in pg.RENDERERS:
            plan = CoursePlan(
                module_title="Test", module_number=1, module_total=1, subtitle="",
                slides=[Slide(type=slide_type, title="Titre test", items=[
                    SlideItem(icon="bolt", label="L", text="T", description="D", value="V"),
                ])],
            )
            output_path = tmp_path / f"test_{slide_type}.pptx"
            pg.generate_pptx(plan, str(output_path))
            assert output_path.exists()


def slide_types_debug(plan, slide_number):
    idx = slide_number - 1
    return plan.slides[idx].type if idx < len(plan.slides) else "?"
