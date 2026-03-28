# Analizador — Analyse grammaticale espagnole

Application desktop (Windows) pour l'apprentissage de l'espagnol par la lecture.
Capture une image de texte espagnol (webcam, écran, fichier ou presse-papier),
extrait le texte par OCR et affiche une analyse grammaticale interactive
avec code couleur par catégorie et groupe syntaxique.

![PySide6](https://img.shields.io/badge/PySide6-Qt6-green)
![Claude API](https://img.shields.io/badge/Claude-Anthropic-orange)
![PaddleOCR](https://img.shields.io/badge/PaddleOCR-v5-blue)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

## Installation

### Option 1 — Installeur Windows (recommandé)

Télécharger `Analizador_1.0_setup.exe` depuis la page [Releases](../../releases/latest) et exécuter l'installeur.

L'installeur inclut tout sauf :
- **Clé API Anthropic** : demandée au premier lancement ([obtenir une clé](https://console.anthropic.com/))
- **RealSR** (optionnel) : super-résolution GPU, téléchargeable séparément — voir ci-dessous

### Option 2 — Depuis les sources

```bash
git clone https://github.com/votre-compte/analizador.git
cd analizador
python -m venv venv
venv\Scripts\activate

pip install PySide6 PySide6-WebEngine anthropic opencv-python-headless
pip install paddleocr paddlepaddle
python main.py
```

### RealSR (optionnel — super-résolution ×4)

Pour améliorer la qualité OCR sur les images basse résolution :

1. Télécharger [RealSR-NCNN-Vulkan](https://github.com/nihui/realsr-ncnn-vulkan/releases)
2. Extraire dans `tools/realsr-ncnn-vulkan-20220728-windows/`
3. L'application le détecte automatiquement

Nécessite un GPU compatible Vulkan (NVIDIA, AMD, Intel intégré).

## Fonctionnalités

### Deux modes de capture

| Mode | Usage | Pipeline |
|---|---|---|
| **Capturer** | Texte imprimé, articles | OCR → découpage phrases → analyse batch |
| **Bulles** | Bandes dessinées, mangas | Détection zones → OCR par bulle → analyse |

### Analyse grammaticale

- Chaque mot coloré par **catégorie** : nom, verbe, adjectif, adverbe, pronom, préposition, article, conjonction
- Fond coloré par **groupe syntaxique** : sujet, verbe, complément, relative
- Expressions idiomatiques soulignées en ondulé
- Panneau détail : définition, lemme, genre, conjugaison, prononciation

### Sessions et documents

- **Sessions** (SQLite) : sauvegarde des pages analysées avec navigation ◀ ▶
- **Documents** (`.anlz`) : archives portables contenant texte + images, réorganisables
- Les pages en mode BD sauvegardent l'image de fond pour une restauration fidèle

### Outils intégrés

- **WordReference** : navigateur intégré avec bloqueur de publicités (~80 domaines)
- **Références** : 17 fiches grammaticales interactives (verbes, pronoms, prépositions…)
- **Zoom** : Ctrl+molette dans la scène texte

## Raccourcis clavier

| Raccourci | Action |
|---|---|
| **Tab / Shift+Tab** | Naviguer entre les phrases |
| **Ctrl+O** | Ouvrir une image |
| **Ctrl+S** | Sauvegarder la page |
| **Ctrl+F** | Recherche dans WordReference |
| **Ctrl+molette** | Zoom |
| **F5** | Webcam |
| **F6** | Capture écran |
| **F7** | Coller (image ou texte) |
| **Clic** sur un mot | Définition dans le panneau détail |
| **Clic** sur la légende | Fiche de référence grammaticale |
| **Bx** (mode BD) | Toggle texte analysé dans la bulle |

## Architecture

```
Analizador/
├── main.py                         # Point d'entrée
├── core/
│   ├── config.py                   # Couleurs, polices, labels
│   ├── db.py                       # SQLite : sessions, pages, images
│   ├── document.py                 # Archives .anlz
│   ├── event_bus.py                # Signaux Qt (singleton)
│   ├── modeles.py                  # PhraseAnalysee, MotAnalyse, Expression
│   ├── paths.py                    # Chemins applicatifs
│   ├── sanitizer.py                # Nettoyage texte OCR
│   └── settings.py                 # Clé API, préférences
├── ui/
│   ├── ad_blocker.py               # Bloqueur publicités QWebEngine
│   ├── capture_widget.py           # Webcam, écran, presse-papier
│   ├── dialogue_documents.py       # Gestionnaire documents .anlz
│   ├── dialogue_sessions.py        # Gestionnaire sessions
│   ├── fenetre_principale.py       # Fenêtre principale
│   ├── panneau_detail.py           # Définitions, traduction
│   ├── panneau_references.py       # Fiches grammaticales
│   └── scene_texte.py              # QGraphicsScene (texte + BD)
├── workers/
│   ├── analyse_worker.py           # Claude API : OCR + analyse
│   └── bbox_worker.py              # Pipeline BD : RealSR → Paddle → Claude
├── models/                         # Modèle PaddleOCR (détection)
├── tools/                          # RealSR-NCNN-Vulkan (optionnel)
├── references/                     # Fiches JSON grammaticales
├── sessions/                       # Base SQLite
├── Analizador.spec                 # PyInstaller OneFile
└── Analizador_setup.iss            # Inno Setup (installeur Windows)
```

## Pipeline technique

### Mode texte

```
Image → RealSR ×4 → Claude Vision OCR → texte → découpage phrases
→ analyse grammaticale batch (3 phrases en parallèle) → rendu coloré
```

### Mode BD

```
Image native → PaddleOCR PP-OCRv5 (détection zones texte)
→ clustering union-find (chevauchement bbox avec marge)
→ enveloppe convexe des segments → crops masqués depuis image ×4
→ Claude Vision OCR par bulle → analyse grammaticale → affichage overlay
```

## Format document .anlz

Archive ZIP :

```
manifest.json           # Métadonnées, liste des pages
pages/
    001.json            # Analyse grammaticale
    001.png             # Image (mode BD, optionnel)
    002.json
```

## Build et distribution

### PyInstaller (exécutable)

```bash
pyinstaller Analizador.spec
```

Produit `dist/Analizador_1.0.exe` + dossiers `references/`, `sessions/`, `tools/`.

### Inno Setup (installeur)

```bash
iscc Analizador_setup.iss
```

Produit `installer/Analizador_1.0_setup.exe` — installeur Windows avec raccourci bureau,
menu Démarrer, et désinstallation propre.

### Publier une release GitHub

1. Tagger la version : `git tag v1.0 && git push --tags`
2. Créer une release sur GitHub depuis le tag
3. Joindre `Analizador_1.0_setup.exe` comme asset
4. Les utilisateurs téléchargent l'installeur depuis la page Releases

## Configuration

La clé API est stockée dans `~/.config/analizador/config.json` (jamais commitée).
Le modèle PaddleOCR est téléchargé automatiquement au premier lancement (~50 Mo)
ou peut être pré-installé dans `models/PP-OCRv5_server_det_infer/`.

## Licence

MIT