"""
Orchestrateur principal : génère un module de cours (PPTX uniquement) à
partir d'un PDF de documentation officielle, avec une étape optionnelle de
chat d'affinage avant la génération du PPTX.

Exemples :

  # 1) Juste le plan (pour relecture/chat avant de générer le PPTX)
  python main.py --pdf doc_make.pdf --title "Router, Iterator, Aggregator" \
      --number 3 --total 6 --topic "router,iterator,aggregator" --stop-after plan

  # 2) Pipeline complet jusqu'au PPTX, avec chat d'affinage interactif avant génération
  python main.py --pdf doc_make.pdf --title "Veille Digitale RSS vers Notion" \
      --number 3 --total 6 --topic "rss,notion,webhook" --chat

  # 3) Reprendre depuis un plan déjà généré/édité (à la main ou via le chat)
  python main.py --plan cache/module_3/plan.json --stop-after pptx
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
    parser = argparse.ArgumentParser(description="Génère le PPTX d'un module de cours à partir d'un PDF")
    parser.add_argument("--pdf", help="Chemin vers le PDF de documentation officielle")
    parser.add_argument("--product", default="", help="Nom du logiciel/produit documenté (ex: 'Make.com'). Défaut: le titre du module.")
    parser.add_argument("--topic", default="", help="Mots-clés séparés par des virgules pour cibler une section du PDF (ex: 'router,iterator,aggregator')")
    parser.add_argument("--title", help="Titre du module (ex: 'Router, Iterator, Aggregator')")
    parser.add_argument("--number", type=int, default=1, help="Numéro du module")
    parser.add_argument("--total", type=int, default=1, help="Nombre total de modules du cours")
    parser.add_argument("--plan", help="Repartir d'un plan JSON déjà généré (édité manuellement ou non), saute l'étape LLM")
    parser.add_argument("--stop-after", choices=["extract", "plan", "pptx"],
                         default="pptx", help="Étape à laquelle s'arrêter (utile pour relire/éditer avant de continuer)")
    parser.add_argument("--chat", action="store_true",
                         help="Ouvre un chat interactif (terminal) pour affiner le plan avant de générer le PPTX")
    parser.add_argument("--model", default=None, help="Modèle OpenAI à utiliser pour le plan (override config.py)")
    parser.add_argument("--theme", default=None, help="Thème visuel à utiliser (voir themes/*.json), défaut: 'default'")
    args = parser.parse_args()

    if args.theme:
        config.load_theme(args.theme)

    if not args.plan and (not args.pdf or not args.title):
        parser.error("Fournir soit --plan, soit --pdf + --title")

    slug = slugify(args.title) if args.title else Path(args.plan).stem
    work_dir = config.CACHE_DIR / slug
    work_dir.mkdir(parents=True, exist_ok=True)
    out_dir = config.OUTPUT_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    plan = None
    plan_path = work_dir / "plan.json"

    # --- Étape 1 : extraction PDF ---------------------------------------
    if not args.plan:
        import pdf_extractor
        print(f"[1/3] Extraction du PDF « {args.pdf} »" + (f" (sujet: {args.topic})" if args.topic else ""))
        if args.topic:
            source_text = pdf_extractor.extract_topic(args.pdf, args.topic.split(","))
        else:
            sections = pdf_extractor.extract_sections_cached(args.pdf, config.CACHE_DIR / "pdf_sections")
            source_text = "\n\n".join(f"## {s.heading}\n{s.text}" for s in sections)
        if not source_text.strip():
            print("[erreur] Aucun contenu extrait — vérifie le PDF ou les mots-clés --topic.")
            sys.exit(1)
        (work_dir / "source_extracted.txt").write_text(source_text, encoding="utf-8")
        print(f"        → {len(source_text)} caractères extraits, sauvegardés dans {work_dir / 'source_extracted.txt'}")
        if args.stop_after == "extract":
            return

        # --- Étape 2 : plan de module (LLM) ------------------------------
        import content_planner
        print(f"[2/3] Génération du plan de module via {args.model or config.OPENAI_MODEL}...")
        plan = content_planner.build_course_plan(
            source_text=source_text,
            module_title=args.title,
            module_number=args.number,
            module_total=args.total,
            topic=args.topic,
            model=args.model,
            product_name=args.product or args.title,
        )
        content_planner.save_plan(plan, str(plan_path))
        print(f"        → {len(plan.slides)} slides planifiées, sauvegardées dans {plan_path}")
        print(f"        → Relis / édite ce fichier si besoin avant de continuer, ou utilise --chat "
              f"pour affiner avec l'IA en discutant.")
        if args.stop_after == "plan":
            return
    else:
        import content_planner
        print(f"[plan] Chargement du plan existant : {args.plan}")
        plan_path = Path(args.plan)
        plan = content_planner.load_plan(args.plan)

    # --- Étape optionnelle : chat d'affinage -----------------------------
    if args.chat:
        import chat_cli
        sys.argv = ["chat_cli.py", str(plan_path)]
        print("\n[chat] Ouverture du chat d'affinage — tape « générer » quand tu es satisfait.\n")
        chat_cli.main()
        import content_planner
        plan = content_planner.load_plan(str(plan_path))  # recharge la version affinée

    # --- Étape 3 : génération PPTX ---------------------------------------
    import pptx_generator
    pptx_path = out_dir / f"{slug}.pptx"
    print(f"[3/3] Génération du PPTX...")
    pptx_generator.generate_pptx(plan, str(pptx_path))
    print(f"        → {pptx_path}")

    print("\nTerminé ! Fichiers produits :")
    print(f"  - PPTX : {pptx_path}")
    print(f"  - Plan : {plan_path}")


if __name__ == "__main__":
    main()
