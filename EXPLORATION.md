# GreenAlp Data Collector — exploration technique

État au 25 novembre 2026. Le titulaire du compte a confirmé que le script Python de connexion et d'export HTTP fonctionne sur son compte. L'exécution autonome sur Linux reste à valider.

## Sources publiques

- GreenAlp décrit un accès par identifiant et mot de passe. Les CGU indiquent aussi qu'une acceptation est demandée à la première connexion et lors des mises à jour des conditions. Le protocole de connexion, la présence éventuelle d'un second facteur et la durée de session restent à observer. [CGU Ma Conso GreenAlp](https://maconso.greenalp.fr/condition-generale-d%27utilisation)
- Les CGU annoncent une consultation journalière et mensuelle avec une actualisation en J−1, ainsi qu'un export des index journaliers des compteurs enregistrés. Le format CSV signalé par l'utilisateur, son schéma et l'unité effective des colonnes restent à vérifier sur un export. Un index peut représenter un cumul du compteur. Il faudra vérifier sa signification avant d'en déduire une consommation par période. [CGU Ma Conso GreenAlp](https://maconso.greenalp.fr/condition-generale-d%27utilisation)
- La page d'accueil publique consultée affiche un écran de chargement du profil. Les échanges qui alimentent le graphique et le téléchargement restent inconnus. Aucune documentation d'API publique pour les relevés d'un compte particulier n'a été trouvée dans les sources consultées. GreenAlp publie également un catalogue Open Data avec ses propres API. [Portail Ma Conso](https://maconso.greenalp.fr/) · [Présentation de l'Open Data](https://greenalp.fr/open-data-greenalp-acteur-de-la-demarche-de-mutualisation-des-donnees-energetiques-des)
- Le périmètre supposé est `maconso.greenalp.fr`. GreenAlp renvoie également vers Métroénergies selon la commune. Le domaine réellement utilisé par le compte déterminera le portail à étudier. [Compteurs communicants GreenAlp](https://greenalp.fr/les-compteurs-communicants-electricite)

## Export observé dans le HAR

Le HAR fourni contient un seul échange. Le portail `https://maconso.greenalp.fr` appelle `GET https://admin.maconso.greenalp.fr/api/v1/consumption/export`. La requête enregistrée ne contient ni paramètres d'URL ni corps. Le serveur répond `200` avec `Content-Type: text/csv; charset=utf-8` et `Content-Disposition: attachment`. Le corps capturé se lit comme un CSV séparé par des points-virgules, avec trois champs par ligne. La signification des colonnes et la portée de l'export restent à établir. Le téléchargement observé provient donc d'une réponse HTTP du serveur.

La capture ne contient aucune valeur de cookie ni d'en-tête `Authorization`. Selon le mode d'export du HAR, les en-têtes sensibles peuvent être retirés. La capture seule ne permet pas de déterminer le mécanisme d'authentification ou de conclure à un accès anonyme. Elle ne couvre ni la connexion ni le chargement du graphique.

Pour lever l'incertitude côté session, ouvrir la requête d'export dans l'onglet Réseau en étant connecté et vérifier sur place la présence de `Authorization` ou de `Cookie`. Indiquer seulement le type observé, par exemple `Bearer` ou cookie. Relever également les métadonnées expurgées de la connexion dans une session neuve. Ces observations orienteront l'essai HTTP sur le compte du titulaire.

## Connexion et API observées dans le HAR complet

Les routes ci-dessous sont sur `https://admin.maconso.greenalp.fr`. Tous ces échanges ont renvoyé `200` dans la capture.

| Requête | Observation |
| --- | --- |
| `POST /api/v1/auth/login` | Corps JSON avec `username` et `password`. Réponse JSON avec `account`, `token` au format apparent JWT et `refresh_token` sous forme de chaîne. |
| `GET /api/v1/user/me` | Réponse JSON avec une clé `user`. |
| `GET /api/v1/meter` | Liste JSON de compteurs. |
| `GET /api/v1/consumption/monthly` | Paramètre `start` au format ISO 8601 UTC avec millisecondes. Réponse JSON indexée par une clé numérique dans les deux appels capturés. L'unité et le sens de cette clé restent à vérifier. |
| `GET /api/v1/consumption/export` | Téléchargement CSV confirmé par une seconde capture. |

La connexion observée renvoie les deux jetons après un seul POST. La vérification dans le panneau Réseau par le titulaire du compte confirme `Authorization: Bearer` sur l'export, sans en-tête `Cookie`. Le HAR ne montre aucun appel de renouvellement.

Depuis le dossier du projet, lancer `python3 probe_export.py` dans un terminal. Le script demande les identifiants, masque la saisie du mot de passe, ouvre une session neuve et utilise le champ `token` comme Bearer pour l'export. Il vérifie la structure du CSV et affiche uniquement le nombre de lignes de données. Le titulaire a confirmé le succès du test réel. La comparaison détaillée des valeurs avec l'export manuel, le démarrage sans saisie depuis Linux et la reconnexion après expiration restent à vérifier.

Le HAR complet contient le mot de passe envoyé et les jetons reçus. Le traiter comme un fichier contenant des secrets et le garder hors du dépôt. Si le fichier a été partagé au-delà d'un périmètre de confiance, changer le mot de passe et révoquer les sessions si le portail le permet.

## Relevé dans le navigateur

1. Dans une fenêtre privée, ouvrir le portail habituel. Dans les outils de développement, ouvrir **Réseau**, activer **Conserver le journal**, puis se connecter normalement. Relever la méthode, le domaine, le chemin et le statut des étapes pertinentes, y compris les redirections. Indiquer si un code, un CAPTCHA ou une validation manuelle est demandé. Pour la session, noter uniquement si un cookie ou un en-tête `Authorization` apparaît, sans sa valeur.
2. Effacer le journal réseau. Dans **Mon suivi conso**, choisir l'électricité et changer la période une fois. Chercher dans **Fetch/XHR** les échanges déclenchés. Relever la méthode, le domaine, le chemin, le statut, le `Content-Type` et, si identifiables, les noms des champs de période et de granularité. Remplacer les identifiants présents dans les chemins par `{compteur}` ou `{id}`.
3. Effacer le journal puis cliquer sur **Exporter**. Examiner cette fois **Toutes** les requêtes. Relever les mêmes métadonnées et la présence éventuelle de `Content-Disposition`. Si le téléchargement démarre sans nouvelle requête observable ou utilise une URL `blob:`, noter le comportement. Cela peut indiquer une génération du fichier dans le navigateur à partir des données déjà chargées. Ouvrir l'export localement et relever les en-têtes de colonnes, le séparateur et les unités visibles.

Partager uniquement ce relevé expurgé. Garder hors du dépôt et de la conversation les identifiants, mots de passe, valeurs de cookies et de tokens, références de compteur, liens signés, HAR, commandes « Copier en tant que cURL » et exports réels. Pour un essai Python local, saisir le mot de passe à l'invite ou le fournir via un gestionnaire de secrets. Conserver la session en mémoire si possible et exclure les valeurs sensibles des journaux.

## Critères de validation

1. Reproduire en Python le parcours de connexion normal dans une session neuve, puis récupérer pour un seul compteur une courte période déjà consultée dans le portail. Comparer les dates, unités et valeurs avec l'affichage ou l'export obtenu manuellement.
2. Si le CSV est produit dans le navigateur, vérifier d'abord si la réponse qui alimente le graphique ou l'export contient toutes les données requises. Un accès HTTP à cette réponse pourrait suffire.
3. Vérifier le renouvellement après expiration, puis refaire l'essai depuis Linux sans navigateur. Une session importée du navigateur peut confirmer un accès ponctuel. L'autonomie exige un démarrage à froid et une reconnexion sans intervention. Relever les éventuelles validations manuelles et l'effet d'un changement de CGU. Les routes internes observées peuvent évoluer avec le portail.
4. Évaluer Playwright si le parcours normal ou la récupération dépend réellement de l'exécution du navigateur. Une étape interactive obligatoire demeure une contrainte d'autonomie à documenter.

## Contrat d’import vérifié sur l’export réel

L’export UTF-8 est séparé par des points-virgules. La première colonne est `Date` au format ISO `AAAA-MM-JJ`. Dans l’échantillon électrique, le même libellé de compteur préfixe deux colonnes `Consommation (kWh)` et `Index (kWh)`. Sur 68 paires de dates consécutives, l’index du lendemain moins celui du jour donne exactement la consommation du jour. L’intégration importe la colonne de consommation telle quelle en kWh et utilise chaque date comme jour civil Europe/Paris. Une ligne datée peut avoir un index et une consommation vide. Une cellule vide est donc traitée comme une donnée manquante, sans déduction à partir de l’index.

Le contrat a été vérifié sur un compteur électrique. Le parseur prend en charge plusieurs paires de colonnes électriques dans le même format. La stabilité du premier élément du libellé et le format d’un vrai compte multicompteur restent à confirmer. La date de fin de disponibilité et les totaux de période sont calculés côté intégration. L’export réel et les captures restent hors du dépôt.
