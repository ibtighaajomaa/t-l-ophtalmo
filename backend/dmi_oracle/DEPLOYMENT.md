# Déploiement de l'intégration Oracle DMI (VM sans accès PyPI)

Ce document explique comment récupérer et activer la connexion directe à la
base Oracle du DMI (app `dmi_oracle`) sur un VM qui a accès à GitHub mais
pas à Internet en général (pas de `pip install` depuis PyPI).

## Prérequis

- Ce VM peut faire `git pull` depuis GitHub (déjà utilisé pour synchroniser
  le code).
- Ce VM a un accès réseau vers la base Oracle du DMI (host/port/service à
  confirmer — sinon rien de ce qui suit ne pourra se connecter réellement).
- Docker + Docker Compose sont déjà installés et la stack tourne déjà (au
  moins une fois construite avec succès dans le passé), pour que le cache
  Docker existant reste valable.

## 1. Récupérer le code

```bash
cd /chemin/vers/t-l-ophtalmo
git fetch origin
git checkout dmi-api-test
git pull origin dmi-api-test
```

## 2. Reconstruire le backend

`requirements.txt` n'a **pas** changé (volontairement) : le paquet
`oracledb` n'y est plus listé, pour ne pas invalider le cache Docker de la
couche `pip install -r requirements.txt` — celle qui installerait Django,
torch, etc. depuis PyPI. À la place, `oracledb` est fourni en `.whl`
vendorisé dans `backend/vendor/` (déjà commité, correspond exactement à
l'image `python:3.11-slim` utilisée par `backend/Dockerfile`) et installé
par une couche Docker séparée, **sans réseau** :

```dockerfile
COPY vendor/oracledb-4.0.2-cp311-cp311-manylinux2014_x86_64....whl /tmp/
RUN pip install --no-cache-dir --no-index /tmp/oracledb-...whl
```

Donc le rebuild classique doit fonctionner sans Internet, à condition que
le cache Docker de la couche `pip install -r requirements.txt` soit déjà
présent sur ce VM (i.e. l'image a déjà été construite au moins une fois
avec ce même `requirements.txt`) :

```bash
docker compose build backend
docker compose up -d backend
docker compose exec backend python -c "import oracledb; print(oracledb.__version__)"
docker compose exec backend python manage.py check
```

Si le build échoue en tentant de joindre PyPI, c'est que le cache Docker
n'était pas présent pour cette couche (ex: premier build sur ce VM, ou
`requirements.txt` avait déjà changé pour une autre raison) — dans ce cas
il faut soit un accès PyPI ponctuel, soit transférer l'image déjà construite
depuis le VM de dev via `docker save` / `docker load` (dites-le moi, je
peux préparer ça).

## 3. Configurer la connexion Oracle réelle

Ajouter dans `backend/.env` (fichier non versionné, à créer/éditer sur ce
VM uniquement — ne jamais le committer) :

```
ORACLE_DMI_HOST=<host ou IP>
ORACLE_DMI_PORT=1521
ORACLE_DMI_SERVICE_NAME=<service_name>
ORACLE_DMI_USER=<user>
ORACLE_DMI_PASSWORD=<password>
```

Puis redémarrer :

```bash
docker compose up -d backend
```

Sans `ORACLE_DMI_HOST`, l'app `dmi_oracle` reste inactive (alias `dmi_db`
non enregistré) — aucun risque de casser le reste du backend en attendant
d'avoir les vraies valeurs.

## 4. Vérifier la connexion

```bash
docker compose exec backend python manage.py dmi_oracle_check ping
```

Doit afficher `Connexion Oracle DMI OK.`. En cas d'erreur, le message
Oracle (ORA-xxxxx) donne la cause (mauvais host/port/service, mauvais
identifiants, pare-feu, etc.).

## 5. Découvrir le vrai schéma

Le modèle Django (`backend/dmi_oracle/models.py`, table
`MD_EXAM_OPHTALMO`, colonnes `NUM_RESUME`/`DATE_EXAMEN`/`COD_MED`/
`PROVENANCE`) est une **supposition**, pas confirmée. Avant de faire
confiance à quoi que ce soit d'autre :

```bash
docker compose exec backend python manage.py dmi_oracle_check tables --like '%EXAM%'
docker compose exec backend python manage.py dmi_oracle_check describe --table <NOM_TABLE_REEL>
```

Renvoyez le résultat (noms de colonnes, types) pour que le modèle et les
endpoints HTTP soient corrigés en conséquence.

## 6. Tester via Postman (ou curl)

Une fois `ORACLE_DMI_HOST` configuré, les endpoints suivants deviennent
actifs sur `http://<host>/api/dmi-oracle/` :

| Méthode | Route | Auth |
| --- | --- | --- |
| GET | `/ping/` | aucune |
| GET | `/tables/?like=%EXAM%` | aucune |
| GET | `/describe/?table=MD_EXAM_OPHTALMO` | aucune |
| GET | `/sample/?table=MD_EXAM_OPHTALMO&limit=5` | `X-DMI-Service-Token` |
| GET | `/exams/` | `X-DMI-Service-Token` |
| POST | `/exams/` | `X-DMI-Service-Token` |

La valeur du token est celle de `DMI_API_TOKEN` (même variable que l'API
`/api/dmi/` HTTP existante).

`POST /exams/` insère réellement une ligne dans `MD_EXAM_OPHTALMO` (ou la
vraie table une fois corrigée) — à n'utiliser qu'une fois certain qu'il
s'agit bien d'une base de test, pas de production.
