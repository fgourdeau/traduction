# Analizador — Analyse grammaticale espagnole

Application PySide6 desktop pour l'apprentissage de l'espagnol.
Capture une image (webcam, écran ou fichier), puis envoie directement
à Claude Vision qui fait l'OCR et l'analyse grammaticale en un seul appel.

## Architecture

```
espagnol-app/
├── main.py                  # Point d'entrée
├── core/
│   ├── __init__.py
│   ├── event_bus.py         # Communication inter-composants (signaux Qt)
│   ├── modeles.py           # Dataclasses : Phrase, Mot, Expression
│   └── config.py            # Couleurs par catégorie, polices, labels
├── workers/
│   ├── __init__.py
│   └── analyse_worker.py    # Claude Vision : OCR + analyse (QThread éphémère)
├── ui/
│   ├── __init__.py
│   ├── fenetre_principale.py
│   ├── scene_texte.py       # QGraphicsScene — mots colorés, soulignés, navigation
│   ├── panneau_detail.py    # Panneau latéral — définitions, expressions, traduction
│   └── capture_widget.py    # Webcam / capture écran
└── README.md
```

## Pipeline

```
image_capturee → analyse_lancee(image) → Claude Vision → analyse_terminee → rendu scène
```

Un seul appel API : Claude lit l'image, extrait le texte ET l'analyse grammaticalement.

## Dépendances

```bash
pip install PySide6 anthropic opencv-python-headless
```

## Variables d'environnement

```bash
export ANTHROPIC_API_KEY="sk-..."
```

## Lancement

```bash
python main.py
```

## Interactions

| Action              | Effet                                      |
|---------------------|--------------------------------------------|
| Clic sur mot        | Affiche définition, genre, conjugaison     |
| Clic sur souligné   | Affiche sens de l'expression               |
| Clic droit (n'importe où) | Affiche traduction de la phrase     |
| Tab                 | Phrase suivante                             |
| Shift+Tab           | Phrase précédente                           |
| Ctrl+O              | Ouvrir une image depuis un fichier          |
| F5                  | Webcam                                      |
| F6                  | Capture écran                               |
