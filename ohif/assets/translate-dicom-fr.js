/**
 * translate-dicom-fr.js
 * Traduit automatiquement les descriptions DICOM anglaises → françaises
 * dans l'interface OHIF via un MutationObserver.
 */
(function () {
  'use strict';

  // ── Dictionnaire EN → FR ────────────────────────────────────────────────────
  const TRANSLATIONS = {
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
    'Optical Coherence Tomography':        'Tomographie par cohérence optique',
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
    'Age-Related Macular Degeneration':    'Dégénérescence maculaire liée à l\'âge',
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
    // Descriptions courtes de séries
    'Right Eye':   'Œil droit',
    'Left Eye':    'Œil gauche',
    'OD':          'OD (Œil droit)',
    'OS':          'OS (Œil gauche)',
    'OU':          'OU (Les deux yeux)',
  };

  // Clés triées par longueur décroissante pour éviter les substitutions partielles
  const SORTED_KEYS = Object.keys(TRANSLATIONS).sort((a, b) => b.length - a.length);

  /**
   * Traduit un texte en cherchant chaque clé du dictionnaire (insensible à la casse).
   * @param {string} text
   * @returns {string}
   */
  function translate(text) {
    if (!text || typeof text !== 'string') return text;
    const trimmed = text.trim();
    for (const key of SORTED_KEYS) {
      if (trimmed.toLowerCase() === key.toLowerCase()) {
        return TRANSLATIONS[key];
      }
    }
    return text;
  }

  /**
   * Parcourt les nœuds texte d'un élément et applique la traduction.
   * @param {Element} root
   */
  function translateTextNodes(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    let node;
    while ((node = walker.nextNode())) {
      const original = node.nodeValue;
      if (!original || !original.trim()) continue;
      const translated = translate(original.trim());
      if (translated !== original.trim()) {
        node.nodeValue = translated;
      }
    }
  }

  // ── MutationObserver ────────────────────────────────────────────────────────
  let debounceTimer = null;

  const observer = new MutationObserver((mutations) => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            translateTextNodes(node);
          }
        }
      }
    }, 50);
  });

  function startObserver() {
    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });
    // Traduction initiale du contenu déjà présent
    translateTextNodes(document.body);
  }

  if (document.body) {
    startObserver();
  } else {
    document.addEventListener('DOMContentLoaded', startObserver);
  }
})();
