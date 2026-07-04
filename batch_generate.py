"""
Génère TOUS les modules d'un cours en une fois (PPTX uniquement), à partir de
la structure planifiée par course_planner.py.

Flux recommandé pour couvrir toute la doc :

  # 1) Planifier la structure complète du cours (quasi gratuit : sommaire seulement)
  python course_planner.py doc.pdf "Cours complet" --product "Nom du logiciel"
  # -> relire cache/course_map.json, ajuster les titres/regroupements si besoin

  # 2) Générer le PLAN (texte + notes de présentateur) de tous les modules,
  #    sans PPTX, pour tout relire avant de lancer la génération finale
  python batch_generate.py --pdf doc.pdf --course-map cache/course_map.json --stop-after plan

  # 3) Relire/éditer les plans dans cache/<slug>/module_XX/plan.json si besoin
  #    (à la main, ou via « python chat_cli.py cache/<slug>/module_XX/plan.json »),
  #    puis lancer la génération PPTX de tous les modules
  python batch_generate.py --course-map cache/course_map.json --stop-after pptx

Le script est reprenable : s'il est interrompu ou relancé, il saute les
modules dont le plan.json (ou le pptx, selon --stop-after) existe déjà,
sauf si --force est passé.
"""
import argparse
import sys
from pathlib import Path

import config


def slugify(text: str) -> str:
    import re, unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text or "module"


def main():
    parser = argparse.ArgumentParser(description="Génère tous les modules d'un cours en batch, à partir d'un PDF")
    parser.add_argument("--pdf", help="PDF source (requis sauf si tous les plans existent déjà)")
    parser.add_argument("--course-map", required=True, help="Chemin vers course_map.json (voir course_planner.py)")
    parser.add_argument("--stop-after", choices=["plan", "pptx"], default="plan",
                         help="Étape à laquelle s'arrêter POUR CHAQUE module (défaut: plan, pour relecture)")
    parser.add_argument("--model", default=None, help="Modèle OpenAI (override config.py)")
    parser.add_argument("--only", default="", help="Ne générer que ces numéros de module, ex: '1,3,5-7'")
    parser.add_argument("--force", action="store_true",
                         help="Régénère le PPTX même s'il existe déjà (le PLAN, lui, n'est jamais régénéré "
                              "par ce flag pour éviter un appel LLM non voulu — utiliser --force-plan pour ça)")
    parser.add_argument("--force-plan", action="store_true",
                         help="Régénère aussi le plan.json (relance un appel LLM payant pour chaque module concerné)")
    parser.add_argument("--chat", action="store_true",
                         help="Ouvre un chat d'affinage interactif pour CHAQUE module avant de générer son PPTX. "
                              "⚠️ Adapté à un petit nombre de modules (chat séquentiel, un module à la fois) — "
                              "pour un gros batch, préfère éditer les plan.json directement ou lancer chat_cli.py "
                              "module par module après coup.")
    parser.add_argument("--theme", default=None, help="Thème visuel à utiliser (voir themes/*.json), défaut: 'default'")
    args = parser.parse_args()

    if args.theme:
        config.load_theme(args.theme)

    import course_planner
    course_map = course_planner.load_course_map(args.course_map)
    modules = course_map["modules"]

    if args.only:
        wanted = set()
        for part in args.only.split(","):
            if "-" in part:
                a, b = part.split("-")
                wanted.update(range(int(a), int(b) + 1))
            else:
                wanted.add(int(part))
        modules = [m for m in modules if m["number"] in wanted]

    course_slug = slugify(course_map.get("course_title", "cours"))
    print(f"Cours « {course_map.get('course_title')} » — {len(modules)} module(s) à traiter\n")

    import pdf_extractor
    import content_planner
    import pptx_generator

    # Extraction du PDF UNE SEULE FOIS pour tous les modules (au lieu de le
    # relire intégralement à chaque module).
    all_sections = None
    if args.pdf:
        print(f"Extraction complète du PDF « {args.pdf} » (une seule fois, patiente si le PDF est volumineux)...")
        all_sections = pdf_extractor.extract_sections_cached(args.pdf, config.CACHE_DIR / "pdf_sections")
        print(f"  → {len(all_sections)} section(s) extraite(s) du PDF.\n")

    results = []
    for m in modules:
        mod_slug = f"module_{m['number']:02d}_{slugify(m['title'])}"
        work_dir = config.CACHE_DIR / course_slug / mod_slug
        out_dir = config.OUTPUT_DIR / course_slug / mod_slug
        work_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        plan_path = work_dir / "plan.json"
        pptx_path = out_dir / f"{mod_slug}.pptx"

        print(f"── Module {m['number']}/{len(modules)} : {m['title']} " + "─" * 10)

        # --- Plan (LLM) ---
        # ⚠️ Ne dépend jamais de --force (qui sert à forcer le PPTX) :
        # régénérer un plan appelle l'API et coûte de l'argent, donc il faut
        # le demander explicitement avec --force-plan.
        if plan_path.exists() and not args.force_plan:
            print(f"   [skip] plan déjà présent : {plan_path}")
            plan = content_planner.load_plan(str(plan_path))
        else:
            if all_sections is None:
                print("   [erreur] --pdf requis pour générer un nouveau plan"); continue
            matched = pdf_extractor.match_sections_by_topic(
                all_sections, m.get("topic_keywords", []) + m.get("source_headings", []),
            )
            source_text = "\n\n".join(f"## {s.heading}\n{s.text}" for s in matched)
            if not source_text.strip():
                print(f"   [warn] aucun contenu trouvé pour ce module (headings/keywords ne matchent rien) — ignoré")
                continue
            plan = content_planner.build_course_plan(
                source_text=source_text,
                module_title=m["title"],
                module_number=m["number"],
                module_total=m["total"],
                topic=", ".join(m.get("topic_keywords", [])),
                model=args.model,
                product_name=course_map.get("product_name") or course_map.get("course_title", "l'outil documenté"),
                example_apps=course_map.get("example_apps", []),
            )
            content_planner.save_plan(plan, str(plan_path))
            print(f"   [ok] plan sauvegardé ({len(plan.slides)} slides) → {plan_path}")

        if args.stop_after == "plan":
            results.append({"module": m["number"], "title": m["title"], "plan": str(plan_path)})
            continue

        # --- Chat d'affinage optionnel (avant le PPTX) ---
        if args.chat:
            import chat_cli
            print(f"   [chat] Ouverture du chat d'affinage pour ce module — tape « générer » pour continuer.")
            sys.argv = ["chat_cli.py", str(plan_path)]
            chat_cli.main()
            plan = content_planner.load_plan(str(plan_path))  # recharge la version affinée

        # --- PPTX ---
        if pptx_path.exists() and not args.force:
            print(f"   [skip] pptx déjà présent : {pptx_path}")
        else:
            pptx_generator.generate_pptx(plan, str(pptx_path))
            print(f"   [ok] pptx → {pptx_path}")

        results.append({"module": m["number"], "title": m["title"], "pptx": str(pptx_path)})

    print("\n" + "═" * 50)
    print(f"Terminé : {len(results)}/{len(modules)} module(s) traités jusqu'à l'étape « {args.stop_after} »")
    print(content_planner.cost_tracker.summary())


if __name__ == "__main__":
    main()
