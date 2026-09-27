// Portee des labelmaps de pile : sur une photo de fond d'oeil (modalite OP),
// un labelmap ne s'affiche que sur l'image dont il est derive.
//
// Pourquoi. Les instances OP n'ont ni ImagePositionPatient ni
// ImageOrientationPatient : OHIF leur donne a toutes la meme geometrie par
// defaut (position 0,0,0), et inject_op_geometry ecrit aussi 0\0\0 partout.
// Or Cornerstone decide qu'un labelmap "se superpose" a une image
// (SegmentationStateManager._updateLabelmapSegmentationReferences ->
// StackViewport.isReferenceViewable {asOverlay} -> matchImagesForOverlay) en
// comparant seulement orientation, position et taille. Tout labelmap de meme
// taille correspond donc a toute photo : le masque IA de la photo analysee
// etait dessine aussi sur l'autre photo de la serie (a de faux endroits, les
// photos ne sont pas recalees), ou la gomme ne pouvait pas l'effacer.
//
// Correctif. On ne touche pas a l'appariement lui-meme : OHIF s'en sert
// (handleStackViewportCase) pour decider d'une conversion pile -> volume. On
// filtre ce qu'on en LIT, au point de passage unique de tous les
// consommateurs : defaultSegmentationStateManager
// .getCurrentLabelmapImageIdsForViewport. Il alimente le rendu, l'ajout et le
// retrait des acteurs a chaque changement d'image, la mise a jour des acteurs
// apres une modification, les brosses natives et nos outils. Sur une pile OP,
// un labelmap n'y reste que si son referencedImageId est l'image affichee
// (meme chaine, meme URI, ou meme SOPInstanceUID + frame). Un labelmap dont
// la source est inconnue est garde : le filtre ne masque que ce qui est
// prouve etranger. Toute autre vue ou modalite recoit la liste d'origine.
//
// Pose des le demarrage (preRegistration), avant toute etude ou SEG. Un filet
// de securite retire les acteurs etrangers deja presents (pose tardive) et
// repasse a chaque SEGMENTATION_RENDERED.
//
// Coupe-circuit : window.config.ownImageLabelmaps = false (puis recharger),
// ou en console window.__teleophOwnImageLabelmaps.disable() (temporaire,
// .enable() pour revenir) ou .uninstall() (definitif jusqu'au rechargement).

const OWN_IMAGE_MODALITIES = ['OP'];
const HANDLE_KEY = '__teleophOwnImageLabelmaps';
const LOG_PREFIX = '[OverlayScope]';
const MAX_LOGGED_HIDDEN = 200;
const MAX_MEMO = 5000;

let core = null;
let handle = null;
let installing = null;
let enabled = true;
let disabledByConfig = false;
// uninstall() en console doit tenir jusqu'au rechargement : sinon le prochain
// outil (loadCornerstone) reinstallerait le filtre sans que personne le voie.
let uninstalledByOperator = false;

const referencedMemo = new Map(); // labelmap imageId -> imageId source (positifs seulement)
const modalityMemo = new Map(); // imageId -> modalite (seulement si les metadonnees existent)
const sameImageMemo = new Map(); // "a\u0001b" -> boolean
const loggedHidden = new Set(); // segmentation|labelmap|image affichee -> deja journalise

function remember(map, key, value) {
  if (map.size >= MAX_MEMO) map.clear();
  map.set(key, value);
}

function referencedOf(labelmapImageId) {
  if (!core || typeof labelmapImageId !== 'string' || !labelmapImageId) return null;
  if (referencedMemo.has(labelmapImageId)) return referencedMemo.get(labelmapImageId);
  let source = null;
  try {
    source = core.cache.getImage(labelmapImageId)?.referencedImageId || null;
  } catch (_) {
    source = null;
  }
  // Une image absente du cache peut y arriver plus tard : seuls les
  // resultats positifs sont memorises.
  if (source) remember(referencedMemo, labelmapImageId, source);
  return source;
}

function modalityOf(imageId) {
  if (!core || typeof imageId !== 'string' || !imageId) return null;
  if (modalityMemo.has(imageId)) return modalityMemo.get(imageId);
  let seriesModule = null;
  try {
    seriesModule = core.metaData.get('generalSeriesModule', imageId);
  } catch (_) {
    seriesModule = null;
  }
  // Metadonnees pas encore chargees : on ne memorise pas, on redemandera.
  if (!seriesModule) return null;
  const modality = seriesModule.modality ? String(seriesModule.modality).toUpperCase() : null;
  remember(modalityMemo, imageId, modality);
  return modality;
}

function toUri(imageId) {
  try {
    const uri = core?.utilities?.imageIdToURI?.(imageId);
    return uri || imageId;
  } catch (_) {
    return imageId;
  }
}

function sopKey(imageId) {
  try {
    const sop = core.metaData.get('generalImageModule', imageId)?.sopInstanceUID;
    if (!sop) return null;
    const match = /\/frames\/(\d+)/.exec(imageId) || /[?&]frame=(\d+)/.exec(imageId);
    return `${sop}#${match ? match[1] : '1'}`;
  } catch (_) {
    return null;
  }
}

function sameImage(a, b) {
  if (!a || !b) return false;
  if (a === b) return true;
  const key = `${a}\u0001${b}`;
  if (sameImageMemo.has(key)) return sameImageMemo.get(key);
  let same = toUri(a) === toUri(b);
  if (!same) {
    const keyA = sopKey(a);
    same = !!keyA && keyA === sopKey(b);
  }
  remember(sameImageMemo, key, same);
  return same;
}

// Vrai quand l'image est une photo OP et que le filtrage est actif.
export function isOwnImageScope(imageId) {
  if (!handle || !enabled || disabledByConfig) return false;
  return OWN_IMAGE_MODALITIES.indexOf(modalityOf(imageId)) !== -1;
}

// Vrai seulement si c'est PROUVE : l'image affichee est une photo OP, le
// labelmap est derive d'une image connue, et ce n'est pas celle-ci.
export function isForeignLabelmap(labelmapImageId, imageId) {
  if (!labelmapImageId || !imageId || !isOwnImageScope(imageId)) return false;
  const source = referencedOf(labelmapImageId);
  return !!source && !sameImage(source, imageId);
}

function noteHidden(stats, segmentationId, labelmapImageId, currentImageId) {
  stats.hidden += 1;
  const key = `${segmentationId}|${labelmapImageId}|${currentImageId}`;
  if (loggedHidden.has(key) || loggedHidden.size >= MAX_LOGGED_HIDDEN) return;
  loggedHidden.add(key);
  console.log(
    LOG_PREFIX, "labelmap d'une autre photo masque | segmentation=", segmentationId,
    '| labelmap=', labelmapImageId,
    '| derive de=', referencedOf(labelmapImageId),
    '| image affichee=', currentImageId
  );
}

function install(csCore, csTools) {
  core = csCore;
  const manager = csTools?.segmentation?.defaultSegmentationStateManager;
  const proto = manager ? Object.getPrototypeOf(manager) : null;
  const original = proto?.getCurrentLabelmapImageIdsForViewport;
  if (!manager || typeof original !== 'function' || typeof csCore?.StackViewport !== 'function') {
    console.error(
      LOG_PREFIX, 'API Cornerstone introuvable (defaultSegmentationStateManager'
      + '.getCurrentLabelmapImageIdsForViewport) : filtrage NON actif, les masques'
      + " d'une photo peuvent s'afficher sur une autre."
    );
    return null;
  }
  if (manager[HANDLE_KEY]) {
    handle = manager[HANDLE_KEY];
    return handle;
  }

  const stats = { hidden: 0, pruned: 0 };
  const labelmapType = csTools?.Enums?.SegmentationRepresentations?.Labelmap || 'Labelmap';
  const labelmapTag = `-${labelmapType}-`;

  const scopedViewport = viewport => {
    if (!enabled || !(viewport instanceof csCore.StackViewport)) return null;
    const currentImageId = viewport.getCurrentImageId?.();
    if (!currentImageId || !isOwnImageScope(currentImageId)) return null;
    return currentImageId;
  };

  const filterList = (raw, viewportId, segmentationId) => {
    if (!enabled || !Array.isArray(raw) || raw.length === 0) return raw;
    const viewport = csCore.getEnabledElementByViewportId(viewportId)?.viewport;
    const currentImageId = scopedViewport(viewport);
    if (!currentImageId) return raw;
    let kept = null;
    for (let i = 0; i < raw.length; i++) {
      const id = raw[i];
      if (isForeignLabelmap(id, currentImageId)) {
        if (!kept) kept = raw.slice(0, i);
        noteHidden(stats, segmentationId, id, currentImageId);
      } else if (kept) {
        kept.push(id);
      }
    }
    // Toujours un tableau : jamais undefined la ou il y avait une liste, sinon
    // getCurrentLabelmapImageIdForViewport ferait imageIds[0] sur undefined.
    return kept || raw;
  };

  // Propriete propre de l'instance : elle masque la methode du prototype,
  // que les fonctions de module de Cornerstone appellent via l'instance.
  manager.getCurrentLabelmapImageIdsForViewport = function scopedGetCurrentLabelmapImageIdsForViewport(
    viewportId,
    segmentationId
  ) {
    const raw = original.call(this, viewportId, segmentationId);
    try {
      return filterList(raw, viewportId, segmentationId);
    } catch (_) {
      return raw;
    }
  };

  // Filet de securite : retire les acteurs de labelmap PROUVES etrangers a
  // l'image affichee (poses avant le filtre, ou par une voie inconnue).
  // Jamais un acteur de l'image elle-meme ni un acteur de source inconnue.
  const pruneViewport = viewport => {
    const currentImageId = scopedViewport(viewport);
    if (!currentImageId) return 0;
    const stale = [];
    (viewport.getActors?.() || []).forEach(entry => {
      const representationUID = entry?.representationUID;
      if (typeof representationUID !== 'string' || representationUID.indexOf(labelmapTag) === -1) return;
      if (isForeignLabelmap(entry.referencedId, currentImageId)) stale.push(entry.uid);
    });
    if (!stale.length) return 0;
    viewport.removeActors(stale);
    viewport.render?.();
    stats.pruned += stale.length;
    console.log(
      LOG_PREFIX, stale.length, "acteur(s) de labelmap d'une autre photo retire(s) de", viewport.id,
      '| image affichee=', currentImageId
    );
    return stale.length;
  };
  const pruneAll = () => {
    let removed = 0;
    let engines = [];
    try {
      engines = csCore.getRenderingEngines?.() || [];
    } catch (_) {
      engines = [];
    }
    engines.forEach(engine => {
      try {
        (engine?.getViewports?.() || []).forEach(viewport => {
          try {
            removed += pruneViewport(viewport);
          } catch (_) {
            // une vue en cours de destruction ne doit rien casser
          }
        });
      } catch (_) {
        // moteur de rendu detruit entre-temps
      }
    });
    return removed;
  };
  const renderedEvent = csTools?.Enums?.Events?.SEGMENTATION_RENDERED
    || 'CORNERSTONE_TOOLS_SEGMENTATION_RENDERED';
  const onSegmentationRendered = evt => {
    try {
      const viewport = csCore.getEnabledElementByViewportId(evt?.detail?.viewportId)?.viewport;
      if (viewport) pruneViewport(viewport);
    } catch (_) {
      // diagnostic seulement
    }
  };
  csCore.eventTarget?.addEventListener?.(renderedEvent, onSegmentationRendered);

  const api = {
    stats,
    modalities: OWN_IMAGE_MODALITIES.slice(),
    isForeignLabelmap,
    pruneAll,
    // Les calques etrangers reviennent au prochain changement d'image.
    disable() {
      enabled = false;
    },
    enable() {
      enabled = true;
      return pruneAll();
    },
    uninstall() {
      uninstalledByOperator = true;
      enabled = true;
      delete manager.getCurrentLabelmapImageIdsForViewport;
      csCore.eventTarget?.removeEventListener?.(renderedEvent, onSegmentationRendered);
      delete manager[HANDLE_KEY];
      try {
        delete window[HANDLE_KEY];
      } catch (_) {
        // rien a nettoyer
      }
      handle = null;
      installing = null;
      console.log(
        LOG_PREFIX,
        "desinstalle jusqu'au rechargement de la page : les labelmaps de toutes les photos s'affichent a nouveau"
      );
    },
  };
  manager[HANDLE_KEY] = api;
  handle = api;
  try {
    window[HANDLE_KEY] = api;
  } catch (_) {
    // diagnostic seulement
  }
  console.log(
    LOG_PREFIX, 'actif : sur une pile', OWN_IMAGE_MODALITIES.join(','),
    "chaque labelmap ne s'affiche que sur l'image dont il est derive"
    + ' (filtre getCurrentLabelmapImageIdsForViewport)'
  );
  // Pose tardive : des acteurs etrangers peuvent deja etre affiches.
  pruneAll();
  return api;
}

// Idempotent : preRegistration l'appelle au demarrage, loadCornerstone() de
// getCommandsModule le rappelle (seconde chance). Ne rejette jamais.
export function installOwnImageLabelmapFilter() {
  if (disabledByConfig || uninstalledByOperator) return Promise.resolve(null);
  if (!installing) {
    installing = Promise.all([import('@cornerstonejs/core'), import('@cornerstonejs/tools')])
      .then(([csCore, csTools]) => install(csCore, csTools))
      .catch(err => {
        console.warn(LOG_PREFIX, 'filtrage non installe', err);
        installing = null;
        return null;
      });
  }
  return installing;
}

export function disableOwnImageLabelmapFilterByConfig() {
  disabledByConfig = true;
  console.log(LOG_PREFIX, 'desactive par la configuration (ownImageLabelmaps: false)');
}
