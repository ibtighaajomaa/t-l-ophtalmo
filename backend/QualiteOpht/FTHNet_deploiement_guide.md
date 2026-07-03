# Guide de déploiement FTHNet sur votre serveur

## 1. Prérequis matériels et logiciels

| Composant | Minimum | Recommandé |
|-----------|---------|------------|
| GPU | NVIDIA avec 4 GB VRAM | NVIDIA RTX 3090 / A100 |
| RAM | 8 GB | 16 GB |
| Stockage | 10 GB | 20 GB |
| OS | Ubuntu 20.04 / CentOS 7 | Ubuntu 22.04 LTS |
| CUDA | 11.1+ | 12.1+ |
| Python | 3.8+ | 3.10 |

---

## 2. Installation pas à pas

### 2.1. Cloner le dépôt

```bash
git clone https://github.com/HudenJear/BasiQA.git
cd BasiQA
```

### 2.2. Créer l'environnement Conda

```bash
conda create -n basiqa python=3.8 -y
conda activate basiqa
```

### 2.3. Installer PyTorch avec CUDA

```bash
# Pour CUDA 12.1
pip install torch==2.1.0 torchvision==0.16.0 --index-url https://download.pytorch.org/whl/cu121

# Pour CUDA 11.8
pip install torch==2.1.0 torchvision==0.16.0 --index-url https://download.pytorch.org/whl/cu118
```

### 2.4. Installer les dépendances

```bash
pip install -r requirements.txt
```

**Contenu de `requirements.txt` :**
```
addict
future
lmdb
numpy<2.0
opencv-python
Pillow
pyyaml
requests
scikit-image
scipy
timm
torch>=1.7
torchvision
tqdm
yapf
pandas
scikit-learn
openpyxl
xlrd
```

### 2.5. Installer SoftPool (obligatoire pour FTHNet)

```bash
cd ~
git clone https://github.com/alexandrosstergiou/SoftPool.git
cd SoftPool/pytorch/
python setup.py install
```

> **Note :** Si l'installation de SoftPool échoue, vous pouvez utiliser l'alternative `AvgPool2d` dans le code (modifiée dans le script API ci-dessous).

### 2.6. Télécharger les poids pré-entraînés

Les poids sont disponibles sur Google Drive :
- **Lien :** https://drive.google.com/drive/folders/1gXaa77aARo1sdqky3_81JD6ofL17fGUU?usp=sharing
- **Code Baidu :** `fth1`

```bash
mkdir -p pretrained_weight
# Placez le fichier .pth téléchargé dans pretrained_weight/
# Exemple : pretrained_weight/net_g_226264S4.pth
```

---

## 3. Structure des fichiers après installation

```
BasiQA/
├── basiqa/                  # Code source principal
│   ├── archs/               # Architectures (FTHNet4, etc.)
│   ├── data/                # Datasets et loaders
│   ├── models/              # Modèles (FIQAModel, HyperIQAModel)
│   ├── utils/               # Utilitaires
│   ├── test.py             # Script de test
│   └── train_multi.py      # Script d'entraînement
├── datasets/                # Datasets (FQS, etc.)
├── options/                 # Fichiers de configuration YAML
│   ├── test/
│   │   └── test_FTHNet.yml
│   └── train/
├── pretrained_weight/       # Poids du modèle
├── requirements.txt
└── fthnet_api.py           # <-- Votre script API (voir section 4)
```

---

## 4. Déploiement comme API (FastAPI)

Le fichier `fthnet_api.py` fourni dans ce guide permet de :
- Recevoir une image via HTTP POST (`/predict`)
- Retourner un score de qualité continu (0-100)
- Classifier l'image en 3 catégories : Good / Usable / Reject
- Fonctionner sur GPU ou CPU

### 4.1. Lancer l'API en local

```bash
conda activate basiqa
cd BasiQA
python fthnet_api.py
```

L'API sera accessible sur : `http://localhost:8000`

### 4.2. Tester l'API avec curl

```bash
curl -X POST "http://localhost:8000/predict" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@votre_image_fond_oeil.jpg"
```

### 4.3. Réponse attendue

```json
{
  "filename": "votre_image_fond_oeil.jpg",
  "quality_score": 78.45,
  "quality_category": "Usable",
  "inference_time_ms": 45.2
}
```

---

## 5. Déploiement sur un serveur de production

### 5.1. Avec Gunicorn (serveur WSGI/ASGI)

```bash
pip install gunicorn uvicorn

gunicorn -w 2 -k uvicorn.workers.UvicornWorker fthnet_api:app \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

### 5.2. Avec Docker (recommandé)

Créez un `Dockerfile` :

```dockerfile
FROM nvidia/cuda:12.1-devel-ubuntu22.04

RUN apt-get update && apt-get install -y \
    python3-pip python3-dev git wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Installer SoftPool
RUN git clone https://github.com/alexandrosstergiou/SoftPool.git /tmp/softpool \
    && cd /tmp/softpool/pytorch \
    && python setup.py install

COPY . .
EXPOSE 8000

CMD ["python", "fthnet_api.py"]
```

Build et run :
```bash
docker build -t fthnet-api .
docker run --gpus all -p 8000:8000 fthnet-api
```

### 5.3. Avec systemd (service Linux)

Créez `/etc/systemd/system/fthnet.service` :

```ini
[Unit]
Description=FTHNet Fundus Quality API
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/BasiQA
Environment="PATH=/home/ubuntu/miniconda3/envs/basiqa/bin"
Environment="CUDA_VISIBLE_DEVICES=0"
ExecStart=/home/ubuntu/miniconda3/envs/basiqa/bin/python fthnet_api.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Activation :
```bash
sudo systemctl daemon-reload
sudo systemctl enable fthnet
sudo systemctl start fthnet
sudo systemctl status fthnet
```

### 5.4. Avec Nginx (reverse proxy + SSL)

Configuration `/etc/nginx/sites-available/fthnet` :

```nginx
server {
    listen 80;
    server_name votre-domaine.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

Activation :
```bash
sudo ln -s /etc/nginx/sites-available/fthnet /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 6. Intégration dans un système de diagnostic

D'après l'article, FTHNet peut être intégré dans un système de diagnostic automatique comme suit :

```
[Image fond d'œil] --> [FTHNet API] --> [Score qualité]
                                      |
                                      v
                         [Score >= 80 ?] --> [Diagnostic IA fiable]
                         [Score < 60  ?] --> [Rejeter / Refaire photo]
                         [Score 60-80]  --> [Diagnostic avec précaution]
```

Exemple de code client Python :

```python
import requests

def evaluate_fundus_quality(image_path):
    url = "http://votre-serveur:8000/predict"
    with open(image_path, "rb") as f:
        files = {"file": f}
        response = requests.post(url, files=files)
    return response.json()

result = evaluate_fundus_quality("image.jpg")
print(f"Score: {result['quality_score']:.2f}/100")
print(f"Catégorie: {result['quality_category']}")
```

---

## 7. Dépannage courant

| Problème | Solution |
|----------|----------|
| `SoftPool` non trouvé | Vérifier l'installation de SoftPool ou utiliser le fallback AvgPool2d dans le code API |
| Erreur CUDA out of memory | Réduire `batch_size` ou utiliser le modèle FTHNet-S au lieu de FTHNet-L |
| Erreur `numpy` | Vérifier `numpy<2.0` : `pip install "numpy<2.0"` |
| Poids du modèle non chargés | Vérifier le chemin dans `test_FTHNet.yml` ou dans le script API |
| Image trop grande | Le script redimensionne automatiquement à 384x384 |

---

## 8. Références

- **Article :** Gong Z. et al. "Acquire continuous and precise score for fundus image quality assessment: FTHNet and FQS dataset." *Scientific Reports* 15, 40524 (2025).
- **Code :** https://github.com/HudenJear/BasiQA
- **Dataset FQS :** https://figshare.com/articles/dataset/FIQS_Dataset_Fundus_Image_Quality_Scores_/28129847
- **SoftPool :** https://github.com/alexandrosstergiou/SoftPool

---

*Guide généré pour le déploiement de FTHNet en environnement clinique / serveur.*
