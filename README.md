---
title: PptxGen
emoji: 🎬
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 8501
pinned: false
license: mit
---

# 🎬 PptxGen

Transforme n'importe quelle documentation technique (PDF) en **slides
PowerPoint prêtes à diffuser**, avec un chat d'affinage avec l'IA avant la
génération finale — en ligne de commande ou depuis une interface web.

Make.com est fourni en exemple (profil prêt à l'emploi), mais le moteur est
générique : n'importe quel PDF de documentation produit un cours dans le
même pipeline.

```
PDF de documentation
   │  pdf_extractor.py — pdfplumber + PyMuPDF
   ▼
Texte structuré par section
   │  course_planner.py — découpe le PDF entier en modules cohérents (LLM, quasi gratuit)
   ▼
Structure du cours (course_map.json)
   │  content_planner.py — GPT génère slides + notes de présentateur par module (JSON structuré)
   ▼
Plan de module (plan.json)
   │  plan_chat.py — chat d'affinage avec l'IA (discuter, corriger, développer un point...)
   │  utilisé par chat_cli.py (terminal) ou webapp/app.py (web)
   ▼
Plan affiné (plan.json mis à jour + conversation.json pour traçabilité)
   │  pptx_generator.py
   ▼
module.pptx (thème visuel configurable, notes de présentateur incluses)
```

> ℹ️ **Historique** : ce projet incluait à l'origine la génération de voix
> off (TTS) et de vidéo MP4 synchronisée. Cette partie a été retirée du MVP
> pour se concentrer sur un PPTX de qualité + un chat d'affinage — voir
> "Fonctionnalités retirées" en bas de ce README si tu dois comprendre
> d'anciennes traces de code/discussions qui en parlent encore.

## ✨ Fonctionnalités

- **Générique** : n'importe quel PDF de doc technique, pas seulement Make.com
- **Découpage automatique** en modules pédagogiques cohérents sur toute la doc
- **Densité de contenu dynamique** : pas de nombre de slides fixe — le LLM
  adapte la quantité à la richesse réelle du sujet, avec un plancher minimum
  (8 slides/module) et des limites anti-surcharge par type de slide (voir
  `content_planner.py`, section "QUANTITÉ DE CONTENU" du prompt système)
- **Chat d'affinage avant génération** : discute avec l'IA du plan d'un
  module (structure, ton, contenu manquant...) et demande des changements en
  langage naturel, en CLI (`chat_cli.py`) ou dans l'interface web — voir
  `plan_chat.py` pour la logique partagée
- **Notes de présentateur** : le script détaillé par slide (généré par le
  LLM) est injecté comme note PowerPoint (visible en mode Présentateur),
  remplaçant l'ancien usage "voix off" de ce champ
- **Thèmes visuels** multiples (`default`, `slate`, `indigo`), 100%
  personnalisables sans toucher au code (`themes/*.json`)
- **Interface web** (Streamlit) : upload, clic, chat, résultat — sans terminal
- **Docker** : zéro configuration système (plus besoin de LibreOffice/FFmpeg
  depuis la suppression du pipeline vidéo)
- **Suivi de coût réel** : chaque appel LLM (plan ET chat) affiche son coût
  exact (tokens facturés)
- **Reprenable** : interruption/relance sans perdre le travail déjà fait
- **Testé** : suite pytest + CI GitHub Actions

## 🚀 Démarrage rapide

### Option A — Docker (recommandé, zéro installation système)

```bash
git clone https://github.com/<ton-compte>/automate-course-forge.git
cd automate-course-forge
cp .env.example .env   # renseigner OPENAI_API_KEY
docker compose up --build
```

Ouvre ensuite [http://localhost:8501](http://localhost:8501) — interface web prête.

### Option B — Installation locale

```bash
git clone https://github.com/<ton-compte>/automate-course-forge.git
cd automate-course-forge
python -m venv venv && source venv/bin/activate   # venv\Scripts\activate sous Windows
pip install -r requirements.txt
cp .env.example .env   # renseigner OPENAI_API_KEY
```

Aucune dépendance système requise (PyMuPDF gère la lecture du PDF, python-pptx
la génération — pas de LibreOffice/FFmpeg dans ce MVP "PPTX only").

Lance ensuite l'UI web (`streamlit run webapp/app.py`) ou utilise le CLI ci-dessous.

## 🖥️ Utilisation en ligne de commande

### Couvrir toute une documentation (plusieurs modules)

```bash
# 1. Planifie la structure complète du cours (quasi gratuit : sommaire seulement)
python course_planner.py doc.pdf "Cours complet" --product "Nom du logiciel"
# -> relis/ajuste cache/course_map.json si besoin

# 2. Génère le PLAN (texte + notes de présentateur) de tous les modules,
#    sans PPTX, pour relecture avant l'étape finale
python batch_generate.py --pdf doc.pdf --course-map cache/course_map.json --stop-after plan

# 3. Relis/édite les plans dans cache/<cours>/module_XX/plan.json si besoin
#    (à la main, ou via le chat : python chat_cli.py cache/<cours>/module_XX/plan.json)
#    puis génère les PPTX de tous les modules
python batch_generate.py --course-map cache/course_map.json --stop-after pptx
```

`batch_generate.py` est **reprenable** (saute ce qui existe déjà, sauf
`--force`) et supporte `--only "1,3,5-7"` pour ne traiter qu'un sous-ensemble
de modules. Ajoute `--chat` pour ouvrir un chat d'affinage interactif module
par module avant chaque génération PPTX (adapté à un petit nombre de
modules — voir `python batch_generate.py --help`).

### Utiliser le profil Make.com fourni en exemple

```bash
python course_planner.py doc_make.pdf --profile make_com
```

Préconfigure le nom de produit, le thème visuel et les exemples
d'applications à citer (voir `profiles/make_com.json`).

### Un seul module ciblé, avec chat d'affinage

```bash
python main.py --pdf doc.pdf --title "Nom du module" --number 1 --total 6 \
    --topic "mot-clé1,mot-clé2" --chat
```

`--chat` ouvre un chat interactif juste après la génération du plan et juste
avant la génération du PPTX (voir `chat_cli.py`).

### Chat d'affinage seul, sur un plan déjà généré

```bash
python chat_cli.py cache/module_1/plan.json
```

### Options communes

| Flag | Effet |
|---|---|
| `--theme slate` | Change le thème visuel (voir `themes/`) |
| `--product "Nom"` | Nom du logiciel documenté (utilisé dans les prompts et les badges) |
| `--model gpt-4.1-mini` | Change le modèle OpenAI pour la génération du plan (moins cher, un peu moins fin) |
| `--chat` | Ouvre un chat d'affinage avant de générer le PPTX (main.py / batch_generate.py) |

## 🌐 Interface web

```bash
streamlit run webapp/app.py
```

Upload du PDF → structure éditable en direct → génération des plans → chat
d'affinage par module (chat intégré, un onglet par module) → génération PPTX
→ téléchargement du cours complet en `.zip`.

## 🎨 Personnaliser le thème visuel

Copie `themes/default.json`, adapte les couleurs/polices/nom de marque,
sauvegarde sous `themes/<nom>.json` — aucune modification de code requise.
Utilisable ensuite via `--theme <nom>` ou dans le sélecteur de l'UI web.

## 💬 Comment fonctionne le chat d'affinage (pour les devs qui reprennent le projet)

Voir `plan_chat.py` pour la logique complète, commentée en détail. Résumé :

- Un seul appel LLM par tour de conversation, avec le plan ACTUEL du module
  sérialisé en JSON dans le system prompt (reconstruit à chaque tour).
- Le modèle a accès à un unique outil (`update_plan`, function calling) dont
  le schéma est identique à celui de la génération initiale
  (`schema.COURSE_PLAN_JSON_SCHEMA`). S'il décide qu'un changement de
  contenu est nécessaire, il renvoie le plan COMPLET mis à jour (pas un
  diff — plus simple à appliquer et à auditer, quitte à coûter un peu plus
  de tokens : choix assumé de simplicité pour ce MVP).
- S'il ne touche pas à l'outil, c'est qu'il répond juste en discussion.
- La conversation est sauvegardée dans `conversation.json` à côté de
  `plan.json`, pour que n'importe qui reprenant le projet puisse voir
  pourquoi le plan a changé.
- `chat_cli.py` (terminal) et `webapp/app.py` (Streamlit) sont deux
  interfaces différentes au-dessus de la MÊME fonction `plan_chat.chat_turn`
  — ne pas dupliquer la logique de chat ailleurs.

**Pistes d'amélioration pour les devs suivants** : édition ciblée d'une
slide précise plutôt que replan complet (utile si le coût devient un sujet
sur de gros cours), retry automatique si le tool call renvoie un JSON
invalide, undo/historique de versions du plan.

## 💰 Coût

Chaque appel LLM (génération du plan ET tours de chat) affiche son coût
réel (tokens facturés), avec un total cumulé en fin de session/batch. Avec
`gpt-4.1` : environ **0,04 à 0,08 $ par module** pour la génération initiale
(un peu plus si le module génère beaucoup de slides) ; chaque tour de chat
utilise `gpt-4.1-mini` par défaut (moins cher, largement suffisant pour de
l'édition ciblée).

Un plafond de sécurité (`MAX_SESSION_COST_USD`, 20 $ par défaut) arrête
proprement toute génération si le coût cumulé de la session le dépasse —
protection contre un bug qui enchaînerait des appels à l'infini.

## 🛡️ Robustesse & sécurité

- **Cache d'extraction PDF** (`pdf_extractor.extract_sections_cached`) :
  un PDF volumineux n'est reparsé qu'une fois, même en cas d'interruption
  et de reprise du batch.
- **Retry automatique** (`retry_utils.py`, via `tenacity`) sur tous les
  appels OpenAI : 5 tentatives avec backoff exponentiel sur les erreurs
  transitoires (rate limit, timeout réseau, erreur 500 ponctuelle) — un
  batch de 18 modules ne plante plus à mi-parcours pour une erreur qui se
  serait résolue d'elle-même.
- **Plafond de coût** (`MAX_SESSION_COST_USD`) et **validation de clé API**
  explicite avant le premier appel (message clair plutôt qu'une erreur
  OpenAI cryptique).
- **Validation anti-traversée de chemin** sur `--theme`/`--profile` (rejette
  tout nom contenant `/`, `\` ou `..`).
- **Upload PDF validé côté web** : taille plafonnée (100 Mo), vérification
  de l'en-tête `%PDF-`, nom de fichier reconstruit (jamais le nom original
  utilisé tel quel dans un chemin).
- **Schémas JSON testés** (`tests/test_tool_schemas.py`, via `jsonschema`) :
  valide que les schémas envoyés à l'API sont corrects EN SOI (pas
  seulement que le code qui les utilise ne plante pas), et qu'un payload
  malformé est bien rejeté (`additionalProperties: false` vérifié
  explicitement, y compris sur les objets imbriqués).
- **Conteneur Docker en utilisateur non-root.**

## 🧩 Étendre le projet

Voir [CONTRIBUTING.md](CONTRIBUTING.md) pour : ajouter un type de slide, un
thème, ou lancer la suite de tests.

## 📁 Structure du projet

```
automate-course-forge/
├── main.py                # Orchestrateur : un seul module (+ option --chat)
├── batch_generate.py       # Orchestrateur : tous les modules d'un cours
├── course_planner.py       # Planifie la structure globale du cours (LLM, léger)
├── content_planner.py      # Génère slides + notes de présentateur par module (LLM, structuré)
├── plan_chat.py             # Logique du chat d'affinage (partagée CLI + web)
├── chat_cli.py               # Chat d'affinage en ligne de commande
├── pdf_extractor.py        # Extraction texte/structure du PDF
├── pptx_generator.py       # Génération des slides (python-pptx)
├── schema.py                 # Schéma de données du plan de cours
├── config.py                  # Configuration + chargement des thèmes
├── themes/                    # Thèmes visuels (JSON)
├── profiles/                  # Profils préconfigurés (ex: make_com.json)
├── webapp/app.py              # Interface web Streamlit (avec chat intégré)
├── tests/                      # Suite pytest
└── .github/workflows/ci.yml    # CI GitHub Actions
```

## ⚠️ Limites connues

- Le plan LLM peut occasionnellement générer un contenu trop long pour une
  boîte de texte — une relecture visuelle reste recommandée avant diffusion
  (ou passe par le chat pour demander de raccourcir un point précis).
- La détection de titres dans `pdf_extractor.py` se base sur les bookmarks
  PDF ou, à défaut, la taille de police — un PDF sans hiérarchie visuelle
  peut nécessiter un découpage manuel via `--topic`.
- Le chat d'affinage renvoie le plan COMPLET à chaque modification (pas de
  diff ciblé) : sur un module à beaucoup de slides, chaque tour de chat qui
  modifie le plan coûte sensiblement le même prix qu'une génération initiale.

## 🗑️ Fonctionnalités retirées (historique)

Les versions précédentes de ce projet généraient aussi une narration audio
(3 moteurs TTS interchangeables : Piper local, edge-tts, ElevenLabs) et une
vidéo MP4 avec sous-titres synchronisés (LibreOffice + PyMuPDF + moviepy).
Cette partie a été volontairement retirée pour concentrer le MVP sur un
PPTX de qualité + un chat d'affinage. Le champ `narration` du schéma a été
renommé `speaker_notes` (rétrocompatible : un ancien `plan.json` avec
`narration` continue de se charger correctement, voir `schema.py`). Si le
besoin audio/vidéo revient un jour, l'ancien code est consultable dans
l'historique Git du projet.

## Licence

[MIT](LICENSE)
