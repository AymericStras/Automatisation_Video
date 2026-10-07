# Installer le workflow de dérushage

`workflow-template.json` est un modèle d'import désactivé. Il ne contient
aucune adresse de production, clé, donnée épinglée ni identifiant de table réel.

1. Importer le JSON dans n8n.
2. Créer une table `Derushage - journal` : champs texte `entry_key`, `job_id`,
   `event`, `status`, `raw_request`, `response_json` et champs numériques
   `files_count`, `input_seconds`, `output_seconds`.
3. Sélectionner cette table dans **Conserver la demande et le bilan**.
4. Remplacer le chemin `derushage-REMPLACER` du Webhook par un chemin propre
   à l'installation, puis publier le workflow.
5. Copier sa Production URL dans `config.json` local (`n8n_webhook`) et
   l'adresse de l'éditeur du workflow dans `workflow_url`.

Contrat : version 1, `action=plan` pour recevoir les fichiers et paramètres,
`action=report` pour enregistrer le bilan. `validation.js` est identique au Code
node du JSON ; toute modification doit mettre à jour les deux. Le plan renvoie
`ordered_names`, `parameters`, `input_seconds`, `requires_human_review=true`.
Les événements de bilan du même projet remplacent la ligne `job_id:report`.

Le webhook est sans authentification dans ce prototype et son adresse réelle
doit rester locale. Il transporte uniquement noms, métadonnées et bilans ; il
n'accède pas au disque. Tester le workflow publié avant un premier vrai projet.
