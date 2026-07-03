# Architecture Production FTHNet — Sécurité & Données Patients
> **Contexte :** Système d'évaluation de la qualité d'images de fond d'œil en milieu hospitalier. Les images sont des **données de santé sensibles** (identifiantes, diagnostiques). Cette architecture applique les standards les plus stricts de sécurité, confidentialité et disponibilité.

---

## 1. Rappel d'urgence : règles d'or avant tout déploiement

| # | Règle | Justification |
|---|-------|-------------|
| 1 | **JAMAIS** exposer FTHNet directement sur Internet | Données patients = cible privilégiée. Le modèle doit vivre dans un réseau interne/isolé. |
| 2 | **Anonymiser** les images avant traitement (ou limiter l'accès) | Le fond d'œil est quasi-unique (biométrie). Supprimer DICOM tags ID. |
| 3 | **Chiffrer** au repos (stockage) et en transit (TLS 1.3) | Obligation légale pour les données de santé. |
| 4 | **Authentifier** tout appel à l'API | JWT ou mTLS obligatoire. Pas d'accès anonyme. |
| 5 | **Auditer** tous les accès | Qui a envoyé quelle image, quand, depuis quelle IP. |
| 6 | **Ne jamais stocker** les images en clair sans durée de vie limitée | Supprimer l'image après inférence, ou chiffrer puis archiver. |

---

## 2. Matériel recommandé (Serveurs)

### 2.1. Configuration minimale (preuve de concept, hôpital moyen)

| Composant | Spécification | Rôle |
|-----------|---------------|------|
| **Serveur 1 : AI Inference** | 1× NVIDIA RTX A4000 (16 GB) ou RTX 3090, 64 GB RAM, 2× SSD 1 TB NVMe RAID 1, Xeon/EPYC 8 cœurs | Héberge FTHNet + API. Pas d'Internet direct. |
| **Serveur 2 : Application / Gateway** | 32 GB RAM, SSD 512 GB, 8 cœurs | Reverse proxy (Nginx), authentification, filtrage. Seul serveur exposé (si besoin). |
| **Serveur 3 : Backup / Logs** | 64 GB RAM, HDD 4-8 TB RAID 5/6, 8 cœurs | Stockage backup chiffré, SIEM, logs audit. |
| **Firewall** | pfSense / Fortinet / Palo Alto | Segmentation réseau, IDS/IPS. |

### 2.2. Configuration recommandée (hôpital universitaire, HA)

| Composant | Spécification | Rôle |
|-----------|---------------|------|
| **Serveur AI (Primary)** | 1× NVIDIA A100 40 GB ou 2× A10, 128 GB RAM, 2× SSD 2 TB NVMe, Dual Xeon Gold | FTHNet en production. |
| **Serveur AI (Secondary)** | Identique au Primary | Failover en cluster (Kubernetes ou Docker Swarm). |
| **Serveur Gateway (HA)** | 2× serveurs 32 GB, clustering Keepalived + HAProxy | Terminaison TLS, rate limiting, authentification. |
| **NAS/SAN Backup** | 8-16 TB, RAID 6, chiffrement LUKS/AES-256 | Backup images (temporaires) et checkpoints. |
| **UPS** | Onduleur 3000 VA+ | Maintien en vie pour flush disques et shutdown propre. |

### 2.3. Matériel critique (ne pas négliger)

- **HBA (Host Bus Adapter)** si SAN iSCSI/Fibre Channel
- **Double NIC** (réseau AI interne + réseau management séparé)
- **TPM 2.0** sur les serveurs pour le chiffrement disque (BitLocker / LUKS)
- **KVM / IPMI** pour l'administration distante sécurisée (pas sur le réseau patients)

---

## 3. Architecture Réseau (Segmentation Zero Trust)

### Zones de sécurité

```
                    ┌─────────────────────────────────────┐
                    │           Internet (si besoin)       │
                    │    (Accès VPN sécurisé uniquement)   │
                    └─────────────┬───────────────────────┘
                                  │
                    ┌─────────────▼───────────────────────┐
                    │      DMZ (DéMilitarisée)            │
                    │  ┌──────────┐    ┌──────────┐       │
                    │  │  Nginx   │───▶│  WAF/    │       │
                    │  │  HAProxy │    │ Firewall │       │
                    │  └──────────┘    └──────────┘       │
                    └─────────────┬───────────────────────┘
                                  │
                    ┌─────────────▼───────────────────────┐
                    │     Réseau Interne Hospitalier      │
                    │  ┌──────────┐    ┌──────────┐      │
                    │  │ Auth/    │───▶│  API     │      │
                    │  │ IAM      │    │ FTHNet   │      │
                    │  └──────────┘    └────┬─────┘      │
                    │                       │            │
                    │                  ┌────▼────┐       │
                    │                  │  GPU    │       │
                    │                  │ Worker  │       │
                    │                  └─────────┘       │
                    └─────────────────────────────────────┘
                                  │
                    ┌─────────────▼───────────────────────┐
                    │     Réseau Backup/Logs (AirGap)   │
                    │  ┌──────────┐    ┌──────────┐      │
                    │  │ NAS      │    │  SIEM    │      │
                    │  │ Chiffré  │    │  Splunk  │      │
                    │  └──────────┘    └──────────┘      │
                    └─────────────────────────────────────┘
```

### Points d'ancrage

- **Pas d'accès Internet direct** depuis la zone AI. Mise à jour par bastion/jump host.
- **VLAN séparé** pour le trafic AI (pas de broadcast avec le réseau hospitalier général).
- **mTLS** entre le gateway et l'API FTHNet (certificats internes).
- **Accès PACS/DICOM** uniquement via un broker sécurisé (pas de connexion directe).

---

## 4. Architecture Applicative (Conteneurs sécurisés)

### 4.1. Docker Compose (production sécurisée)

```yaml
version: "3.8"
services:
  # ── AI Inference (isolé, pas d'accès externe) ──
  fthnet-api:
    build:
      context: ./fthnet
      dockerfile: Dockerfile.secure
    runtime: nvidia
    environment:
      - FTHNET_WEIGHTS=/app/pretrained_weight/net_g_226264S4.pth
      - FTHNET_EMBED_DIM=64
      - NVIDIA_VISIBLE_DEVICES=0
    volumes:
      - fthnet_weights:/app/pretrained_weight:ro
      - /dev/null:/app/tmp_uploads:noexec,nosuid,nodev  # Empêche l'exécution
    networks:
      - ai_internal
    # Pas de ports exposés vers l'extérieur !
    security_opt:
      - no-new-privileges:true
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=100m
    cap_drop:
      - ALL
    cap_add:
      - SYS_NICE  # Pour GPU scheduling uniquement

  # ── Reverse Proxy & Gateway (seul point d'entrée) ──
  nginx-gateway:
    image: nginx:alpine
    ports:
      - "127.0.0.1:8443:443"  # TLS interne seulement
    volumes:
      - ./nginx/ssl:/etc/nginx/ssl:ro
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    networks:
      - ai_internal
      - hospital_net
    depends_on:
      - fthnet-api

  # ── Authentification (Keycloak ou simple JWT) ──
  auth-service:
    image: keycloak/keycloak:24.0
    environment:
      - KC_DB=postgres
      - KC_DB_URL=jdbc:postgresql://auth-db:5432/keycloak
      - KC_DB_USERNAME=keycloak
      - KC_DB_PASSWORD_FILE=/run/secrets/db_password
      - KC_HOSTNAME=auth.hospital.local
      - KC_HTTPS_CERTIFICATE_FILE=/etc/ssl/certs/hospital.crt
      - KC_HTTPS_CERTIFICATE_KEY_FILE=/etc/ssl/private/hospital.key
    secrets:
      - db_password
    networks:
      - hospital_net

  # ── Base de données audit (qui a fait quoi) ──
  audit-db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=fthnet_audit
      - POSTGRES_USER=audit_logger
      - POSTGRES_PASSWORD_FILE=/run/secrets/audit_db_password
    volumes:
      - audit_postgres:/var/lib/postgresql/data
      - ./init-scripts/audit.sql:/docker-entrypoint-initdb.d/01-init.sql:ro
    secrets:
      - audit_db_password
    networks:
      - ai_internal

networks:
  ai_internal:
    driver: bridge
    internal: true  # Pas de route vers l'extérieur
  hospital_net:
    driver: bridge

volumes:
  fthnet_weights:
  audit_postgres:

secrets:
  db_password:
    file: ./secrets/db_password.txt
  audit_db_password:
    file: ./secrets/audit_db_password.txt
```

### 4.2. Dockerfile sécurisé (multi-stage, non-root)

```dockerfile
# Étape 1 : Build
FROM nvidia/cuda:12.1-devel-ubuntu22.04 AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Étape 2 : Runtime minimal
FROM nvidia/cuda:12.1-runtime-ubuntu22.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Créer utilisateur non-root
RUN groupadd -r fthnet && useradd -r -g fthnet -s /bin/false fthnet

COPY --from=builder /root/.local /home/fthnet/.local
ENV PATH=/home/fthnet/.local/bin:$PATH

WORKDIR /app
COPY --chown=fthnet:fthnet fthnet_api.py /app/
COPY --chown=fthnet:fthnet basiqa /app/basiqa

USER fthnet
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "fthnet_api:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 5. Sécurité des données patients

### 5.1. Anonymisation avant inférence

Le fond d'œil est une **empreinte biométrique**. Avant d'envoyer à FTHNet :

1. **Supprimer les métadonnées DICOM** : nom, date de naissance, ID patient, numéro de sécurité sociale, timestamp exact.
2. **Générer un pseudo-ID** : `PAT-2026-7F3A9E` (hash SHA-256 de l'ID interne + sel secret).
3. **Supprimer les coins** (les images DICOM peuvent avoir du texte annoté en overlay).
4. **Audit** : logger la transformation `ID réel → pseudo-ID` dans une base séparée (accès restreint).

### 5.2. Chiffrement

| Couche | Méthode | Clé |
|--------|---------|-----|
| Disque système | LUKS (Linux) / BitLocker (Windows) | TPM + passphrase admin |
| Backup NAS | AES-256-GCM | HSM ou clé dans un vault (HashiCorp Vault) |
| Communication API | TLS 1.3, certificats internes | PKI interne hôpital |
| DICOM en transit | TLS DICOM (port 2762) ou VPN | Certificats médicaux |
| Base de données audit | Chiffrement au niveau colonne (pgsodium) | Vault |

### 5.3. Durée de vie des données (rétention)

| Donnée | Durée | Action après |
|--------|-------|--------------|
| Image brute uploadée | 24 heures | Suppression automatique |
| Image anonymisée + résultat | Durée légale (ex: 10 ans) | Archivage chiffré |
| Logs d'audit | 10 ans | Immuable, backup sur WORM |
| Pseudo-ID mapping | 10 ans | Suppression du sel = irréversible |

---

## 6. Authentification et autorisation

### 6.1. Modèle d'accès recommandé

```
[Ophtalmologiste] ──JWT──▶ [Gateway] ──mTLS──▶ [FTHNet API]
     │                        │                      │
     │                        │                      ▼
     │                        │               [Vérifier scope:
     │                        │                "fthnet:predict"]
     │                        │
     ▼                        ▼
[Role: "medecin"]      [Rate limit: 10 req/min]
```

### 6.2. Implémentation (JWT + scopes)

```python
# Dans fthnet_api.py (à ajouter)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials):
    token = credentials.credentials
    payload = jwt.decode(token, PUBLIC_KEY, algorithms=["RS256"])
    if "fthnet:predict" not in payload.get("scope", []):
        raise HTTPException(403, "Insufficient scope")
    return payload["sub"]  # User ID

@app.post("/predict")
async def predict_endpoint(
    file: UploadFile = File(...),
    user: str = Depends(verify_token)
):
    # ... inférence ...
    # Logger l'audit
    await log_audit(user, file.filename, score)
    return {...}
```

---

## 7. Backup & Reprise d'activité (DR)

### 7.1. Stratégie 3-2-1 (adaptée aux données sensibles)

| Règle | Application |
|-------|-------------|
| **3** copies | Originale, backup local, backup distant |
| **2** médias différents | SSD/NAS local + bandes LTO ou cloud chiffré |
| **1** offsite | Backup dans un datacenter hôpital distant ou cloud souverain |
| **0** erreur | Vérification régulière des restaurations (test mensuel) |

### 7.2. Plan de sauvegarde

| Fréquence | Contenu | Destination |
|-----------|---------|-------------|
| Toutes les heures | Logs audit | NAS local (snapshots) |
| Quotidien | Modèles, code, configs | NAS + bande LTO |
| Hebdomadaire | Image complète serveur (bare metal) | Offsite |
| Mensuel | Test de restauration | Environnement isolé |

### 7.3. RPO / RTO

| Métrique | Valeur | Signification |
|----------|--------|---------------|
| **RPO** (Recovery Point Objective) | 1 heure | Perte de données max acceptable : 1h de logs |
| **RTO** (Recovery Time Objective) | 4 heures | Temps max pour remettre le service en ligne |
| **Failover** | Actif/Passif | Le serveur secondary prend le relais en 5 min |

---

## 8. Monitoring et alerting

### 8.1. Indicateurs critiques

| Métrique | Seuil d'alerte | Action |
|----------|----------------|--------|
| GPU température | > 85°C | Alerte + throttle |
| Latence inférence | > 200 ms | Alerte performance |
| Erreurs API | > 1% / 5 min | Page on-call |
| Tentatives auth échouées | > 5 / min | Blocage IP + investigation |
| Espace disque | > 85% | Alerte + cleanup auto |
| Accès non autorisé | Toute tentative | Alerting immédiat + forensics |

### 8.2. Outils recommandés

- **Prometheus + Grafana** : Métriques système + métriques métier
- **ELK / Splunk** : Centralisation des logs (SIEM)
- **Nagios / Zabbix** : Surveillance infrastructure

---

## 9. Checklist de mise en production

Avant d'ouvrir le service :

- [ ] **Pentest** réalisé (ou audit interne sécurité)
- [ ] **DPA** (Data Processing Agreement) signé avec tout sous-traitant cloud
- [ ] **RGPD** : registre des traitements à jour, DPO informé
- [ ] **Chiffrement disque** activé sur tous les serveurs
- [ ] **TLS 1.3** configuré, pas de TLS 1.0/1.1
- [ ] **HSTS** et headers de sécurité appliqués
- [ ] **Fail2ban** ou équivalent activé
- [ ] **Backup** testé (restauration réussie ce mois-ci)
- [ ] **Runbook** incident rédigé (numéros d'urgence, procédures)
- [ ] **Formation** équipe médicale (ne pas envoyer d'images sur WhatsApp !)
- [ ] **Déconnexion** du WiFi patient (réseau AI ≠ réseau visiteurs)

---

## 10. Résumé de l'architecture cible

```
┌─────────────────────────────────────────────────────────────────┐
│  INTERNET (VPN IPsec/SSL uniquement)                            │
│         │                                                       │
│  ┌──────▼──────┐   ┌──────────┐   ┌──────────────────────┐     │
│  │   Gateway   │──▶│   WAF    │──▶│  Auth (Keycloak)     │     │
│  │  Nginx+TLS  │   │ ModSec   │   │  JWT + RBAC          │     │
│  └──────┬──────┘   └──────────┘   └──────────────────────┘     │
│         │ mTLS + rate limiting                                    │
│  ┌──────▼──────┐   ┌──────────┐                                  │
│  │  FTHNet API │──▶│  GPU     │                                  │
│  │  (Docker)   │   │  A100    │                                  │
│  └──────┬──────┘   └──────────┘                                  │
│         │                                                        │
│  ┌──────▼──────┐   ┌──────────┐                                  │
│  │  Audit DB   │   │  NAS     │                                  │
│  │  Postgres   │   │  Backup  │                                  │
│  │  (chiffrée) │   │  LUKS    │                                  │
│  └─────────────┘   └──────────┘                                  │
└─────────────────────────────────────────────────────────────────┘
         ▲
         │ VLAN isolé (pas de routage vers le Net)
    ┌────┴────┐
    │  PACS   │  (DICOM broker sécurisé)
    │  Hôpital│
    └─────────┘
```

---

## 11. Contacts et ressources

- **Rapport d'incident** : `security@hospital.tn`
- **DPO / Délégué à la protection des données** : à désigner obligatoirement
- **Majeures failles sécurité** : CVE monitoring pour PyTorch, CUDA, Ubuntu
- **Mise à jour** : patchs sécurité mensuels (pas de `apt upgrade` automatique en prod !)

---

> **Document confidentiel.** À ne pas diffuser hors du service informatique et de la direction médicale. Version 1.0.
