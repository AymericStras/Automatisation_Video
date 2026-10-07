# Vérification du dérushage — 7 octobre 2026

Validation locale de la branche `feat/import-derushage` avec le workflow n8n publié.

## Résultats

- 17 tests Python réussis, sans test ignoré, dont les rendus FFmpeg et les contrôles de synchronisation audio/image.
- Test JavaScript du contrat n8n réussi : ordre lexicographique et rejet des doublons.
- Installation des dépendances verrouillées, vérification TypeScript et compilation de l'éditeur réussies.
- Test HTTP complet sur deux vidéos synthétiques, avec le vrai webhook n8n : préparation, tri, modification d'une coupe, sauvegarde de la révision 2, préparation des copies de lecture, validation et export.
- Export refusé avant validation de la révision ; requête n8n invalide rejetée.
- Exports aperçu et pleine résolution de 3,36 secondes décodés et vérifiés ; bilans synchronisés avec n8n. Ces deux vidéos sources de test sont en 160 x 90 : ce contrôle ne constitue pas un essai de rendu 4K.
- Lecture partielle HTTP du MP4 vérifiée (réponse 206), nécessaire à la navigation dans la vidéo.
- Préparation des huit rushs réels réussie : 33,12 secondes de sources, 15 coupes proposées, montage proposé de 16,76 secondes. Aucune validation humaine ni export final de ces rushs n'a été effectué par l'agent.

## Installation locale et limites

La configuration réelle, l'environnement Python, FFmpeg/FFprobe, les dépendances de l'éditeur, caches et projets sont locaux et ignorés par Git. Une autre installation doit suivre le README et fournir son propre webhook.

L'instance locale du dépôt utilise le port 8766 pour éviter la confusion avec l'ancien moteur sur 8765. Le lanceur lit ce port dans la configuration locale.

L'automatisation du navigateur était indisponible pendant cette vérification : les échanges HTTP, les conversions, l'éditeur compilé et les décisions de montage ont été contrôlés, mais pas l'affichage visuel ni l'écoute humaine des raccords.

Les essais n8n ont enregistré des projets de test dans le journal de l'instance. Les originaux ont seulement été lus. Les tests locaux ne constituent pas encore un résultat GitHub Actions : vérifier la CI de la pull request après publication.
