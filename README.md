# KRAPO Scanner V1

Scanner **en lecture seule** pour les marchés Polymarket. Il récupère les marchés publics via Gamma, lit les meilleurs asks YES/NO dans les carnets CLOB, signale les cas où leur coût combiné est inférieur à 1 $, publie un tableau de bord statique et envoie des alertes Telegram.

> Ce signal est un **candidat brut**, pas un arbitrage garanti. Les frais ne sont pas déduits dans cette V1. Il faut vérifier la profondeur, la résolution, les frais du marché et les contraintes légales avant toute conclusion. Le programme ne place aucun ordre.

## Fonctionnement

- Scan automatique toutes les 30 minutes avec GitHub Actions.
- Tableau de bord statique dans `docs/`, publié avec GitHub Pages.
- Telegram facultatif : si les deux secrets sont absents, le scan continue sans alerte.
- Les données du tableau de bord sont publiées dans `docs/data/latest.json`.
- Les alertes déjà envoyées sont mémorisées dans `docs/data/state.json`.

## Installation

### 1. Créer le dépôt GitHub

1. Connecte-toi à GitHub et crée un nouveau dépôt nommé `krapo-scanner`.
2. Mets-le en **Public** pour utiliser gratuitement les runners GitHub Actions standards et GitHub Pages.
3. Téléverse le contenu de cette archive en conservant les dossiers `.github/` et `docs/`.
4. Dans le dépôt, ouvre **Settings → Actions → General** et vérifie que les actions sont autorisées.
5. Dans **Settings → Pages**, choisis **Deploy from a branch**, branche `main`, dossier `/docs`, puis Save.

### 2. Créer le bot Telegram

1. Dans Telegram, ouvre `@BotFather`.
2. Envoie `/newbot`, suis les étapes et copie le token fourni.
3. Ouvre ton nouveau bot et appuie sur **Démarrer**.
4. Pour obtenir ton identifiant de chat, ouvre dans ton navigateur :
   `https://api.telegram.org/botTON_TOKEN/getUpdates`
5. Repère `message` puis `chat` puis `id`. C'est ton `TELEGRAM_CHAT_ID`.
6. Ne partage jamais le token. Si tu l'exposes, régénère-le avec BotFather.

### 3. Ajouter les secrets GitHub

Dans ton dépôt : **Settings → Secrets and variables → Actions → New repository secret**.

Ajoute :
- `TELEGRAM_BOT_TOKEN` = token donné par BotFather
- `TELEGRAM_CHAT_ID` = identifiant de chat récupéré à l'étape précédente

Sans Telegram, tu peux laisser ces secrets absents : le tableau de bord fonctionnera quand même.

### 4. Activer et tester

1. Ouvre l'onglet **Actions**.
2. Sélectionne **KRAPO market scan**.
3. Clique **Run workflow** pour lancer un premier scan immédiatement.
4. Attends la fin du job, puis ouvre **Settings → Pages** pour récupérer l'adresse du tableau de bord.
5. Les scans suivants sont programmés toutes les 30 minutes.

## Réglages

Dans `.github/workflows/scan.yml` :
- `MARKET_LIMIT`: nombre de marchés Gamma examinés (défaut 120).
- `MIN_LIQUIDITY`: liquidité minimale en dollars (défaut 100).
- `GROSS_EDGE_MIN`: écart brut minimum (défaut 0.01 = 1 point de pourcentage).

Le scanner ne prend que les marchés binaires dont les issues sont explicitement nommées `Yes` et `No`. Il lit le meilleur ask de chaque token et compare leur somme à 1 $. La taille affichée est le minimum des deux tailles au meilleur niveau, pas la profondeur totale.

## Limites connues de la V1

- Pas encore de moteur d'implications logiques entre marchés différents.
- Pas de déduction automatique de l'exhaustivité d'un groupe de contrats.
- Pas de calcul exact des frais par marché : les candidats sont donc bruts.
- Le carnet peut changer entre lecture et exécution.
- Les alertes ne sont pas des recommandations de mise.
- GitHub Actions peut retarder les tâches planifiées ; le cron n'est pas une garantie à la minute près.
- Un dépôt public rend le code et les données du tableau de bord publics. Les secrets GitHub restent masqués, mais ne publie jamais de token dans les fichiers.

## Sources techniques

- Gamma API : https://gamma-api.polymarket.com
- CLOB API : https://clob.polymarket.com
- Documentation Gamma : https://gamma-api.polymarket.com/docs
- Telegram Bot API : https://core.telegram.org/bots/api
- GitHub Actions schedule : https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule
