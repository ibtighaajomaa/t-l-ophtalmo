# Documentation des modèles d’intelligence artificielle

## Objet et périmètre

Ce document inventorie les modèles **effectivement activés par le déploiement Docker** de Télé‑Ophtalmo. Il a été établi à partir de `docker-compose.yml`, des configurations MONAI Label, des poids présents dans le dépôt et des fiches publiques des modèles.

> **Important — métriques :** une métrique publiée par l’auteur d’un modèle n’est pas une validation du système Télé‑Ophtalmo. À ce jour, le dépôt ne contient pas de campagne d’évaluation clinique commune sur une cohorte locale. Les valeurs ci-dessous sont donc marquées « publiée », « contrôle local » ou « non documentée ».

## Synthèse

| Fonction dans l’application | Modèle et architecture | Taille du modèle | Base de données annoncée | Taille de la base | Métrique disponible | Code ou modèle source |
| --- | --- | ---: | --- | ---: | --- | --- |
| Contrôle qualité de la rétinographie | **FTHNet4**, Swin Transformer + hypernetwork | environ **5,6 M paramètres** ; poids local 18,4 Mio | FQS | **2 246 images** | publication : **PLCC 0,9442**, **SRCC 0,9358**, validation croisée 10 plis | [BasiQA / FTHNet](https://github.com/HudenJear/BasiQA) |
| Latéralité de l’œil | **InceptionV3** + global average pooling + dense 1 024 + softmax | environ **24 M paramètres** ; poids local 183 Mio | neuf bases regroupées + échantillon Kaggle, selon les notebooks amont | **18 394 entraînement**, **2 000 test** dans les fichiers HDF5 présents | contrôle indiqué dans le code : **99 %** sur un échantillon équilibré du test ; pas de rapport reproductible versionné | [Eye-laterality-detection](https://github.com/keepgallop/Eye-laterality-detection) |
| Segmentation papille/cupule | **SegFormer** fine-tuné | **47,2 M paramètres** | REFUGE | **1 200 images** : 400 entraînement, 400 validation, 400 test | **non documentée** dans la model card et non recalculée dans ce dépôt | [modèle Hugging Face](https://huggingface.co/pamixsun/segformer_for_optic_disc_cup_segmentation) · [Transformers](https://github.com/huggingface/transformers) |
| Segmentation des vaisseaux | **U-Net++**, encodeur EfficientNet-B3 | poids local **52,6 Mio** (environ 13,8 M valeurs FP32) | CHASE_DB1, annoncé dans le code | **28 images** de 14 enfants | **non documentée** pour ce checkpoint et non recalculée | [Segmentation Models PyTorch](https://github.com/qubvel-org/segmentation_models.pytorch) |
| Segmentation des lésions de RD | **DeepLabV3+**, encodeur EfficientNet-B3, 5 classes | poids local **45,1 Mio** (environ 11,8 M valeurs FP32) | DDR, annoncé dans le code | **13 673 images** au total ; le sous-ensemble de segmentation doit être confirmé pour ce checkpoint | **non documentée** pour ce checkpoint et non recalculée | [DDR-dataset](https://github.com/nkicsl/DDR-dataset) · [Segmentation Models PyTorch](https://github.com/qubvel-org/segmentation_models.pytorch) |
| Classification de la rétinopathie diabétique, grades 0 à 4 | **Vision Transformer (ViT)** fine-tuné | famille ViT-Base, environ **86 M paramètres** | la tâche et le code indiquent APTOS 2019, mais la model card publique ne renseigne pas le dataset | **3 662 images d’entraînement** dans APTOS 2019 | model card : **accuracy 0,7287**, loss 1,0460 sur son jeu d’évaluation non décrit | [modèle Hugging Face](https://huggingface.co/Kontawat/vit-diabetic-retinopathy-classification) · [Transformers](https://github.com/huggingface/transformers) |
| Génération du compte rendu | **MedGemma 1.5 4B IT**, Gemma 3 multimodal + encodeur d’images SigLIP | **4 milliards de paramètres** | mélange de données médicales publiques et sous licence, désidentifiées ; détails et volumes non publiés | **non communiqué** | aucune métrique spécifique au compte rendu de fond d’œil de cette application | [Google Health MedGemma](https://github.com/google-health/medgemma) · [modèle Hugging Face](https://huggingface.co/google/medgemma-1.5-4b-it) |

Le modèle `composite_seg` n’est pas un huitième réseau : il orchestre les sorties des modèles papille/cupule, lésions et vaisseaux. Il ne possède ni entraînement ni métrique propre dans ce dépôt.

## Détails par modèle

### 1. FTHNet4 — qualité de l’image

FTHNet4 produit un score continu de qualité. L’application transforme ce score en trois niveaux : bonne qualité à partir de 70, qualité acceptable entre 40 et 70, et mauvaise qualité sous 40. Ces seuils sont des paramètres applicatifs et non des performances publiées. Le checkpoint utilisé est `net_g_226264S4.pth`.

Les métriques pertinentes sont le **PLCC** (corrélation linéaire entre scores prédits et scores humains) et le **SRCC** (corrélation des rangs). Elles ne doivent pas être comparées directement à une accuracy de classification.

### 2. Détection droite/gauche

Le modèle Keras reçoit une image 299 × 299 et prédit deux classes : œil droit (`R`) ou œil gauche (`L`). Les fichiers inclus permettent de vérifier exactement la volumétrie :

- `Xy.h5` : 18 394 images, environ 4,59 Gio ;
- `test_Xy.h5` : 2 000 images, environ 512 Mio.

La mention de 99 % dans le code correspond à un contrôle ponctuel de l’export sur un échantillon équilibré. Il manque un script de test figé, la graine, la matrice de confusion et les intervalles de confiance ; ce chiffre ne doit donc pas être présenté comme une validation clinique du produit.

### 3. Segmentation papille/cupule

Le modèle `pamixsun/segformer_for_optic_disc_cup_segmentation` segmente le fond, la papille et la cupule à partir d’une image redimensionnée en 512 × 512. La fiche publique confirme un entraînement spécialisé sur REFUGE et une taille de 47,2 M paramètres, mais ne publie ni Dice, ni IoU, ni sensibilité pour ce checkpoint.

Les métriques recommandées sont : Dice papille, Dice cupule, IoU par classe, erreur absolue du rapport vertical cupule/disque et sensibilité du seuil de risque glaucomateux.

### 4. Segmentation vasculaire

Le réseau est un U-Net++ avec encodeur EfficientNet-B3 et une sortie binaire. Le masque final emploie un seuil de 0,5. Le code décrit CHASE_DB1 comme base d’origine, mais le dépôt ne contient ni recette d’entraînement, ni découpage train/test, ni résultats liés au fichier `vessel_seg.pt`. Il serait incorrect de lui attribuer les résultats d’un autre U-Net++ publié sur CHASE_DB1.

Les métriques à produire sont : Dice/F1 vasculaire, IoU, sensibilité, spécificité, AUC pixel et métriques de continuité des vaisseaux fins.

### 5. Segmentation des lésions

Le réseau est un DeepLabV3+ avec encodeur EfficientNet-B3. Il prédit cinq classes : fond, microanévrismes, hémorragies, exsudats durs et exsudats mous. Le checkpoint prioritaire est `lesion_seg_ddr.pt`.

Le code associe ce poids à DDR, mais aucun manifeste ne relie le checkpoint à une version précise, un split ou une exécution d’entraînement. Les métriques minimales sont le Dice et l’IoU par lésion, ainsi que la sensibilité au niveau lésion et au niveau image. Le fort déséquilibre entre fond et petites lésions rend l’accuracy pixel globale peu informative.

### 6. Classification de la rétinopathie diabétique

Le modèle public `Kontawat/vit-diabetic-retinopathy-classification` prédit cinq grades : absence de RD, NPDR légère, modérée, sévère et RD proliférante. Sa fiche annonce une accuracy finale de 72,87 %, mais laisse le champ du dataset vide. L’association à APTOS 2019 vient de la description de la tâche dans ce projet, pas de la fiche du producteur ; elle doit donc être vérifiée avant un dossier réglementaire.

Une évaluation locale devrait publier au minimum : matrice de confusion, macro-F1, balanced accuracy, sensibilité/spécificité par grade, AUC one-vs-rest et kappa quadratique pondéré.

### 7. MedGemma — génération du rapport

`google/medgemma-1.5-4b-it` reçoit l’image et/ou les résultats structurés des autres modèles puis rédige le rapport en français. C’est un modèle génératif d’aide à la rédaction, pas la source de vérité des mesures quantitatives. Google indique un mélange de données médicales publiques et sous licence, incluant texte, radiologie, histopathologie, dermatologie et ophtalmologie, sans publier le nombre total d’exemples.

Les benchmarks généraux de MedGemma ne mesurent pas la fidélité des rapports produits par cette application. Une validation spécifique doit mesurer : fidélité aux valeurs fournies, taux d’hallucination, complétude, cohérence latérale droite/gauche et accord de spécialistes.

## Traçabilité dans le dépôt

| Élément | Emplacement |
| --- | --- |
| Liste des modèles activés et identifiant MedGemma | `docker-compose.yml` |
| Configurations des six tâches MONAI | `monai-apps/radiology/lib/configs/` |
| Implémentations d’inférence | `monai-apps/radiology/lib/infers/` |
| Poids de segmentation et de latéralité | `monai-apps/radiology/model/` |
| Code et poids FTHNet4 | `backend/QualiteOpht/UserschiheAppDataLocalTempBasiQA/` |
| Service de génération de rapport | `backend/report-generation/` |
| Projet principal | [ibtighaajomaa/t-l-ophtalmo](https://github.com/ibtighaajomaa/t-l-ophtalmo) |

## Limites et actions nécessaires

Les tailles de poids ne suffisent pas à garantir l’identité ou la qualité d’un modèle. Pour rendre cette documentation exploitable en production et dans un dossier qualité, il reste à :

1. enregistrer le SHA-256, la licence et l’URL/version exacte de chaque checkpoint ;
2. ajouter un manifeste indiquant dataset, split, prétraitement, hyperparamètres et commit d’entraînement ;
3. constituer une cohorte tunisienne indépendante, représentative des caméras et sites utilisés ;
4. exécuter une évaluation reproductible avec intervalles de confiance et analyse par sous-groupes ;
5. faire valider les seuils cliniques et les rapports générés par des ophtalmologistes.

## Sources publiques principales

- [FTHNet et FQS — article](https://arxiv.org/abs/2411.12273)
- [REFUGE — description officielle](https://refuge.grand-challenge.org/Details/)
- [APTOS 2019 Blindness Detection](https://www.kaggle.com/c/aptos2019-blindness-detection)
- [CHASE_DB1](https://blogs.kingston.ac.uk/retinal/chasedb1/)
- [DDR dataset](https://github.com/nkicsl/DDR-dataset)
- [MedGemma 1.5 — model card officielle](https://developers.google.com/health-ai-developer-foundations/medgemma/model-card)

Dernière mise à jour de l’inventaire : 21 juillet 2026.
