import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from schema import CoursePlan, Slide
import plan_chat


def _make_plan(n_slides=2):
    slides = []
    for i in range(n_slides):
        slides.append({
            "type": "title" if i == 0 else "icon_list", "title": f"Slide {i+1}", "subtitle": "",
            "speaker_notes": "", "items": [], "column_left_title": "", "column_right_title": "",
            "column_left_items": [], "column_right_items": [],
        })
    return CoursePlan.from_dict({
        "module_title": "Module test", "module_number": 1, "module_total": 1,
        "subtitle": "", "product_name": "TestProduct", "slides": slides,
    })


def _fake_tool_call(name, args):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _fake_response(content=None, tool_calls=None, usage_tokens=(100, 50)):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=usage_tokens[0], completion_tokens=usage_tokens[1])
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


def _patched_client(response):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))


SAMPLE_SLIDE = {
    "type": "conclusion", "title": "Nouvelle conclusion", "subtitle": "", "speaker_notes": "",
    "items": [], "column_left_title": "", "column_right_title": "",
    "column_left_items": [], "column_right_items": [],
}


class TestChatTurnNoToolCall:
    def test_plain_reply_does_not_touch_plan(self):
        plan = _make_plan()
        response = _fake_response(content="Je pense que la structure est bonne.")
        with patch("plan_chat.OpenAI", return_value=_patched_client(response)):
            result = plan_chat.chat_turn(plan=plan, history=[], user_message="Qu'en penses-tu ?")
        assert result.updated_plan is None
        assert "structure" in result.reply


class TestUpdateSlide:
    def test_update_slide_replaces_only_target(self):
        plan = _make_plan(n_slides=2)
        tool_calls = [_fake_tool_call("update_slide", {"slide_number": 2, "slide": SAMPLE_SLIDE})]
        response = _fake_response(content=None, tool_calls=tool_calls)
        with patch("plan_chat.OpenAI", return_value=_patched_client(response)):
            result = plan_chat.chat_turn(plan=plan, history=[], user_message="Change la slide 2")
        assert result.updated_plan is not None
        assert len(result.updated_plan.slides) == 2
        assert result.updated_plan.slides[0].title == "Slide 1"  # inchangée
        assert result.updated_plan.slides[1].title == "Nouvelle conclusion"  # modifiée
        assert result.updated_plan.product_name == "TestProduct"  # préservé

    def test_update_slide_invalid_number_is_ignored_gracefully(self):
        plan = _make_plan(n_slides=2)
        tool_calls = [_fake_tool_call("update_slide", {"slide_number": 99, "slide": SAMPLE_SLIDE})]
        response = _fake_response(content=None, tool_calls=tool_calls)
        with patch("plan_chat.OpenAI", return_value=_patched_client(response)):
            result = plan_chat.chat_turn(plan=plan, history=[], user_message="Change la slide 99")
        # Le plan est retourné (avec un warning en texte) mais rien n'a explosé
        assert len(result.updated_plan.slides) == 2
        assert "inexistante" in result.reply.lower() or "⚠️" in result.reply


class TestAddSlide:
    def test_add_slide_inserts_at_position(self):
        plan = _make_plan(n_slides=2)
        tool_calls = [_fake_tool_call("add_slide", {"position": 1, "slide": SAMPLE_SLIDE})]
        response = _fake_response(content=None, tool_calls=tool_calls)
        with patch("plan_chat.OpenAI", return_value=_patched_client(response)):
            result = plan_chat.chat_turn(plan=plan, history=[], user_message="Ajoute une slide au début")
        assert len(result.updated_plan.slides) == 3
        assert result.updated_plan.slides[0].title == "Nouvelle conclusion"
        assert result.updated_plan.slides[1].title == "Slide 1"

    def test_add_slide_at_end(self):
        plan = _make_plan(n_slides=2)
        tool_calls = [_fake_tool_call("add_slide", {"position": 3, "slide": SAMPLE_SLIDE})]
        response = _fake_response(content=None, tool_calls=tool_calls)
        with patch("plan_chat.OpenAI", return_value=_patched_client(response)):
            result = plan_chat.chat_turn(plan=plan, history=[], user_message="Ajoute une slide à la fin")
        assert len(result.updated_plan.slides) == 3
        assert result.updated_plan.slides[2].title == "Nouvelle conclusion"


class TestDeleteSlide:
    def test_delete_slide_removes_target_only(self):
        plan = _make_plan(n_slides=2)
        tool_calls = [_fake_tool_call("delete_slide", {"slide_number": 1})]
        response = _fake_response(content=None, tool_calls=tool_calls)
        with patch("plan_chat.OpenAI", return_value=_patched_client(response)):
            result = plan_chat.chat_turn(plan=plan, history=[], user_message="Supprime la slide 1")
        assert len(result.updated_plan.slides) == 1
        assert result.updated_plan.slides[0].title == "Slide 2"


class TestMoveSlide:
    def test_move_slide_reorders(self):
        plan = _make_plan(n_slides=2)
        tool_calls = [_fake_tool_call("move_slide", {"from_number": 1, "to_number": 2})]
        response = _fake_response(content=None, tool_calls=tool_calls)
        with patch("plan_chat.OpenAI", return_value=_patched_client(response)):
            result = plan_chat.chat_turn(plan=plan, history=[], user_message="Mets la slide 1 après la 2")
        assert result.updated_plan.slides[0].title == "Slide 2"
        assert result.updated_plan.slides[1].title == "Slide 1"


class TestMultipleToolCallsInOneTurn:
    def test_two_updates_in_same_turn(self):
        plan = _make_plan(n_slides=2)
        tool_calls = [
            _fake_tool_call("update_slide", {"slide_number": 1, "slide": {**SAMPLE_SLIDE, "title": "A"}}),
            _fake_tool_call("update_slide", {"slide_number": 2, "slide": {**SAMPLE_SLIDE, "title": "B"}}),
        ]
        response = _fake_response(content=None, tool_calls=tool_calls)
        with patch("plan_chat.OpenAI", return_value=_patched_client(response)):
            result = plan_chat.chat_turn(plan=plan, history=[], user_message="Corrige les slides 1 et 2")
        assert result.updated_plan.slides[0].title == "A"
        assert result.updated_plan.slides[1].title == "B"

    def test_move_then_update_uses_positions_after_the_move(self):
        """
        Comportement documenté (pas une garantie idéale, juste la sémantique
        réelle) : les tool_calls d'un même tour sont appliqués SÉQUENTIELLEMENT,
        dans l'ordre reçu. Si le modèle appelle move_slide PUIS update_slide,
        le numéro utilisé par update_slide désigne la position APRÈS le move,
        pas la position d'origine. Le modèle voit cette règle dans le prompt
        système ("appelle l'outil plusieurs fois... dans l'ordre"), mais un
        futur contributeur qui touche à _apply_tool_call doit savoir que ce
        test fixe ce comportement — le casser silencieusement romprait des
        chats en cours sans qu'aucune erreur ne remonte.
        """
        plan = _make_plan(n_slides=3)  # Slide 1, Slide 2, Slide 3
        tool_calls = [
            # Déplace Slide 1 en position 3 -> ordre devient : Slide 2, Slide 3, Slide 1
            _fake_tool_call("move_slide", {"from_number": 1, "to_number": 3}),
            # Cible la position 3 APRÈS ce déplacement, donc "Slide 1" (pas "Slide 3")
            _fake_tool_call("update_slide", {"slide_number": 3, "slide": {**SAMPLE_SLIDE, "title": "Modifiée"}}),
        ]
        response = _fake_response(content=None, tool_calls=tool_calls)
        with patch("plan_chat.OpenAI", return_value=_patched_client(response)):
            result = plan_chat.chat_turn(plan=plan, history=[], user_message="Déplace puis corrige")
        titles = [s.title for s in result.updated_plan.slides]
        assert titles == ["Slide 2", "Slide 3", "Modifiée"]


class TestConversationPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        history = [{"role": "user", "content": "Salut"}, {"role": "assistant", "content": "Bonjour"}]
        path = tmp_path / "conversation.json"
        plan_chat.save_conversation(history, str(path))
        loaded = plan_chat.load_conversation(str(path))
        assert loaded == history

    def test_load_missing_file_returns_empty_list(self, tmp_path):
        loaded = plan_chat.load_conversation(str(tmp_path / "does_not_exist.json"))
        assert loaded == []
