/**
 * translate-dicom-fr.js
 * Traduit automatiquement l'interface OHIF et les descriptions DICOM
 * de l'anglais vers le français via un MutationObserver et l'initialisation i18next.
 */
(function () {
  'use strict';

  // ── Force i18next to French if available ─────────────────────────────────────
  try {
    localStorage.setItem('i18nextLng', 'fr');
    sessionStorage.setItem('i18nextLng', 'fr');
  } catch (e) {}

  function syncI18n() {
    try {
      if (window.i18n && typeof window.i18n.changeLanguage === 'function') {
        if (window.i18n.language !== 'fr') {
          window.i18n.changeLanguage('fr');
        }
      }
    } catch (e) {}
  }
  syncI18n();
  const i18nInterval = setInterval(syncI18n, 1000);
  setTimeout(() => clearInterval(i18nInterval), 15000);

  // ── Dictionnaire complet EN → FR ────────────────────────────────────────────
  const EXACT_TRANSLATIONS = {
    // Descriptions DICOM / Modalités
    'Retinal Fundus Photography':          "Photographie du fond d'œil",
    'Fundus Photography':                  "Photographie du fond d'œil",
    'Retinal Photography':                 'Photographie rétinienne',
    'Ophthalmic Photography':              'Photographie ophtalmique',
    'Ophthalmic Photograph':               'Photographie ophtalmique',
    'Ophthalmic Tomography':               'Tomographie ophtalmique',
    'Fundus Photo':                        "Photo du fond d'œil",
    'Color Fundus':                        "Fond d'œil couleur",
    'Color Fundus Photography':            "Fond d'œil couleur",
    'Fluorescein Angiography':             'Angiographie à la fluorescéine',
    'Indocyanine Green Angiography':       "Angiographie au vert d'indocyanine",
    'Optical Coherence Tomography':        'Tomographie par cohérence optique (OCT)',
    'OCT':                                 'OCT',
    'OCT Angiography':                     'Angiographie OCT',
    'Visual Field':                        'Champ visuel',
    'Perimetry':                           'Périmétrie',
    'Slit Lamp':                           'Lampe à fente',
    'Anterior Segment':                    'Segment antérieur',
    'External Eye':                        'Œil externe',
    'Corneal Topography':                  'Topographie cornéenne',
    'Retinal Angiography':                 'Angiographie rétinienne',
    'Diabetic Retinopathy Screening':      'Dépistage de la rétinopathie diabétique',
    'Retinopathy Screening':               'Dépistage de la rétinopathie',
    'Macular Degeneration':                'Dégénérescence maculaire',
    'Age-Related Macular Degeneration':    'DMLA',
    'Glaucoma':                            'Glaucome',
    'Optic Disc':                          'Disque optique',
    'Optic Nerve':                         'Nerf optique',
    'Retinal Detachment':                  'Décollement de la rétine',
    'Cataract':                            'Cataracte',
    'Diabetic Retinopathy':                'Rétinopathie diabétique',
    'Ophthalmic Refraction':               'Réfraction ophtalmique',
    'Autorefraction':                      'Autoréfraction',
    'Keratometry':                         'Kératométrie',
    'Tonometry':                           'Tonométrie',
    'Biometry':                            'Biométrie',

    // Côtés / Yeux
    'Right Eye':                           'Œil droit',
    'Left Eye':                            'Œil gauche',
    'Both Eyes':                           'Les deux yeux',
    'OD':                                  'OD (Œil droit)',
    'OS':                                  'OS (Œil gauche)',
    'OU':                                  'OU (Deux yeux)',

    // Interface OHIF Navigation & Onglets
    'Studies':                             'Études',
    'Series':                              'Séries',
    'Study List':                          'Liste des examens',
    'Patient':                             'Patient',
    'Measurements':                        'Mesures',
    'Measurement Tracking':                'Suivi des mesures',
    'Segmentation':                        'Segmentation',
    'AI Analysis':                         'Analyse IA',
    'Track':                               'Suivre',
    'Hydrate':                             'Charger',
    'LOAD':                                'CHARGER',

    // Boutons et Actions
    'Print Report':                        'Imprimer le rapport',
    'Save':                                'Enregistrer',
    'Saving...':                           'Enregistrement...',
    'Saved':                               'Enregistré',
    'Zoom':                                'Zoom',
    'Pan':                                 'Déplacer',
    'Rotate Right':                        'Pivoter à droite',
    'Rotate Left':                         'Pivoter à gauche',
    'Flip Horizontally':                   'Miroir horizontal',
    'Flip Vertically':                     'Miroir vertical',
    'Invert':                              'Inverser',
    'Reset':                               'Réinitialiser',
    'Reset View':                          'Réinitialiser la vue',
    'Length':                              'Longueur',
    'Angle':                               'Angle',
    'Probe':                               'Sonde',
    'Rectangle':                           'Rectangle',
    'Circle':                              'Cercle',
    'Freehand':                            'Tracé libre',
    'Layout':                              'Disposition',
    'Window Level':                        'Fenêtrage / Contraste',
    'Next Image':                          'Image suivante',
    'Previous Image':                      'Image précédente',
    'Capture':                             'Capture',
    'Export':                              'Exporter',
    'More':                                'Plus',
    'Cancel':                              'Annuler',
    'Clear':                               'Effacer',
    'Filter':                              'Filtrer',
    'Search':                              'Rechercher',
    'Close':                               'Fermer',
    'Back':                                'Retour',
    'Next':                                'Suivant',
    'Previous':                            'Précédent',

    // Métadonnées & Tableaux
    'Modality':                            'Modalité',
    'Description':                         'Description',
    'Date':                                'Date',
    'Patient Name':                        'Nom du patient',
    'MRN':                                 'IPP',
    'Accession':                           'N° d\'accession',
    'Instances':                           'Instances',
    'Loading...':                          'Chargement...',
    'No data available':                   'Aucune donnée disponible',

    // Panneau IA / Ophtalmo
    'DMLA — DeepSeeNet+':                  'DMLA',
    'Microaneurysms':                      'Microanévrismes',
    'Hemorrhages':                         'Hémorragies',
    'Exudates':                            'Exsudats',
    'Hard Exudates':                       'Exsudats durs',
    'Cotton Wool Spots':                   'Nodules cotonneux',
    'Neovascularization':                  'Néovascularisation',
    'Fibrous Tissue':                      'Tissu fibreux',
    'Optic disc':                          'Disque optique',
    'Optic cup':                           'Excavation papillaire',
    'Cup to disc ratio':                   'Rapport cup/disc',
    'Fovea':                               'Fovéa',
    'Macula':                              'Macula',
    'Macular Edema':                       'Œdème maculaire',
    'Normal':                              'Normal',
    'Mild':                                'Légère',
    'Moderate':                            'Modérée',
    'Severe':                              'Sévère',
    'Proliferative':                       'Proliférante',
    'Non-proliferative':                   'Non proliférante',
    'Referable':                           'À référer',
    'Confidence':                          'Confiance',
    'Recommendation':                      'Recommandation',
    'Findings':                            'Constatations',
    'Impression':                          'Conclusion',
    'Report modifiable — verify clinical content before validation.': 'Rapport modifiable — vérifiez le contenu clinique avant validation.',
  };

  // Préfixes partiels à traduire dans les chaînes composées
  const PREFIX_REPLACEMENTS = [
    [/^Retinal Fundus Photography\b/i, "Photographie du fond d'œil"],
    [/^Fundus Photography\b/i, "Photographie du fond d'œil"],
    [/^Ophthalmic Photography\b/i, "Photographie ophtalmique"],
    [/^Optical Coherence Tomography\b/i, "Tomographie par cohérence optique"],
    [/^Print Report\b/i, "Imprimer le rapport"],
    [/DMLA\s*—\s*DeepSeeNet\+/i, "DMLA"],
  ];

  const SORTED_EXACT_KEYS = Object.keys(EXACT_TRANSLATIONS).sort((a, b) => b.length - a.length);

  /**
   * Traduit une chaîne de caractères textuelle.
   */
  function translate(text) {
    if (!text || typeof text !== 'string') return text;
    const trimmed = text.trim();
    if (!trimmed) return text;

    // 1. Correspondance exacte (insensible à la casse)
    const lower = trimmed.toLowerCase();
    for (const key of SORTED_EXACT_KEYS) {
      if (lower === key.toLowerCase()) {
        const replacement = EXACT_TRANSLATIONS[key];
        // Conserver les espaces originaux avant/après
        return text.replace(trimmed, replacement);
      }
    }

    // 2. Remplacement par expressions régulières / préfixes
    let result = text;
    for (const [pattern, replacement] of PREFIX_REPLACEMENTS) {
      if (pattern.test(result)) {
        result = result.replace(pattern, replacement);
      }
    }

    return result;
  }

  /**
   * Parcourt les nœuds texte et les attributs d'un élément pour traduire et masquer les bannières.
   */
  function translateElement(root) {
    if (!root) return;

    // Masquer immédiatement les bannières 'investigational use' et 'Sélection conservatrice'
    if (root.querySelectorAll) {
      const candidates = root.querySelectorAll('div, p, span, button');
      for (let i = 0; i < candidates.length; i++) {
        const el = candidates[i];
        const text = el.textContent || '';
        if (text.includes('investigational use only') || text.includes('Confirm and hide')) {
          if (el.tagName === 'BUTTON' && text.includes('Confirm and hide')) {
            try { el.click(); } catch (e) {}
          }
          const banner = el.closest('[class*="banner"], [class*="alert"], [class*="dialog"], [class*="warning"], [class*="notification"]') || el;
          banner.style.display = 'none';
        }
        if (text.includes('Sélection conservatrice')) {
          el.style.display = 'none';
        }
      }
    }

    // Nœuds texte
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    let node;
    while ((node = walker.nextNode())) {
      const original = node.nodeValue;
      if (!original || !original.trim()) continue;
      const translated = translate(original);
      if (translated !== original) {
        node.nodeValue = translated;
      }
    }

    // Attributs aria-label et title
    if (root.querySelectorAll) {
      const titledElements = root.querySelectorAll('[title], [aria-label], [placeholder]');
      for (let i = 0; i < titledElements.length; i++) {
        const el = titledElements[i];
        if (el.title) {
          const t = translate(el.title);
          if (t !== el.title) el.title = t;
        }
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) {
          const t = translate(ariaLabel);
          if (t !== ariaLabel) el.setAttribute('aria-label', t);
        }
        const placeholder = el.getAttribute('placeholder');
        if (placeholder) {
          const t = translate(placeholder);
          if (t !== placeholder) el.setAttribute('placeholder', t);
        }
      }
    }
  }

  // ── MutationObserver pour les modifications dynamiques du DOM ───────────────
  let debounceTimer = null;

  const observer = new MutationObserver((mutations) => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            translateElement(node);
          } else if (node.nodeType === Node.TEXT_NODE) {
            const original = node.nodeValue;
            if (original && original.trim()) {
              const translated = translate(original);
              if (translated !== original) {
                node.nodeValue = translated;
              }
            }
          }
        }
      }
    }, 40);
  });

  function startObserver() {
    if (document.body) {
      observer.observe(document.body, {
        childList: true,
        subtree: true,
      });
      translateElement(document.body);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startObserver);
  } else {
    startObserver();
  }
})();
