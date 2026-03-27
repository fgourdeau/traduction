# -*- mode: python ; coding: utf-8 -*-
import os
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    # On retire 'references' et 'sessions' de datas ici car on ne veut
    # PAS qu'ils soient encapsulés dans le binaire immuable.
    datas=[('models', 'models')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
    optimize=0,
    excludes=[
        'tkinter',
        'matplotlib',
        'tensorflow',
        'tensorboard',
        'torch',
        'torchvision',
        'torchaudio',
        'pandas',
        'modelscope',
        'baidubce',
        ]
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries, # On déplace les binaires ici pour le mode onefile
    a.zipfiles, # On ajoute les zipfiles ici
    a.datas,    # On ajoute les datas système ici
    name='Analizador',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['analizador.ico'],

)
# On supprime la section COLLECT car elle force la création d'un dossier

import shutil
import os

# Chemin de destination (le dossier dist)
dist_path = os.path.join(os.getcwd(), 'dist')

# Liste des dossiers à copier à l'extérieur
dossiers_externes = ['references', 'sessions','tools']

for d in dossiers_externes:
    source = os.path.join(os.getcwd(), d)
    destination = os.path.join(dist_path, d)

    # On copie seulement si le dossier source existe et
    # n'est pas déjà dans la destination
    if os.path.exists(source):
        if os.path.exists(destination):
            shutil.rmtree(destination)
        shutil.copytree(source, destination)
        print(f"--- Dossier {d} copié dans dist/ ---")