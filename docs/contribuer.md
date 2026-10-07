# Travailler sur Automatisation_Video

Une tâche précise correspond à une branche courte et une PR. `main` contient
les versions relues et intégrées. Conserver les commits historiques existants.

```powershell
git switch main
git pull --ff-only
git switch -c fix/description-courte
# modifier puis vérifier
git diff
git add chemin/du/fichier
git commit -m "fix: expliquer le comportement corrigé"
git push -u origin fix/description-courte
```

Ouvrir une PR, lire le diff et les résultats des tests, puis demander la revue
humaine avant fusion. Pour conserver les commits logiques et la frontière de
la contribution, choisir **Create a merge commit** sur GitHub.
Après fusion : revenir sur main et faire `git pull --ff-only`.

Pour plusieurs tâches simultanées, utiliser des worktrees distincts avec des
périmètres de fichiers différents. Commencer avec deux agents au maximum.
Un agent ne lance pas d'autres agents sans demande explicite. Les contrats
communs évoluent dans une PR préalable si d'autres tâches en dépendent.

Pour annuler une modification déjà partagée, créer une branche et utiliser
`git revert <commit>`, puis une PR. Pour annuler une PR fusionnée par merge
commit, `git revert -m 1 <commit-de-fusion>` annule la contribution entière.
Ne pas réécrire main ni utiliser de force-push pour effacer un problème.

La migration initiale conserve la provenance du prototype dans sa PR ; elle ne
reconstitue pas de faux commits anciens. Ses trois commits introduisent le
code portable, les tests, puis la documentation et les règles de collaboration.

Les paramètres réels, médias, exports, binaires et node_modules ne sont pas
versionnés. Les décisions d'édition et leurs sauvegardes restent dans les
dossiers de projets locaux ; Git conserve le code qui les manipule.
