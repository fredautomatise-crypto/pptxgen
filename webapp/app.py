"""
Interface web (Streamlit) pour piloter tout le pipeline sans terminal :
upload d'un PDF, planification de la structure du cours, génération des
plans, chat d'affinage par module, puis génération des PPTX.

Lancer avec :
    streamlit run webapp/app.py
"""
import json
import shutil
import sys
from pathlib import Path

import streamlit as st

# Permet d'importer les modules du projet (config.py, course_planner.py, ...)
# qui vivent au niveau racine du repo, un cran au-dessus de webapp/.
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

import config

st.set_page_config(page_title=f"{config.BRAND_NAME} — Générateur de slides", page_icon="🎬", layout="wide")


def slugify(text: str) -> str:
    import re, unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "cours"


def init_state():
    defaults = {
        "pdf_path": None, "course_map": None, "plans": {}, "sections": None,
        "course_slug": None, "chat_histories": {},  # {module_number: [{"role":..,"content":..}, ...]}
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()

# ---------------------------------------------------------------------------
# Sidebar (config) — placée en premier dans le code pour que le thème choisi
# soit appliqué AVANT de générer le CSS/hero ci-dessous (config.load_theme()
# doit s'exécuter avant qu'on lise config.COLORS). Streamlit affiche le
# contenu "with st.sidebar" dans la colonne latérale quel que soit l'endroit
# du script où il est défini, donc ça ne change rien visuellement.
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    themes = config.list_themes()
    theme_names = [t["name"] for t in themes]
    theme_labels = {t["name"]: t["label"] for t in themes}
    chosen_theme = st.selectbox("Thème visuel des slides", theme_names, format_func=lambda n: theme_labels[n])
    if chosen_theme != config.ACTIVE_THEME:
        config.load_theme(chosen_theme)

    model = st.text_input("Modèle OpenAI (plan)", value=config.OPENAI_MODEL)
    chat_model = st.text_input("Modèle OpenAI (chat d'affinage)", value=config.CHAT_MODEL)
    st.caption(f"Clé API : {'✅ configurée' if config.OPENAI_API_KEY else '❌ manquante — voir .env'}")
    st.divider()
    st.caption("Le coût cumulé de la session s'affiche après chaque génération.")

# ---------------------------------------------------------------------------
# CSS + hero — générés à partir du thème actif, pour que l'app elle-même
# porte la même identité visuelle que les slides qu'elle produit.
# ---------------------------------------------------------------------------
C = config.COLORS


def _css() -> str:
    return f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {{
        font-family: 'Inter', sans-serif;
    }}

    .pptxgen-hero {{
        position: relative;
        background: linear-gradient(135deg, #{C['bg_dark']} 0%, #{C['bg_dark_alt']} 100%);
        border-radius: 20px;
        padding: 2.2rem 2.6rem;
        margin-bottom: 1.6rem;
        overflow: hidden;
    }}
    .pptxgen-hero::before {{
        content: "";
        position: absolute;
        width: 280px; height: 280px;
        border-radius: 50%;
        background: #{C['bg_dark_alt']};
        opacity: 0.55;
        top: -100px; right: -70px;
    }}
    .pptxgen-hero::after {{
        content: "";
        position: absolute;
        width: 170px; height: 170px;
        border-radius: 50%;
        background: #{C['bg_dark_alt']};
        opacity: 0.35;
        top: 30px; right: 50px;
    }}
    .pptxgen-badge {{
        display: inline-block;
        position: relative; z-index: 1;
        background: #{C['accent']};
        color: white;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        padding: 0.35rem 0.9rem;
        border-radius: 999px;
        margin-bottom: 0.9rem;
        text-transform: uppercase;
    }}
    .pptxgen-title {{
        font-family: 'Fraunces', serif;
        font-size: 2.6rem;
        font-weight: 600;
        color: white;
        margin: 0;
        position: relative; z-index: 1;
        line-height: 1.1;
    }}
    .pptxgen-tagline {{
        font-family: 'Inter', sans-serif;
        font-size: 1.05rem;
        color: #{C['text_light']};
        margin-top: 0.6rem;
        position: relative; z-index: 1;
        max-width: 640px;
    }}

    [data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 16px !important;
        border: 1px solid #{C['border_soft']} !important;
    }}

    .step-row {{
        display: flex;
        align-items: center;
        margin-bottom: 0.4rem;
    }}
    .step-badge {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 2rem; height: 2rem;
        border-radius: 50%;
        background: #{C['accent']};
        color: white;
        font-weight: 700;
        font-family: 'Inter', sans-serif;
        margin-right: 0.65rem;
        font-size: 0.95rem;
        flex-shrink: 0;
    }}
    .step-title {{
        font-family: 'Fraunces', serif;
        font-size: 1.35rem;
        font-weight: 600;
        color: #{C['text_dark']};
    }}

    .stButton>button {{
        background-color: #{C['accent']};
        color: white;
        border: none;
        border-radius: 10px;
        font-weight: 600;
        padding: 0.55rem 1.3rem;
        transition: background-color 0.15s ease;
    }}
    .stButton>button:hover {{
        background-color: #{C['accent_dark']};
        color: white;
    }}
    .stButton>button:disabled {{
        background-color: #{C['border_soft']};
        color: #{C['text_muted']};
    }}
    </style>
    """


def step_header(number: int, title: str):
    st.markdown(
        f'<div class="step-row"><span class="step-badge">{number}</span>'
        f'<span class="step-title">{title}</span></div>',
        unsafe_allow_html=True,
    )


st.markdown(_css(), unsafe_allow_html=True)

st.markdown(
    f"""
    <div class="pptxgen-hero">
        <span class="pptxgen-badge">🎬 AI Slide Generator</span>
        <h1 class="pptxgen-title">{config.BRAND_NAME}</h1>
        <p class="pptxgen-tagline">
            Transforme n'importe quelle documentation PDF en slides PowerPoint
            structurées — plan généré par IA, chat d'affinage avant export,
            zéro mise en page manuelle.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Étape 1 — Upload du PDF + infos du cours
# ---------------------------------------------------------------------------
with st.container(border=True):
    step_header(1, "Documentation source")
    col1, col2 = st.columns(2)
    with col1:
        uploaded_pdf = st.file_uploader("PDF de documentation officielle", type=["pdf"])
        course_title = st.text_input("Titre du cours", placeholder="ex: Cours Make.com complet")
    with col2:
        product_name = st.text_input("Nom du logiciel/produit documenté", placeholder="ex: Make.com")
        example_apps = st.text_input("Exemples d'applications à citer (séparés par des virgules, optionnel)",
                                      placeholder="Gmail, Notion, Slack, Airtable")

    MAX_PDF_SIZE_MB = 100

    if uploaded_pdf and course_title:
        size_mb = len(uploaded_pdf.getvalue()) / (1024 * 1024)
        if size_mb > MAX_PDF_SIZE_MB:
            st.error(f"PDF trop volumineux ({size_mb:.0f} Mo, max {MAX_PDF_SIZE_MB} Mo).")
        elif not uploaded_pdf.getvalue().startswith(b"%PDF-"):
            st.error("Ce fichier ne semble pas être un PDF valide (en-tête manquant).")
        else:
            # Nom de fichier sécurisé : on ignore le nom original (qui pourrait
            # contenir des séparateurs de chemin) et on utilise le slug du titre.
            pdf_path = ROOT_DIR / "cache" / "uploads" / f"{slugify(course_title)}.pdf"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(uploaded_pdf.getvalue())
            st.session_state.pdf_path = str(pdf_path)
            st.session_state.course_slug = slugify(course_title)
            st.success(f"PDF prêt : {uploaded_pdf.name} ({size_mb:.1f} Mo)")

# ---------------------------------------------------------------------------
# Étape 2 — Planifier la structure du cours
# ---------------------------------------------------------------------------
with st.container(border=True):
    step_header(2, "Structure du cours")
    if st.button("📐 Planifier la structure complète", disabled=not (uploaded_pdf and course_title)):
        import course_planner
        with st.spinner("Analyse du sommaire du PDF et planification des modules..."):
            course_map = course_planner.build_course_map(
                st.session_state.pdf_path, course_title, model=model,
                product_name=product_name or course_title,
            )
            course_map["example_apps"] = [a.strip() for a in example_apps.split(",") if a.strip()]
            st.session_state.course_map = course_map
        st.success(f"{len(course_map['modules'])} modules planifiés.")

    if st.session_state.course_map:
        st.write("Relis et ajuste les titres si besoin avant de continuer :")
        for m in st.session_state.course_map["modules"]:
            m["title"] = st.text_input(f"Module {m['number']}", value=m["title"], key=f"mod_title_{m['number']}")

# ---------------------------------------------------------------------------
# Étape 3 — Générer les plans (texte + notes de présentateur)
# ---------------------------------------------------------------------------
with st.container(border=True):
    step_header(3, "Plans de module (texte + notes de présentateur)")
    if st.button("📝 Générer tous les plans", disabled=not st.session_state.course_map):
        import pdf_extractor
        import content_planner

        course_map = st.session_state.course_map
        with st.spinner("Extraction complète du PDF..."):
            sections = pdf_extractor.extract_sections_cached(st.session_state.pdf_path, config.CACHE_DIR / "pdf_sections")

        progress = st.progress(0.0, text="Génération des plans...")
        modules = course_map["modules"]
        for i, m in enumerate(modules):
            matched = pdf_extractor.match_sections_by_topic(
                sections, m.get("topic_keywords", []) + m.get("source_headings", []))
            source_text = "\n\n".join(f"## {s.heading}\n{s.text}" for s in matched)
            if not source_text.strip():
                st.warning(f"Module {m['number']} ({m['title']}) : aucun contenu trouvé, ignoré.")
                continue
            plan = content_planner.build_course_plan(
                source_text=source_text, module_title=m["title"], module_number=m["number"],
                module_total=m["total"], topic=", ".join(m.get("topic_keywords", [])), model=model,
                product_name=course_map.get("product_name", course_title),
                example_apps=course_map.get("example_apps", []),
            )
            st.session_state.plans[m["number"]] = plan
            progress.progress((i + 1) / len(modules), text=f"Module {i + 1}/{len(modules)} : {m['title']}")
        progress.empty()
        st.success(f"{len(st.session_state.plans)} plans générés. {content_planner.cost_tracker.summary()}")

    if st.session_state.plans:
        with st.expander(f"📋 {len(st.session_state.plans)} plans générés — relire"):
            for num, plan in sorted(st.session_state.plans.items()):
                st.write(f"**Module {num} : {plan.module_title}** — {len(plan.slides)} slides")

# ---------------------------------------------------------------------------
# Étape 4 — Chat d'affinage (par module, avant génération du PPTX)
# ---------------------------------------------------------------------------
with st.container(border=True):
    step_header(4, "Affiner un module par le chat")
    st.caption("Discute avec l'IA de la structure/du contenu d'un module avant de générer son PPTX. "
               "Les changements concrets que tu demandes sont directement appliqués au plan.")

    if not st.session_state.plans:
        st.info("Génère d'abord les plans (étape 3) pour pouvoir les affiner ici.")
    else:
        plan_options = {num: f"Module {num} : {p.module_title} ({len(p.slides)} slides)"
                         for num, p in sorted(st.session_state.plans.items())}
        selected_num = st.selectbox("Module à affiner", options=list(plan_options.keys()),
                                     format_func=lambda n: plan_options[n])

        if selected_num not in st.session_state.chat_histories:
            st.session_state.chat_histories[selected_num] = []

        for msg in st.session_state.chat_histories[selected_num]:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        user_msg = st.chat_input("Écris ta demande ou ta question sur ce module...")
        if user_msg:
            import plan_chat
            with st.chat_message("user"):
                st.write(user_msg)
            with st.chat_message("assistant"):
                with st.spinner("Réflexion..."):
                    result = plan_chat.chat_turn(
                        plan=st.session_state.plans[selected_num],
                        history=st.session_state.chat_histories[selected_num],
                        user_message=user_msg,
                        model=chat_model,
                    )
                st.write(result.reply)
                if result.updated_plan is not None:
                    st.session_state.plans[selected_num] = result.updated_plan
                    st.caption(f"✅ Plan mis à jour ({len(result.updated_plan.slides)} slides).")

            st.session_state.chat_histories[selected_num].append({"role": "user", "content": user_msg})
            st.session_state.chat_histories[selected_num].append(result.raw_assistant_message)

# ---------------------------------------------------------------------------
# Étape 5 — Génération finale des PPTX
# ---------------------------------------------------------------------------
with st.container(border=True):
    step_header(5, "Génération finale des PPTX")
    if st.button("🚀 Générer tous les PPTX", disabled=not st.session_state.plans):
        import pptx_generator

        out_dir = ROOT_DIR / "output" / st.session_state.course_slug
        out_dir.mkdir(parents=True, exist_ok=True)
        progress = st.progress(0.0, text="Génération...")
        items = sorted(st.session_state.plans.items())

        for i, (num, plan) in enumerate(items):
            mod_slug = f"module_{num:02d}_{slugify(plan.module_title)}"
            mod_dir = out_dir / mod_slug
            mod_dir.mkdir(parents=True, exist_ok=True)
            pptx_path = mod_dir / f"{mod_slug}.pptx"
            pptx_generator.generate_pptx(plan, str(pptx_path))

            # Sauvegarde le plan + la conversation à côté du PPTX pour traçabilité
            import content_planner, plan_chat
            content_planner.save_plan(plan, str(mod_dir / "plan.json"))
            history = st.session_state.chat_histories.get(num, [])
            if history:
                plan_chat.save_conversation(history, str(mod_dir / "conversation.json"))

            progress.progress((i + 1) / len(items), text=f"Module {i + 1}/{len(items)} : {plan.module_title}")

        progress.empty()

        # Zip final téléchargeable
        zip_path = shutil.make_archive(str(out_dir), "zip", root_dir=str(out_dir))
        st.success("Génération terminée !")
        with open(zip_path, "rb") as f:
            st.download_button("⬇️ Télécharger tout le cours (.zip)", f, file_name=f"{st.session_state.course_slug}.zip")

        import content_planner
        st.caption(content_planner.cost_tracker.summary())

st.markdown(
    f'<p style="text-align:center; color:#{C["text_muted"]}; font-size:0.85rem; margin-top:2rem;">'
    f'{config.BRAND_NAME} · {config.TAGLINE}</p>',
    unsafe_allow_html=True,
)
