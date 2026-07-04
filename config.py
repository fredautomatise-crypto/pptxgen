"""
Configuration du générateur de cours. Le style visuel (couleurs, polices,
nom de marque) vient d'un THÈME chargé dynamiquement depuis themes/*.json —
voir load_theme() plus bas. Ça permet de personnaliser complètement
l'identité visuelle sans toucher au code de rendu (pptx_generator.py).
"""
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = BASE_DIR / "cache"
THEMES_DIR = BASE_DIR / "themes"
PROFILES_DIR = BASE_DIR / "profiles"

OUTPUT_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Clés API / modèles
# ---------------------------------------------------------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")

# Garde-fou : arrête proprement (RuntimeError explicite) plutôt que de
# continuer à enchaîner des appels payants si un bug (boucle, mauvais
# paramètre) fait dériver la facture. 0 ou négatif = pas de limite.
MAX_SESSION_COST_USD = float(os.getenv("MAX_SESSION_COST_USD", "20.0"))


def require_openai_api_key():
    """À appeler avant tout premier appel API — message clair immédiat
    plutôt qu'une erreur d'authentification cryptique renvoyée par OpenAI."""
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY manquant. Copie .env.example en .env et renseigne ta clé "
            "(voir https://platform.openai.com/api-keys)."
        )

# Modèle utilisé par plan_chat.py pour le chat d'affinage avant génération du
# PPTX. Séparé de OPENAI_MODEL pour permettre d'utiliser un modèle moins cher
# côté chat (beaucoup d'allers-retours courts) et un modèle plus poussé pour
# la génération du plan initial.
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4.1-mini")

# Nombre max de messages d'historique (user+assistant confondus) renvoyés à
# l'API à chaque tour de chat. Le plan complet étant déjà réinjecté dans le
# system prompt à chaque tour (voir plan_chat._build_system_prompt), l'IA n'a
# pas besoin de tout l'historique pour rester cohérente — au-delà de
# quelques échanges récents, le coût augmente sans bénéfice réel.
CHAT_HISTORY_MAX_MESSAGES = int(os.getenv("CHAT_HISTORY_MAX_MESSAGES", "12"))

MODEL_PRICING = {
    "gpt-4.1":       {"input": 2.00, "output": 8.00},
    "gpt-4.1-mini":  {"input": 0.40, "output": 1.60},
    "gpt-4.1-nano":  {"input": 0.10, "output": 0.40},
    "gpt-5.4":       {"input": 2.50, "output": 15.00},
    "gpt-5.4-mini":  {"input": 0.75, "output": 4.50},
    "default":       {"input": 2.00, "output": 8.00},
}

# ---------------------------------------------------------------------------
# Thème visuel
# ---------------------------------------------------------------------------
DEFAULT_ICON_MAP = {
    "target": "◎", "grid": "⊞", "hexagon": "⬡", "swap": "↔", "lock": "⚿",
    "diamond": "◈", "bolt": "⚡", "check": "✓", "warning": "⚠", "clock": "⏱",
    "calendar": "📅", "gear": "⚙", "fork": "⑂", "loop": "⟳", "cross": "❌",
    "arrow": "→", "down": "↓", "search": "🔍", "chat": "💬", "star": "★",
    "link": "🔗", "doc": "📄", "cloud": "☁", "shield": "🛡",
}

SLIDE_WIDTH_IN = 13.333
SLIDE_HEIGHT_IN = 7.5


def list_themes():
    """Retourne la liste des thèmes disponibles (nom + libellé)."""
    themes = []
    for f in sorted(THEMES_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        themes.append({"name": data.get("name", f.stem), "label": data.get("label", f.stem)})
    return themes


def _safe_name(name: str, kind: str) -> str:
    """Rejette tout nom contenant un séparateur de chemin ou '..' — évite
    qu'un --theme/--profile malicieux (ou mal formé) sorte des dossiers
    themes/ ou profiles/ (ex: --theme "../../../etc/passwd")."""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError(f"Nom de {kind} invalide : « {name} ». "
                          f"Utilise uniquement des lettres/chiffres/tirets, sans chemin.")
    return name


def load_theme(theme_name: str = None):
    """
    Charge un thème depuis themes/<theme_name>.json et l'applique aux
    variables globales du module (COLORS, ICON_PALETTE, FONTS, BRAND_NAME,
    TAGLINE, ICON_MAP). Appelé une fois au démarrage avec le thème choisi
    (CLI --theme, variable d'env THEME, ou "default").
    """
    theme_name = _safe_name(theme_name or os.getenv("THEME", "default"), "thème")
    theme_path = THEMES_DIR / f"{theme_name}.json"
    if not theme_path.exists():
        available = ", ".join(t["name"] for t in list_themes())
        raise FileNotFoundError(f"Thème « {theme_name} » introuvable dans {THEMES_DIR}. "
                                 f"Thèmes disponibles : {available}")
    data = json.loads(theme_path.read_text(encoding="utf-8"))

    global COLORS, ICON_PALETTE, FONTS, BRAND_NAME, TAGLINE, ICON_MAP, ACTIVE_THEME
    COLORS = data["colors"]
    ICON_PALETTE = data["icon_palette"]
    FONTS = data["fonts"]
    BRAND_NAME = data.get("brand_name", "PptxGen")
    TAGLINE = data.get("tagline", "AI Course Generator")
    ICON_MAP = DEFAULT_ICON_MAP
    ACTIVE_THEME = theme_name
    return data


def load_profile(profile_name: str) -> dict:
    """Charge un profil (produit + thème + exemples préconfigurés) depuis profiles/<name>.json."""
    profile_name = _safe_name(profile_name, "profil")
    profile_path = PROFILES_DIR / f"{profile_name}.json"
    if not profile_path.exists():
        available = ", ".join(p.stem for p in PROFILES_DIR.glob("*.json"))
        raise FileNotFoundError(f"Profil « {profile_name} » introuvable dans {PROFILES_DIR}. "
                                 f"Profils disponibles : {available}")
    return json.loads(profile_path.read_text(encoding="utf-8"))


# Chargement initial (thème par défaut, ou celui défini dans .env / THEME)
load_theme()
