# Dérushage — prototype local

Formulaire Python, moteur FFmpeg et aperçu interactif React/Remotion. n8n reçoit
les métadonnées, valide l'ordre et les réglages, puis conserve les bilans.
Les rushs, caches et exports restent sur le PC et hors de Git.

## Installation

Prérequis : Python 3.11 ou ultérieur, Node.js 22 ou ultérieur avec npm,
FFmpeg/FFprobe avec libx264 et AAC, et un workflow n8n publié.
Les versions des dépendances de l'éditeur sont verrouillées dans package-lock.json.

Depuis `1-Derushage` :

```powershell
py -3 -m venv .venv
Copy-Item config.example.json config.json
cd editor
npm ci
npm run check
npm run build
cd ..
```

Installer FFmpeg/FFprobe dans PATH ou placer les exécutables dans `bin/`.
Autre option : définir `FFMPEG_PATH` et `FFPROBE_PATH` vers les exécutables.
Renseigner dans `config.json` le dossier vidéo, les racines autorisées,
le webhook **Production URL** et l'URL du workflow de la même instance HTTPS.
Une URL `/assistant/`, `/mcp-server/http` ou `/webhook-test/` ne convient pas.
La configuration réelle est ignorée par Git ; ne pas la coller dans une PR.

```powershell
.venv\Scripts\python.exe app.py --open-browser
```

Le lanceur `Lancer le derushage.cmd` fait la même chose. Le moteur écoute uniquement
sur `http://127.0.0.1:8765`. Utiliser **Fermer le moteur local** avant de le relancer
après un changement de code : fermer l'onglet ne ferme pas le processus Python.
Les caches sont dans `.work/`, les projets dans `projets/` à côté du code.

## Utilisation

1. Choisir un dossier puis sélectionner les vidéos. L'ordre initial est
   lexicographique sans distinction de casse : C1, C10, C2.
2. Choisir l'assemblage intégral ou le raccourcissement des pauses.
3. Préparer les coupes et ouvrir l'éditeur : accepter, restaurer ou ajuster
   chaque pause, modifier les bornes et l'ordre des extraits.
4. Enregistrer la version, valider la relecture puis exporter l'aperçu ou
   la pleine résolution. Une modification invalide l'approbation précédente.

Réglages initiaux : pause minimale 0,8 s, respiration conservée 0,3 s,
seuil sonore -35 dB. La respiration doit être plus courte que la pause minimale.
Les originaux restent intacts. Vérifier les mots faibles et les raccords à l'écoute.

## Limites et statut

Import du prototype existant, avec adaptation des chemins et de la configuration.
Les tests locaux du moteur, des décisions et du rendu synthétique sont disponibles.
Le modèle n8n doit être configuré sur chaque instance ; cet import ne prouve pas
que son webhook réel est publié ni accessible. Le contrôle audio par l'utilisateur
reste nécessaire. Un moteur local à la fois ; 100 fichiers, une heure et 500 segments.

La détection repose sur le volume sonore ; elle ne comprend pas les phrases.
L'export réencode en H.264 8 bits 4:2:0 et AAC ; conserver les originaux pour
l'étalonnage. Le HDR est refusé. Les entrées doivent contenir vidéo et audio.
Remotion et les autres dépendances restent soumis à leurs propres licences.

## Vérifications

Depuis la racine du dépôt :

```powershell
py -3 -m unittest discover -s 1-Derushage/tests -p "test_*.py" -v
node 1-Derushage/tests/check_n8n_logic.cjs
npm --prefix 1-Derushage/editor ci
npm --prefix 1-Derushage/editor run check
npm --prefix 1-Derushage/editor run build
```

Les tests de rendu génèrent leurs petits médias rouge/bleu localement.
Ils sont ignorés si FFmpeg/FFprobe manquent ; la CI les installe pour les exécuter.
Le test de tri n8n s'exécute sans réseau. Aucun test n'envoie de vidéo à n8n.
