# Installer arrstack-mcp (fork) dans le Docker MCP Toolkit

Deux serveurs MCP, définis dans ce dossier, s'ajoutent au profil `all` :

| Serveur | Fichier | Services |
|---|---|---|
| `arrstack` | `arrstack.yaml` | Sonarr, Radarr, Prowlarr, Bazarr, qBittorrent, Gluetun, Profilarr, cross-seed, Jellyfin, Seerr, Jellystat, Wizarr, Dispatcharr |
| `arrstack-4k` | `arrstack-4k.yaml` | Sonarr-4K, Radarr-4K, Bazarr-4K |

Les deux utilisent la même image `ghcr.io/jefedi/arrstack-mcp:latest`, lancée en `--transport stdio`.
Les URLs sont préremplies avec les adresses de la stack (10.10.10.15 / 10.10.10.16). Les clés API, c'est **toi** qui les saisis : elles ne sont ni dans le code ni dans les fichiers YAML.
Les outils de suppression sont **masqués par défaut** (`allow_destructive=false`).

---

## Étape 1 — Vérifier que les conteneurs Docker atteignent les VM

Depuis PowerShell sur jTower :

```powershell
docker run --rm curlimages/curl:8.17.0 -s -o /dev/null -w "%{http_code}\n" http://10.10.10.15:8989/ping
docker run --rm curlimages/curl:8.17.0 -s -o /dev/null -w "%{http_code}\n" http://10.10.10.16:8096/System/Ping
```

* `200` sur les deux → passe à l'étape 2.
* Timeout → le réseau 10.10.10.0/24 n'est pas routé jusqu'à jTower. La solution standard est un *subnet router* Tailscale sur l'hôte Proxmox (doc : https://tailscale.com/kb/1019/subnets) :
  1. Shell de l'hôte Proxmox : activer le forwarding IP (section « Enable IP forwarding » de la doc), puis `tailscale set --advertise-routes=10.10.10.0/24`.
  2. Console admin Tailscale → machine de l'hôte → **Edit route settings** → coche `10.10.10.0/24`.
  3. Sur jTower, le client Tailscale Windows accepte les routes par défaut ; relance le test.

## Étape 2 — Points à vérifier sur la stack

* **qBittorrent** (derrière Gluetun) : le port WebUI doit être publié par le conteneur `gluetun` (publié en `8090` sur l’hôte). Si le port est différent, change `qbittorrent_url` à l'étape 4.
  qBittorrent refuse les requêtes dont l'en-tête Host n'est pas dans *Options → Web UI → Server domains* (champ `WebUI\ServerDomains`). Ajoute `10.10.10.15` à ce champ, ou garde `*`.
* **Gluetun** : le serveur de contrôle (port `8000`) doit aussi être publié par `gluetun`. Il faut aussi un rôle `apikey` dans `/gluetun/auth/config.toml` (doc : https://github.com/qdm12/gluetun-wiki/blob/main/setup/advanced/control-server.md). Si tu ne veux pas exposer Gluetun, retire `gluetun` de `enabled_services`.
* Ports par défaut supposés : Prowlarr 9696, Seerr 5055, Jellyfin 8096, Jellystat 3500, Wizarr 5690, Dispatcharr 9191, Profilarr 6868, cross-seed 2468. Corrige à l'étape 4 ceux qui diffèrent.

## Étape 3 — Ajouter les serveurs au profil `all`

Récupère ce dossier `docker-mcp/` sur jTower (clone du fork), puis :

```powershell
# Le fichier doit être dans le dossier des catalogues Docker MCP, sinon :
# "local file path must resolve within Docker MCP catalogs directory"
Copy-Item <chemin>\arrstack-mcp\docker-mcp\arrstack*.yaml $HOME\.docker\mcp\catalogs\
cd $HOME\.docker\mcp\catalogs
docker mcp profile server add all --server file://./arrstack.yaml --server file://./arrstack-4k.yaml
docker mcp profile server ls
```

L'image est publiée par GitHub Actions (workflow *Publish Docker image*) au premier push sur `main`. Si ce n'est pas encore fait, construis-la en local depuis la racine du repo : `docker build -t ghcr.io/jefedi/arrstack-mcp:latest .`

## Étape 4 — (Optionnel) Changer une URL ou un réglage

```powershell
docker mcp profile config all --set arrstack.qbittorrent_url=http://10.10.10.15:8080
docker mcp profile config all --set arrstack.enabled_services=sonarr,radarr,seerr
docker mcp profile config all --set arrstack.allow_destructive=true
docker mcp profile config all --get-all
```

## Étape 5 — Saisir les clés API (c'est toi qui les entres)

⚠️ Ce sont des identifiants. Saisis-les toi-même et ne les colle pas dans une conversation.

Nom du secret = `<serveur>.<nom>`. Pour éviter que la clé reste dans l'historique PowerShell, passe-la par l'entrée standard :

```powershell
Read-Host "Clé Sonarr" | docker mcp secret set arrstack.sonarr_api_key
```

| Secret | Où trouver la valeur |
|---|---|
| `arrstack.sonarr_api_key` / `arrstack-4k.sonarr_api_key` | Sonarr → Settings → General → API Key |
| `arrstack.radarr_api_key` / `arrstack-4k.radarr_api_key` | Radarr → Settings → General → API Key |
| `arrstack.prowlarr_api_key` | Prowlarr → Settings → General → API Key |
| `arrstack.bazarr_api_key` / `arrstack-4k.bazarr_api_key` | Bazarr → Settings → General → Security → API Key |
| `arrstack.qbt_user`, `arrstack.qbt_pass` | Identifiants WebUI qBittorrent |
| `arrstack.gluetun_api_key` | La clé que tu choisis pour le rôle `apikey` de Gluetun |
| `arrstack.profilarr_api_key` | Variable `PROFILARR_API_KEY` du conteneur, ou Settings → Security → API keys |
| `arrstack.crossseed_api_key` | `docker exec cross-seed cross-seed api-key` |
| `arrstack.jellyfin_api_key` | Jellyfin → Tableau de bord → Clés API → `+` |
| `arrstack.seerr_api_key` | Seerr → Settings → General → API Key |
| `arrstack.jellystat_api_key` | Jellystat → Settings → API Keys |
| `arrstack.wizarr_api_key` | Wizarr → Settings → General → API Keys |
| `arrstack.dispatcharr_api_key` | Dispatcharr → menu utilisateur (admin) → API key |

Un secret non saisi est transmis à la place de la clé comme `<UNKNOWN>` par la passerelle : le service répond alors `401`. Saisis toutes les clés, ou retire le service de `enabled_services`.

Vérification : `docker mcp secret ls`

## Étape 6 — Tester

```powershell
docker mcp gateway run --profile all
```

Redémarre Claude Desktop. Dans une conversation, demande par exemple « santé de Sonarr et Sonarr-4K ». Les outils `sonarr_health` des deux serveurs doivent répondre.

## Garde-fous intégrés

* Les suppressions (`*_delete_*`) sont masquées tant que `allow_destructive` n'est pas à `true`. Même activées, `sonarr_delete_series` et `radarr_delete_movie` refusent un média qui porte un tag contenant `keep` (`mediacleaner-keep` / `mediacleaner_keep`).
* Aucun outil ne démarre de torrent en masse : les outils qBittorrent refusent `all`.
* `crossseed_run_job inject`, `gluetun_restart_vpn` et `wizarr_delete_user` disent dans leur description de demander confirmation avant de lancer.
