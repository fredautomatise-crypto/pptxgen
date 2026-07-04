"""
Chat en ligne de commande pour discuter d'un plan de module avec l'IA avant
de générer le PPTX. S'appuie sur plan_chat.py (logique partagée avec l'UI web).

Usage :
    python chat_cli.py cache/module_3/plan.json

Commandes spéciales pendant le chat :
    generer / générer / go     -> quitte le chat et affiche la commande pptx_generator à lancer
    quitter / exit             -> quitte sans rien générer (le plan modifié reste sauvegardé)

Tout le reste est traité comme un message envoyé à l'IA.

La conversation est sauvegardée à chaque tour dans un fichier
`conversation.json` à côté du plan.json, pour garder une trace de pourquoi le
plan a changé (utile pour les devs qui reprendront le projet).
"""
import argparse
import sys
from pathlib import Path

import config
import content_planner
import plan_chat


def main():
    parser = argparse.ArgumentParser(description="Chat d'affinage du plan d'un module avant génération PPTX")
    parser.add_argument("plan_path", help="Chemin vers plan.json à affiner")
    parser.add_argument("--model", default=None, help="Modèle OpenAI pour le chat (défaut: config.CHAT_MODEL)")
    args = parser.parse_args()

    plan_path = Path(args.plan_path)
    if not plan_path.exists():
        print(f"[erreur] Plan introuvable : {plan_path}")
        sys.exit(1)

    plan = content_planner.load_plan(str(plan_path))
    conversation_path = plan_path.parent / "conversation.json"
    history = plan_chat.load_conversation(str(conversation_path))

    print(f"💬 Chat d'affinage — module « {plan.module_title} » ({len(plan.slides)} slides)")
    print("Discute librement, demande des changements, puis tape « générer » quand tu es satisfait.")
    print("(« quitter » pour sortir sans générer — le plan reste sauvegardé tel quel)\n")

    while True:
        try:
            user_input = input("Toi > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nÀ bientôt.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("generer", "générer", "go"):
            print(f"\n✅ Plan final : {plan_path} ({len(plan.slides)} slides)")
            print("Génère le PPTX avec :")
            print(f"    python pptx_generator.py {plan_path} <sortie.pptx>")
            print("(ou relance main.py --plan ... --stop-after pptx si tu es passé par ce chat depuis main.py)")
            break
        if user_input.lower() in ("quitter", "exit", "quit"):
            print("À bientôt — le plan n'a pas été régénéré depuis ta dernière modification validée.")
            break

        result = plan_chat.chat_turn(
            plan=plan,
            history=history,
            user_message=user_input,
            model=args.model,
        )
        print(f"\nIA  > {result.reply}\n")

        history.append({"role": "user", "content": user_input})
        history.append(result.raw_assistant_message)
        plan_chat.save_conversation(history, str(conversation_path))

        if result.updated_plan is not None:
            plan = result.updated_plan
            content_planner.save_plan(plan, str(plan_path))
            print(f"        → plan.json mis à jour ({len(plan.slides)} slides) — {plan_path}\n")

    print(f"\n{content_planner.cost_tracker.summary()}")


if __name__ == "__main__":
    main()
