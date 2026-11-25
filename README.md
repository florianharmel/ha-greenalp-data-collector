# GreenAlp Data Collector

Intégration personnalisée pour Home Assistant Core **2026.11.3**. Elle importe dans Recorder les consommations électriques journalières disponibles sur Ma Conso GreenAlp et expose des capteurs pour les tableaux de bord et les automatisations.

## Installation

- **HACS** `→` **Dépôts personnalisés**. Ajouter l’URL GitHub du dépôt publié, catégorie **Intégration**, puis télécharger **GreenAlp Data Collector** et redémarrer Home Assistant.
- **Installation locale**. Copier le dossier `custom_components/greenalp` dans `config/custom_components`, puis redémarrer Home Assistant.
- Dans **Paramètres → Appareils et services → Ajouter une intégration**, sélectionner **GreenAlp Data Collector** et saisir les identifiants Ma Conso. À la première collecte, l’intégration importe tout l’historique disponible dans l’export.
- Dans les paramètres du tableau de bord **Énergie**, ajouter la statistique externe **GreenAlp Électricité …** correspondante sous **Consommation du réseau**. Sélectionner chaque compteur souhaité une seule fois. Vérifier que le fuseau Home Assistant est `Europe/Paris` si l’on souhaite retrouver les mêmes bornes des journées que dans Ma Conso.

## Utilisation

La fréquence se change dans les options de l’intégration, de 1 à 168 heures, avec 6 heures par défaut. Chaque synchronisation télécharge l’export disponible, dont la route ne propose aucun filtre de date observé. La mise à jour porte sur les sept derniers jours terminés, étendus en cas de retard de collecte.

**Synchroniser** déclenche une mise à jour ordinaire. **Resynchroniser l’historique** réimporte toutes les dates disponibles et recalcule les cumuls affectés. Les données précédemment importées restent disponibles lorsque l’export est réduit, qu’un relevé devient vide ou que la connexion échoue. Les boutons et le déclenchement automatique partagent les mêmes limites de concurrence. En cas d’erreur réseau, les tentatives sont espacées avec un délai de 1 minute, 2 minutes, puis une augmentation exponentielle plafonnée à 64 minutes ou à l’intervalle configuré s’il est plus court. Une authentification rejetée ouvre le flux de réauthentification.

Les capteurs par compteur indiquent la veille, la semaine civile commençant le lundi et le mois en cours jusqu’à la veille. Une période incomplète est inconnue, avec un attribut `missing_days`. Une consommation mesurée de zéro vaut `0 kWh`. Les capteurs de diagnostic indiquent la dernière synchronisation réussie depuis le chargement, la fin du dernier jour disponible, son ancienneté en heures, le statut de connexion et la catégorie d’erreur. Des valeurs d’une collecte précédente peuvent rester visibles après une erreur.

Chaque valeur journalière est publiée à la dernière heure du jour local. Elle apparaît donc à cette heure dans une vue horaire. Le CSV est traité en mémoire. Le mot de passe est stocké par Home Assistant dans son entrée de configuration. Protéger le dossier de configuration et ses sauvegardes. Les jetons restent en mémoire et les diagnostics exposent uniquement des catégories d’erreur.

## Coûts électriques estimés

Ouvrir les **Options** de l’intégration pour saisir le prix fixe TTC en EUR/kWh, l’abonnement mensuel TTC facultatif (0 EUR par défaut) et la date d’effet locale. L’abonnement est appliqué **par compteur électrique** et réparti sur les jours calendaires de chaque mois. Les coûts commencent à la date d’effet du premier tarif. Laisser les champs de tarif vides permet de modifier uniquement la fréquence.

Pour changer de tarif, saisir le nouveau prix, l’abonnement applicable et la nouvelle date d’effet. Les tarifs sont conservés par date. Une nouvelle date passée, ou le remplacement d’un tarif passé, exige de cocher **Autoriser le recalcul des coûts passés**. La modification s’applique jusqu’au tarif suivant, s’il existe. Une resynchronisation applique à chaque jour son tarif historique. Elle recalcule les consommations corrigées et les cumuls associés sans créer de doublons.

Les quatre capteurs **Coût estimé** donnent le total de la veille, de la semaine civile, du mois et de l’année en cours jusqu’à la veille, pour les jours couverts par un tarif. Leurs attributs donnent le coût de consommation et d’abonnement séparément ainsi que le nombre de jours manquants. Si la consommation d’un jour manque et que son prix du kWh est positif, le capteur de total reste inconnu pour la période concernée. L’abonnement reste calculable. Les montants sont des estimations TTC. L’intégration ne récupère aucune facture.

Dans le tableau de bord **Énergie**, modifier la source **Consommation du réseau** GreenAlp, puis choisir la statistique qui suit les coûts totaux. Sélectionner **GreenAlp Coût estimé · Total …** avec le même suffixe de compteur que la série de consommation. Home Assistant associe les deux séries via `stat_cost`. Utiliser EUR comme devise de Home Assistant. La série cumulée affiche les charges connues, y compris l’abonnement les jours où le coût de consommation est encore inconnu. Les séries **Consommation** et **Abonnement** restent disponibles séparément dans Recorder. La série **Total** les agrège déjà.

## Mise à jour et désinstallation

Pour mettre à jour, télécharger la version dans HACS et redémarrer. Pour une installation manuelle, remplacer le dossier de l’intégration et redémarrer. Une mise à jour conserve les séries Recorder tant que les identifiants de compteur et de compte restent stables.

Pour désinstaller, retirer la série de la configuration Énergie, supprimer l’entrée GreenAlp dans **Appareils et services**, puis désinstaller le dépôt dans HACS ou retirer le dossier installé manuellement. Redémarrer Home Assistant. Recorder conserve l’historique. Pour l’effacer volontairement, utiliser **Outils de développement → Statistiques** et supprimer la série externe concernée.

## Développement local

Avec Docker Desktop ou Docker Engine lancé, exécuter `docker compose up -d` et ouvrir `http://127.0.0.1:18123`. Le conteneur utilise la version cible et la configuration isolée `.ha-test/`. Après une modification, exécuter `docker compose restart`. Pour arrêter l’environnement, exécuter `docker compose down`. La configuration locale est conservée et ignorée par Git.

Exécuter les tests Python indépendants avec `python3 -m unittest discover -s tests -v`. Le jeu de données est fictif. Ne jamais déposer de HAR, d’export personnel, d’identifiants ou de journaux dans le dépôt. Voir [le contrat de données](EXPLORATION.md).

Avant publication, renseigner l’URL du dépôt et du suivi des problèmes dans `custom_components/greenalp/manifest.json`, puis vérifier l’installation du dépôt personnalisé depuis HACS.

Pour tester le Config Flow et les réimports sur un vrai Recorder avec un répertoire
temporaire, lancer le test d’intégration dans la même image Docker.

```sh
docker compose run --rm --no-deps \
  -v ./custom_components:/integration:ro -v ./tests:/tests:ro \
  --entrypoint python homeassistant /tests/home_assistant_smoke.py
```
