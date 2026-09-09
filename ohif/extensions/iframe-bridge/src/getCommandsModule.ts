export default function getCommandsModule({ servicesManager, commandsManager }) {
  const { uiNotificationService } = servicesManager.services;

  const claheOverlays = new Map();
  const foveaOverlays = new Map();
  const editSessions = new Map(); // viewportId -> { mode: 'erase'|'pencil', cleanup }
  const undoStacks = new Map(); // segmentationId -> Map<offset, oldValue>[]
  const redoStacks = new Map();
  const originalSnapshots = new Map(); // segmentationId -> pristine scalarData snapshot
  const brushCursors = new Map(); // viewportId -> { svg, circle }
  const usedModesThisSession = new Set(); // 'erase' | 'pencil', reset on save
  let foveaMarkers = [];
  let foveaVisible = false;
  // Crayon and Gomme keep independent brush sizes (in canvas pixels). They
  // persist in localStorage so the doctor's preferred sizes survive reloads.
  const BRUSH_MIN = 1;
  const BRUSH_MAX = 120;
  const BRUSH_STEP = 1;
  const BRUSH_STORAGE_KEY = 'teleophtalmo.segmentation.brushSizes';
  const brushPanels = new Map(); // viewportId -> { panel, refresh }
  const brushSizes = loadBrushSizes();
  // "Baguette" (magic wand): one click on a lesion, seeded region growing on the
  // fundus image fills the whole lesion. Two doctor-facing settings, persisted.
  const WAND_STORAGE_KEY = 'teleophtalmo.segmentation.wand';
  const WAND_LIMITS = { tolerance: [1, 80], radius: [1, 150], edges: [0, 99], flatten: [0, 1], colour: [0, 100] };
  const WAND_DEFAULTS = { tolerance: 12, radius: 40, edges: 90, flatten: 1, colour: 60 };
  // A haemorrhage and a vessel can share the same green luminance and still
  // differ in hue. This weight is how much the CIELAB chroma counts in the
  // similarity distance; at 0 the wand behaves exactly as it did before.
  const WAND_COLOUR = 1;
  // The acceptance threshold is max(tolerance, K_SIGMA * sigma of the region):
  // the slider is a floor, and a noisy or heterogeneous lesion widens it on its
  // own instead of forcing the doctor to retune.
  const WAND_K_SIGMA = 2.5;
  // Hysteresis, as in the Canny detector: a strict threshold defines a core we
  // are confident about, then a loose one (this multiple of the strict one) is
  // allowed, but only for pixels hanging on that core and no further than
  // BAND pixels away from it.
  const WAND_HYSTERESIS_RATIO = 1.8;
  const WAND_HYSTERESIS_BAND = 3; // px
  const WAND_MAX_ERASE_COMPONENT = 250000; // px, guards Alt+click on a vessel tree
  const WAND_MAX_BOX_HALF = 400; // px, caps the working box of a very long stroke
  // A stroke that comes back to its starting point is read as an outline and
  // filled, rather than used as seeds. Closing tolerance is generous, since a
  // hand-drawn loop rarely lands exactly on its own start.
  const LASSO_CLOSE_PX = 18;
  const LASSO_MIN_POINTS = 6;
  const LASSO_MAX_HALF = 1200; // px, guards the memory of an enormous outline
  const wandPanels = new Map(); // viewportId -> { panel, refresh }
  const wandPreviews = new Map(); // viewportId -> { canvas }
  const wandSettings = loadWandSettings();
  let csCore = null;

  function clampWandSetting(key, value) {
    const [min, max] = WAND_LIMITS[key];
    const n = Number(value);
    if (!Number.isFinite(n)) return WAND_DEFAULTS[key];
    return Math.max(min, Math.min(max, Math.round(n)));
  }

  function loadWandSettings() {
    try {
      const saved = JSON.parse(window.localStorage.getItem(WAND_STORAGE_KEY) || '{}');
      return {
        tolerance: clampWandSetting('tolerance', saved.tolerance ?? WAND_DEFAULTS.tolerance),
        radius: clampWandSetting('radius', saved.radius ?? WAND_DEFAULTS.radius),
        edges: clampWandSetting('edges', saved.edges ?? WAND_DEFAULTS.edges),
        flatten: clampWandSetting('flatten', saved.flatten ?? WAND_DEFAULTS.flatten),
        colour: clampWandSetting('colour', saved.colour ?? WAND_DEFAULTS.colour),
      };
    } catch (_) {
      return { ...WAND_DEFAULTS };
    }
  }

  function getWandSetting(key) {
    return wandSettings[key] ?? WAND_DEFAULTS[key];
  }

  function setWandSetting(key, value) {
    const next = clampWandSetting(key, value);
    if (next === wandSettings[key]) return next;
    wandSettings[key] = next;
    try {
      window.localStorage.setItem(WAND_STORAGE_KEY, JSON.stringify(wandSettings));
    } catch (_) {
      // storage unavailable -- keep the in-memory value
    }
    wandPanels.forEach(record => record.refresh());
    editSessions.forEach(session => {
      if (session.mode === 'wand') session.onSettingsChanged?.();
    });
    return next;
  }

  function clampBrushSize(value, fallback) {
    const n = Number(value);
    if (!Number.isFinite(n)) return fallback;
    return Math.max(BRUSH_MIN, Math.min(BRUSH_MAX, Math.round(n)));
  }

  function loadBrushSizes() {
    const defaults = { pencil: 12, erase: 24 };
    try {
      const saved = JSON.parse(window.localStorage.getItem(BRUSH_STORAGE_KEY) || '{}');
      return {
        pencil: clampBrushSize(saved.pencil, defaults.pencil),
        erase: clampBrushSize(saved.erase, defaults.erase),
      };
    } catch (_) {
      return defaults;
    }
  }

  function getBrushSize(mode) {
    return brushSizes[mode] ?? (mode === 'pencil' ? 12 : 24);
  }

  function setBrushSize(mode, value) {
    const next = clampBrushSize(value, getBrushSize(mode));
    if (next === brushSizes[mode]) return next;
    brushSizes[mode] = next;
    try {
      window.localStorage.setItem(BRUSH_STORAGE_KEY, JSON.stringify(brushSizes));
    } catch (_) {
      // storage may be unavailable (private mode) -- size still applies for this session
    }
    brushPanels.forEach(record => {
      if (record.mode === mode) record.refresh();
    });
    editSessions.forEach(session => {
      if (session.mode === mode) session.applyRadius?.();
    });
    return next;
  }
  let csTools = null;

  async function loadCornerstone() {
    if (!csCore) csCore = await import('@cornerstonejs/core');
    if (!csTools) csTools = await import('@cornerstonejs/tools');
    return { csCore, csTools };
  }

  function removeFoveaOverlays() {
    foveaOverlays.forEach(({ element, render, resizeObserver, svg }) => {
      element.removeEventListener('CORNERSTONE_IMAGE_RENDERED', render);
      element.removeEventListener('CORNERSTONE_NEW_IMAGE', render);
      resizeObserver?.disconnect();
      svg.remove();
    });
    foveaOverlays.clear();
  }

  function markerForViewport(viewport) {
    const imageId = decodeURIComponent(viewport?.getCurrentImageId?.() || '');
    return foveaMarkers.find(marker =>
      marker.sop_instance_uid && imageId.includes(marker.sop_instance_uid)
    );
  }

  function drawFoveaMarker(viewportId, viewport) {
    const element = viewport?.element;
    if (!element) return;

    let record = foveaOverlays.get(viewportId);
    if (!record) {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('aria-label', 'Localisation de la fovéa');
      Object.assign(svg.style, {
        position: 'absolute', inset: '0', width: '100%', height: '100%',
        pointerEvents: 'none', zIndex: '9', overflow: 'visible',
      });
      element.appendChild(svg);
      const render = () => requestAnimationFrame(() => drawFoveaMarker(viewportId, viewport));
      element.addEventListener('CORNERSTONE_IMAGE_RENDERED', render);
      element.addEventListener('CORNERSTONE_NEW_IMAGE', render);
      const resizeObserver = typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(render)
        : null;
      resizeObserver?.observe(element);
      record = { element, render, resizeObserver, svg };
      foveaOverlays.set(viewportId, record);
    }

    const { svg } = record;
    svg.replaceChildren();
    const marker = markerForViewport(viewport);
    if (!foveaVisible || !marker) return;

    const imageDataResult = viewport.getImageData?.();
    const imageData = imageDataResult?.imageData || imageDataResult;
    let canvasPoint;
    try {
      let imageX = marker.x_px;
      let imageY = marker.y_px;
      const dimensions = imageData?.getDimensions?.();
      // VascX receives these OP DICOMs through PIL as portrait arrays, while
      // Cornerstone exposes their stored DICOM matrix in landscape orientation.
      // Detect that exact transposition from dimensions instead of assuming it
      // for every image type.
      const isTransposed = dimensions?.length >= 2
        && dimensions[0] === marker.source_height
        && dimensions[1] === marker.source_width
        && marker.source_width !== marker.source_height;
      if (isTransposed) {
        imageX = marker.y_px;
        imageY = marker.x_px;
      }
      const worldPoint = imageData?.indexToWorld?.([imageX, imageY, 0]);
      canvasPoint = worldPoint
        ? viewport.worldToCanvas?.(worldPoint)
        : viewport.indexToCanvas?.([imageX, imageY, 0]);
    } catch (_) {
      return;
    }
    if (!canvasPoint || !canvasPoint.every(Number.isFinite)) return;

    const width = Math.max(1, element.clientWidth);
    const height = Math.max(1, element.clientHeight);
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const [x, y] = canvasPoint;
    const half = 7;
    [[x - half, y - half, x + half, y + half], [x + half, y - half, x - half, y + half]]
      .forEach(points => {
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', String(points[0]));
        line.setAttribute('y1', String(points[1]));
        line.setAttribute('x2', String(points[2]));
        line.setAttribute('y2', String(points[3]));
        line.setAttribute('stroke', '#ffffff');
        line.setAttribute('stroke-width', '4');
        line.setAttribute('stroke-linecap', 'round');
        line.style.filter = 'drop-shadow(0 0 2px #000)';
        svg.appendChild(line);
      });
  }

  function renderFoveaOverlays() {
    const { viewportGridService, cornerstoneViewportService } = servicesManager.services;
    const viewportId = viewportGridService.getState()?.activeViewportId;
    if (!viewportId) return;
    const viewport = cornerstoneViewportService.getCornerstoneViewport(viewportId);
    drawFoveaMarker(viewportId, viewport);
  }

  function applyClahe(source, target, tiles = 8, clipLimit = 2) {
    const width = source.width;
    const height = source.height;
    const scratch = document.createElement('canvas');
    scratch.width = width;
    scratch.height = height;
    const sourceContext = scratch.getContext('2d', { willReadFrequently: true });
    const targetContext = target.getContext('2d');
    sourceContext.drawImage(source, 0, 0, width, height);
    const image = sourceContext.getImageData(0, 0, width, height);
    const output = new ImageData(width, height);
    const tileWidth = Math.ceil(width / tiles);
    const tileHeight = Math.ceil(height / tiles);
    const luts = [];

    for (let ty = 0; ty < tiles; ty++) {
      luts[ty] = [];
      for (let tx = 0; tx < tiles; tx++) {
        const histogram = new Uint32Array(256);
        const x0 = tx * tileWidth;
        const y0 = ty * tileHeight;
        const x1 = Math.min(x0 + tileWidth, width);
        const y1 = Math.min(y0 + tileHeight, height);
        const pixels = Math.max(1, (x1 - x0) * (y1 - y0));
        for (let y = y0; y < y1; y++) {
          for (let x = x0; x < x1; x++) {
            const i = (y * width + x) * 4;
            const luminance = Math.round(
              image.data[i] * 0.299 + image.data[i + 1] * 0.587 + image.data[i + 2] * 0.114
            );
            histogram[luminance]++;
          }
        }
        const limit = Math.max(1, Math.round((clipLimit * pixels) / 256));
        let excess = 0;
        for (let i = 0; i < 256; i++) {
          if (histogram[i] > limit) {
            excess += histogram[i] - limit;
            histogram[i] = limit;
          }
        }
        const increment = Math.floor(excess / 256);
        const remainder = excess % 256;
        for (let i = 0; i < 256; i++) histogram[i] += increment + (i < remainder ? 1 : 0);
        const lut = new Uint8Array(256);
        let cumulative = 0;
        for (let i = 0; i < 256; i++) {
          cumulative += histogram[i];
          lut[i] = Math.min(255, Math.round((cumulative * 255) / pixels));
        }
        luts[ty][tx] = lut;
      }
    }

    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        const i = (y * width + x) * 4;
        const luminance = Math.round(
          image.data[i] * 0.299 + image.data[i + 1] * 0.587 + image.data[i + 2] * 0.114
        );
        // Interpolate the four neighbouring tile LUTs. Applying only the LUT
        // of the current tile creates visible square boundaries.
        const gridX = x / tileWidth - 0.5;
        const gridY = y / tileHeight - 0.5;
        const left = Math.max(0, Math.min(tiles - 1, Math.floor(gridX)));
        const top = Math.max(0, Math.min(tiles - 1, Math.floor(gridY)));
        const right = Math.min(tiles - 1, left + 1);
        const bottom = Math.min(tiles - 1, top + 1);
        const weightX = gridX <= 0 ? 0 : Math.max(0, Math.min(1, gridX - Math.floor(gridX)));
        const weightY = gridY <= 0 ? 0 : Math.max(0, Math.min(1, gridY - Math.floor(gridY)));
        const topValue =
          luts[top][left][luminance] * (1 - weightX) +
          luts[top][right][luminance] * weightX;
        const bottomValue =
          luts[bottom][left][luminance] * (1 - weightX) +
          luts[bottom][right][luminance] * weightX;
        const enhanced = topValue * (1 - weightY) + bottomValue * weightY;
        const ratio = enhanced / Math.max(1, luminance);
        output.data[i] = Math.min(255, image.data[i] * ratio);
        output.data[i + 1] = Math.min(255, image.data[i + 1] * ratio);
        output.data[i + 2] = Math.min(255, image.data[i + 2] * ratio);
        output.data[i + 3] = image.data[i + 3];
      }
    }
    targetContext.putImageData(output, 0, 0);
  }

  // Our own overlays (CLAHE, wand preview) are canvases appended to the same
  // element, so they must never be mistaken for the Cornerstone canvas.
  function findViewportCanvas(element) {
    if (!element) return null;
    return Array.from(element.querySelectorAll('canvas')).find(
      canvas =>
        canvas.width > 0 &&
        canvas.height > 0 &&
        !canvas.hasAttribute('data-teleoph-overlay')
    );
  }

  function sendToParent(type, payload = {}) {
    try {
      if (window.parent && window.parent !== window) {
        window.parent.postMessage(
          { type: `ohif-bridge:${type}`, ...payload },
          '*'
        );
      }
    } catch (e) {
      // cross-origin errors silently ignored
    }
  }

  function getActiveViewport() {
    const { viewportGridService, cornerstoneViewportService } = servicesManager.services;
    const { activeViewportId } = viewportGridService.getState();
    return {
      activeViewportId,
      viewport: cornerstoneViewportService.getCornerstoneViewport(activeViewportId),
    };
  }

  function getActiveLabelmapVolume(segmentationId) {
    if (typeof segmentationId !== 'string' || !segmentationId) return undefined;
    const { segmentationService } = servicesManager.services;
    try {
      return segmentationService?.getLabelmapVolume?.(segmentationId);
    } catch (_) {
      return undefined;
    }
  }

  // OP/fundus studies are single 2D frames shown in stack viewports, so their
  // labelmaps are stack-based (representationData.Labelmap.imageIds) and
  // segmentationService.getLabelmapVolume() returns null for them. Wrap both
  // storage kinds behind one read/write accessor.
  function getLabelmapAccessor(segmentationId, viewportId, viewport) {
    if (typeof segmentationId !== 'string' || !segmentationId) return null;
    const { segmentationService } = servicesManager.services;

    const volume = getActiveLabelmapVolume(segmentationId);
    if (volume?.voxelManager) {
      return {
        kind: 'volume',
        segmentationId,
        getScalarData: () => volume.voxelManager.getCompleteScalarDataArray?.(),
        setScalarData: data => volume.voxelManager.setCompleteScalarDataArray?.(data),
      };
    }

    const segmentation = segmentationService?.getSegmentation?.(segmentationId);
    const imageIds = segmentation?.representationData?.Labelmap?.imageIds;
    if (!imageIds?.length || !csCore?.cache) return null;

    let imageId = null;
    try {
      imageId = csTools?.segmentation?.state?.getCurrentLabelmapImageIdForViewport?.(
        viewportId,
        segmentationId
      );
    } catch (_) {
      imageId = null;
    }
    if (!imageId) {
      const index = viewport?.getCurrentImageIdIndex?.() ?? 0;
      imageId = imageIds[index] || imageIds[0];
    }
    const image = csCore.cache.getImage(imageId);
    if (!image) return null;
    const vm = image.voxelManager;
    return {
      kind: 'stack',
      segmentationId,
      imageId,
      getScalarData: () => (vm?.getScalarData ? vm.getScalarData() : image.getPixelData?.()),
      setScalarData: data => {
        if (vm?.setScalarData) vm.setScalarData(data);
      },
    };
  }

  // A study can have several SEG series loaded at once (one per model), each
  // as its own Cornerstone segmentation object with its own generated id --
  // there is no fixed '1'. Resolve the real id/segment the doctor currently
  // has selected (via OHIF's own SEG panel) instead of assuming one.
  function resolveActiveSegmentationId(viewportId) {
    const { segmentationService } = servicesManager.services;
    try {
      const activeSegmentation = segmentationService?.getActiveSegmentation?.(viewportId);
      return activeSegmentation?.segmentationId || null;
    } catch (_) {
      return null;
    }
  }

  function resolveActiveSegmentIndex(viewportId) {
    const { segmentationService } = servicesManager.services;
    try {
      return segmentationService?.getActiveSegment?.(viewportId)?.segmentIndex;
    } catch (_) {
      return undefined;
    }
  }

  // Editing tools shouldn't force the doctor to click into OHIF's native SEG
  // panel first just to mark a segmentation "active" -- if none is active yet,
  // default to the first one that is actually loaded for this study.
  function waitForActiveSegmentation(viewportId, timeoutMs = 6000) {
    return new Promise(resolve => {
      const startedAt = Date.now();
      const tick = () => {
        const id = ensureActiveSegmentationId(viewportId, true);
        if (id) return resolve(id);
        if (Date.now() - startedAt > timeoutMs) return resolve(null);
        setTimeout(tick, 300);
      };
      tick();
    });
  }

  // Classes of the doctor-drawn segmentation: every type shown in the viewer
  // legend. Indices 1-4 match the AI lesion_seg model (microaneurysms,
  // hemorrhages, hard exudates, soft exudates); the others follow.
  const DOCTOR_LESION_SEGMENTS = [
    { index: 1, label: 'Microanévrismes', color: [255, 50, 50, 255] },
    { index: 2, label: 'Hémorragies', color: [59, 130, 246, 255] },
    { index: 3, label: 'Exsudats', color: [255, 255, 255, 255] },
    { index: 4, label: 'Nodules cotonneux', color: [0, 255, 0, 255] },
    { index: 5, label: 'Néovascularisation', color: [255, 200, 0, 255] },
    { index: 6, label: 'Disque optique', color: [0, 180, 130, 255] },
    { index: 7, label: 'Excavation papillaire', color: [255, 80, 160, 255] },
    { index: 8, label: 'Vaisseaux', color: [168, 85, 247, 255] },
  ];

  // Create an empty labelmap on the image currently displayed so the doctor can
  // draw directly on it, without any AI SEG loaded. Uses the same OHIF service
  // calls as the "+ Add segmentation" button of the Segmentation panel.
  async function createEditableSegmentation(viewportId, modeLabel) {
    const { viewportGridService, displaySetService, segmentationService } = servicesManager.services;
    const state = viewportGridService?.getState?.();
    const viewportInfo = state?.viewports?.get?.(viewportId);
    const displaySetUid = viewportInfo?.displaySetInstanceUIDs?.[0];
    const displaySet = displaySetUid ? displaySetService?.getDisplaySetByUID?.(displaySetUid) : null;
    if (!displaySet) {
      uiNotificationService.show({
        title: modeLabel,
        message: "Impossible de trouver l'image affichée pour y créer une segmentation.",
        type: 'error',
        duration: 4000,
      });
      return null;
    }
    const segmentationId = `doctor-${Date.now()}`;
    const segments = {};
    DOCTOR_LESION_SEGMENTS.forEach(s => {
      segments[s.index] = { label: s.label, active: s.index === 2 };
    });
    console.log('[SegmentationEdit] creating editable segmentation', segmentationId, 'on', displaySetUid);
    await segmentationService.createLabelmapForDisplaySet(displaySet, {
      segmentationId,
      label: 'Lésions (médecin)',
      segments,
    });
    const type = csTools?.Enums?.SegmentationRepresentations?.Labelmap || 'Labelmap';
    await segmentationService.addSegmentationRepresentation(viewportId, { segmentationId, type });
    DOCTOR_LESION_SEGMENTS.forEach(s => {
      try {
        segmentationService.setSegmentColor(viewportId, segmentationId, s.index, s.color);
      } catch (err) {
        console.warn('[SegmentationEdit] setSegmentColor failed', s.index, err);
      }
    });
    try {
      segmentationService.setActiveSegmentation(viewportId, segmentationId);
    } catch (_) {
      // representation may still be settling; the poll below re-checks
    }
    try {
      segmentationService.setActiveSegment(segmentationId, 2);
    } catch (_) {
      // same
    }
    const id = await waitForActiveSegmentation(viewportId, 5000);
    return id || segmentationId;
  }

  // Nothing selected/loaded by the doctor -> draw directly on the image: create
  // an empty labelmap with the lesion classes, immediately. When the doctor has
  // loaded a SEG series (left list / CHARGER badge) this is never reached and
  // the tools work on that segmentation instead.
  async function loadSegmentationForEditing(viewportId, modeLabel) {
    try {
      const createdId = await createEditableSegmentation(viewportId, modeLabel);
      if (createdId) {
        uiNotificationService.show({
          title: modeLabel,
          message: 'Nouvelle segmentation « Lésions (médecin) » créée sur l\'image. Dessinez directement. Pour corriger la segmentation IA, sélectionnez d\'abord la série SEG à gauche.',
          type: 'success',
          duration: 4500,
        });
      }
      return createdId;
    } catch (err) {
      reportSegmentationError(modeLabel, 'create-segmentation', err);
      return null;
    }
  }

  function ensureActiveSegmentationId(viewportId, quiet = false) {
    const existing = resolveActiveSegmentationId(viewportId);
    if (existing) return existing;

    const { segmentationService } = servicesManager.services;
    try {
      const raw = segmentationService?.getSegmentations?.();
      // getSegmentations() has been observed to be a reactive/proxied array
      // whose Symbol.iterator is unreliable (Array.from/for...of silently
      // yield 0 items even though .length is correct) -- index by hand.
      const length = raw?.length ?? 0;
      let tried = 0;
      for (let i = 0; i < length; i++) {
        const entry = raw[i];
        const candidates = [entry?.segmentationId, entry?.id];
        for (const candidateId of candidates) {
          if (!candidateId) continue;
          tried++;
          try {
            segmentationService.setActiveSegmentation(viewportId, candidateId);
          } catch (setErr) {
            console.warn('[SegmentationEdit] setActiveSegmentation failed for', candidateId, setErr);
            continue;
          }
          const confirmed = resolveActiveSegmentationId(viewportId);
          if (confirmed) return confirmed;
          if (getActiveLabelmapVolume(candidateId)) return candidateId;
        }
      }
      if (!quiet) {
        console.warn(
          '[SegmentationEdit] No usable segmentation id found. length=', length, 'tried=', tried, 'raw=', raw
        );
      }
      return null;
    } catch (err) {
      console.error('[SegmentationEdit] ensureActiveSegmentationId failed:', err);
      return null;
    }
  }

  function currentStudyInstanceUid() {
    const query = new URLSearchParams(window.location.search);
    return query.get('StudyInstanceUIDs') || query.get('studyInstanceUids') || '';
  }

  function scalarOffsetFromCanvas(viewport, canvasX, canvasY) {
    const imageDataResult = viewport?.getImageData?.();
    const imageData = imageDataResult?.imageData || imageDataResult;
    if (!imageData) return null;

    const dimensions = imageData.getDimensions?.();
    if (!dimensions || dimensions.length < 2) return null;

    const world = viewport.canvasToWorld?.([canvasX, canvasY]);
    const index = world ? imageData.worldToIndex?.(world) : null;
    if (!index) return null;

    const i = Math.round(index[0]);
    const j = Math.round(index[1]);
    const k = Math.round(index[2] || 0);
    const width = dimensions[0];
    const height = dimensions[1];
    const depth = dimensions[2] || 1;
    if (i < 0 || j < 0 || k < 0 || i >= width || j >= height || k >= depth) {
      return null;
    }
    return i + j * width + k * width * height;
  }

  function notifySegmentationModified(segmentationId = '1') {
    import('@cornerstonejs/core').then(({ eventTarget, triggerEvent }) => {
      import('@cornerstonejs/tools').then(({ Enums }) => {
        triggerEvent(eventTarget, Enums.Events.SEGMENTATION_DATA_MODIFIED, {
          segmentationId,
        });
      });
    });
  }

  function paintAtCanvasPoint(viewport, accessor, canvasX, canvasY, brushSize, writeValue, strokeDiff) {
    const scalarData = accessor?.getScalarData?.();
    if (!scalarData) return 0;

    const radius = Math.max(0.5, brushSize / 2);
    const radiusSquared = radius * radius;
    const span = Math.max(0, Math.ceil(radius - 0.5));
    let changed = 0;

    for (let dy = -span; dy <= span; dy++) {
      for (let dx = -span; dx <= span; dx++) {
        if (dx * dx + dy * dy > radiusSquared) continue;
        const offset = scalarOffsetFromCanvas(viewport, canvasX + dx, canvasY + dy);
        if (offset == null) continue;
        const current = scalarData[offset];
        if (current === writeValue) continue;
        if (strokeDiff && !strokeDiff.has(offset)) {
          strokeDiff.set(offset, current);
        }
        scalarData[offset] = writeValue;
        changed++;
      }
    }

    if (changed) {
      accessor.setScalarData(scalarData);
      notifySegmentationModified(accessor.segmentationId);
      viewport?.render?.();
    }
    return changed;
  }

  function ensureOriginalSnapshot(accessor) {
    const segmentationId = accessor?.segmentationId;
    if (!segmentationId || originalSnapshots.has(segmentationId)) return;
    const scalarData = accessor.getScalarData?.();
    if (scalarData) {
      originalSnapshots.set(segmentationId, scalarData.slice());
    }
  }

  function pushUndoEntry(segmentationId, strokeDiff) {
    if (!strokeDiff || strokeDiff.size === 0) return;
    const stack = undoStacks.get(segmentationId) || [];
    stack.push(strokeDiff);
    undoStacks.set(segmentationId, stack);
    redoStacks.set(segmentationId, []);
  }

  // Toolbar commands are invoked by OHIF's CommandsManager with an options
  // *object* as first argument (never a bare id). Accept either shape and
  // fall back to the segmentation currently active in the viewport.
  async function resolveEditTarget(options) {
    await loadCornerstone();
    const { activeViewportId, viewport } = getActiveViewport();
    let segmentationId = null;
    if (typeof options === 'string') {
      segmentationId = options;
    } else if (options && typeof options.segmentationId === 'string') {
      segmentationId = options.segmentationId;
    }
    if (!segmentationId) {
      segmentationId = resolveActiveSegmentationId(activeViewportId) ||
        ensureActiveSegmentationId(activeViewportId);
    }
    const accessor = segmentationId
      ? getLabelmapAccessor(segmentationId, activeViewportId, viewport)
      : null;
    return { activeViewportId, viewport, segmentationId, accessor };
  }

  async function undoSegmentationEdit(options) {
    try {
      const { viewport, segmentationId, accessor } = await resolveEditTarget(options);
      const stack = segmentationId && undoStacks.get(segmentationId);
      if (!stack || !stack.length) {
        uiNotificationService.show({ title: 'Annuler', message: 'Rien à annuler.', type: 'info', duration: 1500 });
        return;
      }
      const scalarData = accessor?.getScalarData?.();
      if (!scalarData) {
        uiNotificationService.show({ title: 'Annuler', message: 'Pixels de la segmentation inaccessibles.', type: 'warning', duration: 2500 });
        return;
      }
      const strokeDiff = stack.pop();
      const redoDiff = new Map();
      strokeDiff.forEach((oldValue, offset) => {
        redoDiff.set(offset, scalarData[offset]);
        scalarData[offset] = oldValue;
      });
      accessor.setScalarData(scalarData);
      notifySegmentationModified(segmentationId);
      viewport?.render?.();
      const redoStack = redoStacks.get(segmentationId) || [];
      redoStack.push(redoDiff);
      redoStacks.set(segmentationId, redoStack);
    } catch (err) {
      reportSegmentationError('Annuler', 'undo', err);
    }
  }

  async function redoSegmentationEdit(options) {
    try {
      const { viewport, segmentationId, accessor } = await resolveEditTarget(options);
      const stack = segmentationId && redoStacks.get(segmentationId);
      if (!stack || !stack.length) {
        uiNotificationService.show({ title: 'Rétablir', message: 'Rien à rétablir.', type: 'info', duration: 1500 });
        return;
      }
      const scalarData = accessor?.getScalarData?.();
      if (!scalarData) {
        uiNotificationService.show({ title: 'Rétablir', message: 'Pixels de la segmentation inaccessibles.', type: 'warning', duration: 2500 });
        return;
      }
      const redoDiff = stack.pop();
      const undoDiff = new Map();
      redoDiff.forEach((newValue, offset) => {
        undoDiff.set(offset, scalarData[offset]);
        scalarData[offset] = newValue;
      });
      accessor.setScalarData(scalarData);
      notifySegmentationModified(segmentationId);
      viewport?.render?.();
      const undoStack = undoStacks.get(segmentationId) || [];
      undoStack.push(undoDiff);
      undoStacks.set(segmentationId, undoStack);
    } catch (err) {
      reportSegmentationError('Rétablir', 'redo', err);
    }
  }

  async function resetSegmentationToOriginal(options) {
    try {
      const { viewport, segmentationId, accessor } = await resolveEditTarget(options);
      const original = segmentationId && originalSnapshots.get(segmentationId);
      const scalarData = accessor?.getScalarData?.();
      console.log(
        '[SegmentationEdit] reset segmentationId=', segmentationId,
        'hasSnapshot=', !!original, 'accessor.kind=', accessor?.kind
      );
      if (!original) {
        uiNotificationService.show({
          title: 'Réinitialiser',
          message: 'Aucune modification à annuler pour cette segmentation.',
          type: 'info',
          duration: 2000,
        });
        return;
      }
      if (!scalarData) {
        uiNotificationService.show({
          title: 'Réinitialiser',
          message: 'Pixels de la segmentation inaccessibles.',
          type: 'warning',
          duration: 2500,
        });
        return;
      }
      if (original.length !== scalarData.length) {
        uiNotificationService.show({
          title: 'Réinitialiser',
          message: 'La segmentation active ne correspond pas à la version IA mémorisée.',
          type: 'warning',
          duration: 3000,
        });
        return;
      }
      scalarData.set(original);
      accessor.setScalarData(scalarData);
      notifySegmentationModified(segmentationId);
      viewport?.render?.();
      undoStacks.set(segmentationId, []);
      redoStacks.set(segmentationId, []);
      uiNotificationService.show({
        title: 'Réinitialiser',
        message: 'Masque restauré à la version IA initiale.',
        type: 'success',
        duration: 2000,
      });
    } catch (err) {
      reportSegmentationError('Réinitialiser', 'reset', err);
    }
  }

  // An AI DICOM-SEG only carries the classes it actually found: a lesion mask
  // with no cotton-wool spot has no segment 4 at all, so the doctor cannot draw
  // one. Declare the full class list of each model and add whatever is missing
  // to the loaded segmentation, so every class shows up in the Segmentations
  // panel and can be painted into.
  const SEGMENTATION_CLASS_SETS = [
    {
      match: /l[eé]sion/i,
      segments: [
        { index: 1, label: 'Microanévrismes', color: [255, 50, 50, 255] },
        { index: 2, label: 'Hémorragies', color: [59, 130, 246, 255] },
        { index: 3, label: 'Exsudats', color: [255, 255, 255, 255] },
        { index: 4, label: 'Nodules cotonneux', color: [0, 255, 0, 255] },
      ],
    },
    {
      match: /neovasc|néovasc/i,
      segments: [{ index: 1, label: 'Néovascularisation', color: [255, 200, 0, 255] }],
    },
    {
      match: /vaiss|vessel/i,
      segments: [{ index: 1, label: 'Vaisseaux', color: [168, 85, 247, 255] }],
    },
    {
      match: /optic|disc|exca|cup/i,
      segments: [
        { index: 1, label: 'Disque optique', color: [0, 180, 130, 255] },
        { index: 2, label: 'Excavation papillaire', color: [255, 80, 160, 255] },
      ],
    },
  ];

  function segmentationDisplayName(segmentation) {
    if (!segmentation) return '';
    return [
      segmentation.label,
      segmentation.cachedStats?.info,
      segmentation.segmentationId,
    ]
      .filter(Boolean)
      .join(' ');
  }

  function ensureAllSegmentClasses(segmentationId, viewportId) {
    const { segmentationService } = servicesManager.services;
    if (!segmentationId || !segmentationService?.addSegment) return 0;
    let segmentation = null;
    try {
      segmentation = segmentationService.getSegmentation(segmentationId);
    } catch (_) {
      return 0;
    }
    if (!segmentation) return 0;

    const name = segmentationDisplayName(segmentation);
    const set = SEGMENTATION_CLASS_SETS.find(entry => entry.match.test(name));
    // Unknown SEG kind: never invent classes for it.
    if (!set) return 0;

    const existing = segmentation.segments || {};
    const missing = set.segments.filter(item => !existing[item.index]);

    // addSegment() makes the new segment active; restore the doctor's choice.
    const previousActive = viewportId ? resolveActiveSegmentIndex(viewportId) : undefined;
    let added = 0;
    missing.forEach(item => {
      try {
        segmentationService.addSegment(segmentationId, {
          segmentIndex: item.index,
          label: item.label,
          color: item.color,
          visibility: true,
          isLocked: false,
        });
        added++;
      } catch (err) {
        console.warn('[SegmentationEdit] addSegment failed for', item.label, err);
      }
    });
    if (added) {
      console.log(
        '[SegmentationEdit] added', added, 'missing class(es) to', segmentationId,
        missing.map(item => item.label)
      );
      try {
        segmentationService.setActiveSegment(
          segmentationId,
          previousActive || set.segments[0].index
        );
      } catch (_) {
        // non fatal
      }
    }
    return added + realignSegmentAppearance(segmentationId, viewportId, set);
  }

  // A DICOM SEG carries the labels and the colours chosen by whatever wrote it.
  // Nothing forced those to agree with the legend drawn over the image, so the
  // same haemorrhage read blue on the left and grey on the right, and a hard
  // exudate came through as "Exsudats solides" in purple.
  //
  // The class set is the single source of truth. Every segment it declares is
  // realigned on it, whether it came from the file or was just added.
  function realignSegmentAppearance(segmentationId, viewportId, set) {
    const { segmentationService } = servicesManager.services;
    let segments = {};
    try {
      segments = segmentationService.getSegmentation(segmentationId)?.segments || {};
    } catch (_) {
      return 0;
    }
    let changed = 0;
    set.segments.forEach(item => {
      const segment = segments[item.index];
      if (!segment) return;
      if (segment.label !== item.label) {
        try {
          segmentationService.setSegmentLabel?.(segmentationId, item.index, item.label);
          changed++;
        } catch (err) {
          console.warn('[SegmentationEdit] setSegmentLabel failed for', item.label, err);
        }
      }
      // Alpha is left to the viewer's own opacity setting, so only the three
      // colour components are compared.
      const current = segment.color || [];
      const differs =
        current[0] !== item.color[0] ||
        current[1] !== item.color[1] ||
        current[2] !== item.color[2];
      if (differs && viewportId) {
        try {
          segmentationService.setSegmentColor?.(
            viewportId, segmentationId, item.index, item.color
          );
          changed++;
        } catch (err) {
          console.warn('[SegmentationEdit] setSegmentColor failed for', item.label, err);
        }
      }
    });
    if (changed) {
      console.log(
        '[SegmentationEdit] realigned', changed, 'segment appearance(s) on', segmentationId
      );
    }
    return changed;
  }

  // Complete the classes as soon as a segmentation is loaded, so the doctor sees
  // every class in the Segmentations panel just by opening the study, without
  // having to activate a tool first.
  let completingClasses = false;

  function completeClassesForAllSegmentations() {
    if (completingClasses) return;
    const { segmentationService, viewportGridService } = servicesManager.services;
    completingClasses = true;
    try {
      const viewportId = viewportGridService?.getState?.()?.activeViewportId;
      const raw = segmentationService?.getSegmentations?.();
      const length = raw?.length ?? 0;
      for (let i = 0; i < length; i++) {
        const entry = raw[i];
        const id = entry?.segmentationId || entry?.id;
        if (id) ensureAllSegmentClasses(id, viewportId);
      }
    } catch (err) {
      console.warn('[SegmentationEdit] class completion sweep failed', err);
    } finally {
      completingClasses = false;
    }
  }

  function subscribeSegmentationClassCompletion() {
    const { segmentationService } = servicesManager.services;
    const events = segmentationService?.EVENTS;
    if (!segmentationService?.subscribe || !events) return;
    // Adding a segment emits SEGMENTATION_MODIFIED, which is deliberately not in
    // this list: reacting to it would loop.
    ['SEGMENTATION_ADDED', 'SEGMENTATION_LOADING_COMPLETE', 'SEGMENTATION_REPRESENTATION_ADDED']
      .forEach(name => {
        const event = events[name];
        if (!event) return;
        try {
          segmentationService.subscribe(event, () => {
            // Let the service finish its own bookkeeping first.
            setTimeout(completeClassesForAllSegmentations, 0);
          });
        } catch (err) {
          console.warn('[SegmentationEdit] cannot subscribe to', name, err);
        }
      });
  }

  try {
    subscribeSegmentationClassCompletion();
  } catch (err) {
    console.warn('[SegmentationEdit] class completion subscription failed', err);
  }

  function segmentsForSegmentation(segmentationId) {
    const { segmentationService } = servicesManager.services;
    if (!segmentationId) return [];
    try {
      const segmentation = segmentationService?.getSegmentation?.(segmentationId);
      const segments = segmentation?.segments || {};
      return Object.keys(segments)
        .map(key => Number(key))
        .filter(index => Number.isFinite(index) && index > 0)
        .sort((a, b) => a - b)
        .map(index => ({
          segmentIndex: index,
          label: segments[index]?.label || `Segment ${index}`,
          color: segments[index]?.color,
        }));
    } catch (_) {
      return [];
    }
  }

  function cycleActivePencilSegment() {
    const { segmentationService } = servicesManager.services;
    const { activeViewportId } = getActiveViewport();
    const segmentationId = ensureActiveSegmentationId(activeViewportId);
    if (!segmentationId) {
      uiNotificationService.show({
        title: 'Segment',
        message: 'Aucune segmentation active. Sélectionnez-en une dans la liste à gauche.',
        type: 'warning',
        duration: 3000,
      });
      return;
    }
    ensureAllSegmentClasses(segmentationId, activeViewportId);
    const segments = segmentsForSegmentation(segmentationId);
    if (!segments.length) {
      uiNotificationService.show({
        title: 'Segment',
        message: 'Aucune classe trouvée pour cette segmentation.',
        type: 'info',
        duration: 1800,
      });
      return;
    }
    const currentIndex = resolveActiveSegmentIndex(activeViewportId);
    const currentPos = segments.findIndex(s => s.segmentIndex === currentIndex);
    const next = segments[(currentPos + 1) % segments.length];
    try {
      segmentationService.setActiveSegment(segmentationId, next.segmentIndex);
    } catch (err) {
      reportSegmentationError('Segment', 'cycle', err);
      return;
    }
    uiNotificationService.show({
      title: 'Segment',
      message: `Classe active pour le crayon : ${next.label}`,
      type: 'info',
      duration: 2000,
    });
  }

  function showBrushCursor(element, viewportId) {
    let record = brushCursors.get(viewportId);
    if (!record) {
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('aria-hidden', 'true');
      Object.assign(svg.style, {
        position: 'absolute', inset: '0', width: '100%', height: '100%',
        pointerEvents: 'none', zIndex: '10', overflow: 'visible',
      });
      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('fill', 'none');
      circle.setAttribute('stroke', '#ffffff');
      circle.setAttribute('stroke-width', '1.5');
      circle.style.filter = 'drop-shadow(0 0 1px #000)';
      svg.appendChild(circle);
      element.appendChild(svg);
      record = { svg, circle };
      brushCursors.set(viewportId, record);
    }
    return record;
  }

  function hideBrushCursor(viewportId) {
    const record = brushCursors.get(viewportId);
    if (record) {
      record.svg.remove();
      brushCursors.delete(viewportId);
    }
  }

  // Small on-image control (top-left of the viewport) to see and change the
  // brush size of the active tool without keyboard tricks: [-] [size] [+] and
  // a slider. Pointer/wheel events are stopped at the panel so clicking the
  // controls never paints on the image underneath.
  function showBrushPanel(element, viewportId, mode, modeLabel) {
    hideBrushPanel(viewportId);

    const accent = mode === 'pencil' ? '#22c55e' : '#e5e7eb';
    const panel = document.createElement('div');
    panel.setAttribute('data-brush-panel', mode);
    Object.assign(panel.style, {
      position: 'absolute',
      top: '8px',
      right: '8px',
      zIndex: '20',
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      padding: '4px 8px',
      borderRadius: '6px',
      background: 'rgba(15, 23, 42, 0.88)',
      border: `1px solid ${accent}`,
      color: '#f8fafc',
      font: '12px system-ui, -apple-system, "Segoe UI", sans-serif',
      cursor: 'default',
      userSelect: 'none',
      pointerEvents: 'auto',
      boxShadow: '0 1px 4px rgba(0,0,0,0.5)',
    });

    const label = document.createElement('span');
    label.textContent = modeLabel;
    Object.assign(label.style, { fontWeight: '600', color: accent, marginRight: '2px' });

    const makeButton = text => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = text;
      Object.assign(button.style, {
        width: '22px',
        height: '22px',
        lineHeight: '20px',
        padding: '0',
        borderRadius: '4px',
        border: '1px solid rgba(255,255,255,0.35)',
        background: 'rgba(255,255,255,0.08)',
        color: '#f8fafc',
        fontSize: '14px',
        fontWeight: '700',
        cursor: 'pointer',
      });
      return button;
    };
    const minus = makeButton('−');
    const plus = makeButton('+');
    minus.title = 'Diminuer la taille';
    plus.title = 'Augmenter la taille';

    const value = document.createElement('span');
    Object.assign(value.style, { minWidth: '46px', textAlign: 'center', fontVariantNumeric: 'tabular-nums' });

    const range = document.createElement('input');
    range.type = 'range';
    range.min = String(BRUSH_MIN);
    range.max = String(BRUSH_MAX);
    range.step = String(BRUSH_STEP);
    range.title = 'Taille de la brosse';
    Object.assign(range.style, { width: '90px', cursor: 'pointer', accentColor: accent });

    const refresh = () => {
      const size = getBrushSize(mode);
      value.textContent = `${size} px`;
      if (range.value !== String(size)) range.value = String(size);
      minus.disabled = size <= BRUSH_MIN;
      plus.disabled = size >= BRUSH_MAX;
      minus.style.opacity = minus.disabled ? '0.4' : '1';
      plus.style.opacity = plus.disabled ? '0.4' : '1';
    };

    minus.addEventListener('click', () => setBrushSize(mode, getBrushSize(mode) - BRUSH_STEP));
    plus.addEventListener('click', () => setBrushSize(mode, getBrushSize(mode) + BRUSH_STEP));
    range.addEventListener('input', () => setBrushSize(mode, range.value));

    [
      'pointerdown', 'pointermove', 'pointerup', 'pointerleave', 'pointercancel',
      'mousedown', 'mousemove', 'mouseup', 'click', 'dblclick', 'contextmenu',
      'wheel', 'touchstart', 'touchmove', 'touchend', 'keydown',
    ].forEach(type => {
      panel.addEventListener(type, event => event.stopPropagation());
    });

    panel.appendChild(label);
    panel.appendChild(minus);
    panel.appendChild(value);
    panel.appendChild(plus);
    panel.appendChild(range);
    element.appendChild(panel);

    const record = { panel, refresh, mode };
    brushPanels.set(viewportId, record);
    refresh();
    return record;
  }

  function hideBrushPanel(viewportId) {
    const record = brushPanels.get(viewportId);
    if (record) {
      record.panel.remove();
      brushPanels.delete(viewportId);
    }
  }

  // Which model's mask is this? The backend needs to know: the same endpoint
  // now receives lesion masks and optic disc masks, and they feed different
  // parts of the report.
  const SEGMENTATION_KINDS = [
    { kind: 'lesions', match: /l[eé]sion/i },
    { kind: 'neovascularization', match: /neovasc|néovasc/i },
    { kind: 'vessels', match: /vaiss|vessel/i },
    { kind: 'optic_disc', match: /optic|disc|exca|cup/i },
  ];

  function segmentationKind(segmentationId, viewportId) {
    const { segmentationService } = servicesManager.services;
    let name = '';
    try {
      const segmentation = segmentationService?.getSegmentation?.(segmentationId);
      name = segmentationDisplayName(segmentation);
    } catch (err) {
      console.warn('[SegmentationEdit] segmentationKind lookup failed', err);
    }
    // The lesion set must be tested first: "seg_lésions" also matches nothing
    // else, but a description mentioning both would otherwise fall to whichever
    // pattern came first by accident.
    const entry = SEGMENTATION_KINDS.find(candidate => candidate.match.test(name));
    return entry ? entry.kind : 'unknown';
  }

  function labelmapDimensions(viewport) {
    const imageId = viewport?.getCurrentImageId?.();
    const image = imageId && csCore?.cache ? csCore.cache.getImage(imageId) : null;
    if (!image) return null;
    const width = image.columns || image.width;
    const height = image.rows || image.height;
    return width && height ? { width, height } : null;
  }

  // Vertical extent of each segment, in rows. The cup/disc ratio is defined on
  // vertical DIAMETERS, not on areas, so the pixel counts alone cannot express
  // it and these have to travel with them.
  function verticalExtents(scalarData, width) {
    const first = {};
    const last = {};
    for (let i = 0; i < scalarData.length; i++) {
      const value = scalarData[i];
      if (!value) continue;
      const row = Math.floor(i / width);
      if (first[value] === undefined) first[value] = row;
      last[value] = row; // the scan runs row by row, so this is the lowest one
    }
    const out = {};
    Object.keys(first).forEach(value => {
      out[value] = last[value] - first[value] + 1;
    });
    return out;
  }

  function countLabelValues(scalarData) {
    const counts = {};
    for (let i = 0; i < scalarData.length; i++) {
      const value = scalarData[i];
      if (!value) continue;
      counts[value] = (counts[value] || 0) + 1;
    }
    return counts;
  }

  function summarizeActiveSegmentation() {
    const { activeViewportId, viewport } = getActiveViewport();
    const segmentationId = ensureActiveSegmentationId(activeViewportId);
    if (!segmentationId) return null;
    const accessor = getLabelmapAccessor(segmentationId, activeViewportId, viewport);
    const scalarData = accessor?.getScalarData?.();
    if (!scalarData) return null;

    const counts = countLabelValues(scalarData);
    const size = labelmapDimensions(viewport);
    // The backend has to know what the mask held BEFORE the doctor touched it,
    // and it has to be counted on this very array. The model's own pixel
    // counts were measured on the inference tensor and do not share a frame of
    // reference with the labelmap loaded here, so using them as the reference
    // would rescale the report on the first save, before anything was erased.
    //
    // originalSnapshots holds exactly that: a copy taken when the first
    // editing tool was activated, before any stroke.
    const pristine = originalSnapshots.get(segmentationId);
    return {
      segmentation_id: segmentationId,
      segmentation_kind: segmentationKind(segmentationId, activeViewportId),
      pixel_counts_by_segment: counts,
      baseline_counts_by_segment: pristine ? countLabelValues(pristine) : null,
      vertical_extents_by_segment: size ? verticalExtents(scalarData, size.width) : null,
      total_labeled_pixels: Object.values(counts).reduce((sum, value) => sum + value, 0),
    };
  }

  function reportSegmentationError(modeLabel, phase, err) {
    console.error(`[SegmentationEdit] ${modeLabel} (${phase}) failed:`, err);
    uiNotificationService.show({
      title: `${modeLabel} — erreur`,
      message: `[${phase}] ${err?.message || err}`,
      type: 'error',
      duration: 8000,
    });
  }

  async function toggleSegmentationEdit(mode) {
    const modeLabel = mode === 'pencil' ? 'Crayon' : 'Gomme';
    try {
      await loadCornerstone();
      const { activeViewportId, viewport } = getActiveViewport();
      const element = viewport?.element;
      if (!activeViewportId || !element) {
        reportSegmentationError(modeLabel, 'setup', new Error('Aucun viewport actif trouvé.'));
        return;
      }

      const existing = editSessions.get(activeViewportId);
      if (existing) {
        const wasSameMode = existing.mode === mode;
        existing.cleanup();
        editSessions.delete(activeViewportId);
        hideBrushCursor(activeViewportId);
        hideBrushPanel(activeViewportId);
        hideWandPanel(activeViewportId);
        hideWandPreview(activeViewportId);
        if (wasSameMode) {
          uiNotificationService.show({
            title: modeLabel,
            message: `${modeLabel} désactivé.`,
            type: 'info',
            duration: 1600,
          });
          return;
        }
      }

      let segmentationId = ensureActiveSegmentationId(activeViewportId);
      if (!segmentationId) {
        segmentationId = await loadSegmentationForEditing(activeViewportId, modeLabel);
        if (!segmentationId) return;
      }
      const accessor = segmentationId
        ? getLabelmapAccessor(segmentationId, activeViewportId, viewport)
        : null;
      console.log(
        '[SegmentationEdit] segmentationId=', segmentationId,
        'accessor.kind=', accessor?.kind,
        'imageId=', accessor?.imageId
      );
      let initialData = null;
      try {
        initialData = accessor ? accessor.getScalarData() : null;
      } catch (err) {
        console.warn('[SegmentationEdit] getScalarData failed', err);
      }
      if (!accessor || !initialData) {
        uiNotificationService.show({
          title: modeLabel,
          message: segmentationId
            ? 'Segmentation trouvée mais ses pixels ne sont pas accessibles (voir console).'
            : "Aucune segmentation chargée. Cliquez sur CHARGER en haut à droite de l'image, puis réessayez.",
          type: 'warning',
          duration: 3500,
        });
        return;
      }

      ensureAllSegmentClasses(segmentationId, activeViewportId);
      ensureOriginalSnapshot(accessor);

      let drawing = false;
      let strokeDiff = null;
      const previousCursor = element.style.cursor;
      element.style.cursor = 'none';
      const cursor = showBrushCursor(element, activeViewportId);
      showBrushPanel(element, activeViewportId, mode, modeLabel);
      cursor.circle.setAttribute('stroke', mode === 'pencil' ? '#22c55e' : '#ffffff');

      const pointFromEvent = event => {
        const rect = element.getBoundingClientRect();
        return [event.clientX - rect.left, event.clientY - rect.top];
      };
      const paint = event => {
        try {
          const [x, y] = pointFromEvent(event);
          const writeValue = mode === 'pencil'
            ? (resolveActiveSegmentIndex(activeViewportId) ?? 1)
            : 0;
          if (paintAtCanvasPoint(viewport, accessor, x, y, getBrushSize(mode), writeValue, strokeDiff)) {
            usedModesThisSession.add(mode);
          }
        } catch (err) {
          reportSegmentationError(modeLabel, 'paint', err);
        }
      };
      const applyRadius = () => {
        cursor.circle.setAttribute('r', String(Math.max(1, getBrushSize(mode) / 2)));
      };
      const updateCursor = event => {
        try {
          const [x, y] = pointFromEvent(event);
          cursor.circle.setAttribute('cx', String(x));
          cursor.circle.setAttribute('cy', String(y));
          applyRadius();
        } catch (err) {
          reportSegmentationError(modeLabel, 'cursor', err);
        }
      };
      applyRadius();
      const pointerDown = event => {
        try {
          drawing = true;
          strokeDiff = new Map();
          element.setPointerCapture?.(event.pointerId);
          updateCursor(event);
          paint(event);
          event.preventDefault();
        } catch (err) {
          reportSegmentationError(modeLabel, 'pointerdown', err);
        }
      };
      const pointerMove = event => {
        try {
          updateCursor(event);
          if (!drawing) return;
          paint(event);
          event.preventDefault();
        } catch (err) {
          reportSegmentationError(modeLabel, 'pointermove', err);
        }
      };
      const pointerUp = event => {
        try {
          if (drawing && strokeDiff) {
            pushUndoEntry(segmentationId, strokeDiff);
          }
          drawing = false;
          strokeDiff = null;
          element.releasePointerCapture?.(event.pointerId);
          event.preventDefault();
        } catch (err) {
          reportSegmentationError(modeLabel, 'pointerup', err);
        }
      };
      const wheel = event => {
        if (!event.altKey) return;
        setBrushSize(mode, getBrushSize(mode) + (event.deltaY > 0 ? -BRUSH_STEP : BRUSH_STEP));
        event.preventDefault();
      };

      element.addEventListener('pointerdown', pointerDown);
      element.addEventListener('pointermove', pointerMove);
      element.addEventListener('pointerup', pointerUp);
      element.addEventListener('pointerleave', pointerUp);
      element.addEventListener('wheel', wheel, { passive: false });

      editSessions.set(activeViewportId, {
        mode,
        applyRadius,
        cleanup: () => {
          element.style.cursor = previousCursor;
          element.removeEventListener('pointerdown', pointerDown);
          element.removeEventListener('pointermove', pointerMove);
          element.removeEventListener('pointerup', pointerUp);
          element.removeEventListener('pointerleave', pointerUp);
          element.removeEventListener('wheel', wheel);
        },
      });

      uiNotificationService.show({
        title: modeLabel,
        message:
          mode === 'pencil'
            ? `Crayon actif (${getBrushSize('pencil')} px). Taille : panneau en haut à droite ou Alt + molette. Bouton "Segment" : classe à dessiner.`
            : `Gomme active (${getBrushSize('erase')} px). Taille : panneau en haut à droite ou Alt + molette.`,
        type: 'success',
        duration: 3000,
      });
    } catch (err) {
      reportSegmentationError(modeLabel, 'setup', err);
    }
  }

  // ---------------------------------------------------------------------------
  // Baguette magique: image processing helpers (all in-browser, no server call)
  // ---------------------------------------------------------------------------

  // Green channel of the displayed fundus image (best lesion contrast on colour
  // fundus photographs), smoothed with a 3x3 box blur. Computed once per tool
  // activation. Grayscale images are normalised to 0..255.
  // sRGB companding, tabulated: the only per-pixel cost left in the Lab
  // transform is its cube roots.
  const SRGB_TO_LINEAR = (() => {
    const table = new Float32Array(256);
    for (let v = 0; v < 256; v++) {
      const c = v / 255;
      table[v] = c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }
    return table;
  })();

  // CIELAB chroma (a*, b*) under D65, stored as bytes centred on 128 so the
  // same median filter and the same arithmetic apply as on the green channel.
  //
  // L* is deliberately dropped: the green channel already carries the
  // luminance, illumination-corrected by the morphological flat field, and
  // recomputing it from Lab would throw that correction away. What the green
  // channel cannot express is hue, and hue is exactly what separates a red
  // haemorrhage from a vessel of the same darkness.
  function labChroma(pixels, total, stride, width, height) {
    const rawA = new Uint8Array(total);
    const rawB = new Uint8Array(total);
    const f = t => (t > 0.008856451679 ? Math.cbrt(t) : 7.787037037 * t + 0.1379310345);
    for (let p = 0; p < total; p++) {
      const base = p * stride;
      const r = SRGB_TO_LINEAR[pixels[base]];
      const g = SRGB_TO_LINEAR[pixels[base + 1]];
      const b = SRGB_TO_LINEAR[pixels[base + 2]];
      // Divided by the D65 white point, so a neutral grey gives a* = b* = 0.
      const fx = f((0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047);
      const fy = f(0.2126729 * r + 0.7151522 * g + 0.0721750 * b);
      const fz = f((0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883);
      const a = 500 * (fx - fy);
      const bb = 200 * (fy - fz);
      rawA[p] = a <= -128 ? 0 : a >= 127 ? 255 : Math.round(a + 128);
      rawB[p] = bb <= -128 ? 0 : bb >= 127 ? 255 : Math.round(bb + 128);
    }
    // Denoised like the green channel. Not flat-fielded: vignetting is a
    // brightness effect, chroma drifts far less, and the adaptive threshold
    // absorbs what is left for the cost of two more morphology passes.
    return { a: median3x3(rawA, width, height), b: median3x3(rawB, width, height) };
  }

  function getFundusGreenChannel(viewport) {
    const imageId = viewport?.getCurrentImageId?.();
    const image = imageId && csCore?.cache ? csCore.cache.getImage(imageId) : null;
    if (!image) return null;
    const pixels = image.getPixelData?.();
    const width = image.columns || image.width;
    const height = image.rows || image.height;
    if (!pixels || !width || !height) return null;
    const total = width * height;
    const raw = new Uint8Array(total);
    let chroma = null;
    if (image.color || pixels.length >= total * 3) {
      const stride = pixels.length >= total * 4 ? 4 : 3;
      for (let p = 0; p < total; p++) raw[p] = pixels[p * stride + 1];
      chroma = labChroma(pixels, total, stride, width, height);
    } else {
      let min = Infinity;
      let max = -Infinity;
      for (let p = 0; p < total; p++) {
        const v = pixels[p];
        if (v < min) min = v;
        if (v > max) max = v;
      }
      const scale = max > min ? 255 / (max - min) : 1;
      for (let p = 0; p < total; p++) raw[p] = Math.round((pixels[p] - min) * scale);
    }
    const data = median3x3(raw, width, height);
    // Both variants are computed once at activation and kept, so toggling the
    // illumination correction costs nothing.
    const flat = flattenIllumination(data, width, height);
    // Computed once when the tool is activated, then reused by every click and
    // every hover preview: O(width * height) here instead of per stroke.
    const gradient = sobelMagnitude(data, width, height);
    return { data, flat, gradient, chroma, width, height, imageId };
  }

  // Sobel gradient magnitude. A pixel sitting on a strong edge is a boundary,
  // either the lesion's own or a vessel's, and the region must not cross it.
  function sobelMagnitude(src, width, height) {
    const out = new Float32Array(width * height);
    for (let j = 1; j < height - 1; j++) {
      const row = j * width;
      for (let i = 1; i < width - 1; i++) {
        const idx = row + i;
        const a = src[idx - width - 1];
        const b = src[idx - width];
        const c = src[idx - width + 1];
        const d = src[idx - 1];
        const f = src[idx + 1];
        const g = src[idx + width - 1];
        const h = src[idx + width];
        const k = src[idx + width + 1];
        const gx = c + 2 * f + k - (a + 2 * d + g);
        const gy = g + 2 * h + k - (a + 2 * b + c);
        out[idx] = Math.sqrt(gx * gx + gy * gy);
      }
    }
    return out;
  }

  // Percentile of the gradient inside the search box, via a histogram: gives an
  // edge threshold that adapts to the local contrast of each image.
  function gradientThreshold(gradient, width, height, seedI, seedJ, radius, percentile) {
    if (!gradient || percentile <= 0) return Infinity;
    const bins = new Int32Array(256);
    let total = 0;
    let maxValue = 0;
    for (let j = seedJ - radius; j <= seedJ + radius; j++) {
      if (j < 0 || j >= height) continue;
      for (let i = seedI - radius; i <= seedI + radius; i++) {
        if (i < 0 || i >= width) continue;
        const value = gradient[j * width + i];
        if (value > maxValue) maxValue = value;
      }
    }
    if (maxValue <= 0) return Infinity;
    const scale = 255 / maxValue;
    for (let j = seedJ - radius; j <= seedJ + radius; j++) {
      if (j < 0 || j >= height) continue;
      for (let i = seedI - radius; i <= seedI + radius; i++) {
        if (i < 0 || i >= width) continue;
        bins[Math.min(255, Math.round(gradient[j * width + i] * scale))]++;
        total++;
      }
    }
    if (!total) return Infinity;
    const target = (total * percentile) / 100;
    let cumulative = 0;
    for (let b = 0; b < 256; b++) {
      cumulative += bins[b];
      if (cumulative >= target) return b / scale;
    }
    return Infinity;
  }

  // A fundus photograph is brighter at the centre than at the periphery. That
  // slow drift biases the ring-median background estimate, so the same lesion
  // needs a different tolerance depending on where it sits in the image.
  //
  // Classic remedy in retinal lesion detection: estimate the illumination with
  // grayscale morphology using a structuring element larger than any lesion,
  // then subtract it. An opening erases structures brighter than their
  // surroundings, a closing erases the darker ones, so the average of the two
  // keeps neither bright nor dark lesions and leaves only the illumination.
  //
  // Both passes use a separable square element and a monotonic deque, so the
  // cost is linear in the number of pixels and independent of the element size.
  function slidingExtreme(src, dst, width, height, radius, wantMax) {
    const deque = new Int32Array(Math.max(width, height));
    // horizontal
    for (let y = 0; y < height; y++) {
      const row = y * width;
      let head = 0;
      let tail = 0;
      for (let x = 0; x < width + radius; x++) {
        if (x < width) {
          const v = src[row + x];
          while (tail > head) {
            const last = src[row + deque[tail - 1]];
            if (wantMax ? last <= v : last >= v) tail--;
            else break;
          }
          deque[tail++] = x;
        }
        const out = x - radius;
        if (out >= 0) {
          while (deque[head] < out - radius) head++;
          dst[row + out] = src[row + deque[head]];
        }
      }
    }
    // vertical, in place on dst
    const column = new Uint8Array(height);
    for (let x = 0; x < width; x++) {
      for (let y = 0; y < height; y++) column[y] = dst[y * width + x];
      let head = 0;
      let tail = 0;
      for (let y = 0; y < height + radius; y++) {
        if (y < height) {
          const v = column[y];
          while (tail > head) {
            const last = column[deque[tail - 1]];
            if (wantMax ? last <= v : last >= v) tail--;
            else break;
          }
          deque[tail++] = y;
        }
        const out = y - radius;
        if (out >= 0) {
          while (deque[head] < out - radius) head++;
          dst[out * width + x] = column[deque[head]];
        }
      }
    }
  }

  function grayOpen(src, width, height, radius) {
    const eroded = new Uint8Array(src.length);
    const opened = new Uint8Array(src.length);
    slidingExtreme(src, eroded, width, height, radius, false);
    slidingExtreme(eroded, opened, width, height, radius, true);
    return opened;
  }

  function grayClose(src, width, height, radius) {
    const dilated = new Uint8Array(src.length);
    const closed = new Uint8Array(src.length);
    slidingExtreme(src, dilated, width, height, radius, true);
    slidingExtreme(dilated, closed, width, height, radius, false);
    return closed;
  }

  function flattenIllumination(src, width, height) {
    // The element must be larger than the biggest lesion we want to keep,
    // hence a fraction of the image rather than a fixed number of pixels.
    const radius = Math.max(12, Math.round(Math.min(width, height) * 0.06));
    const opened = grayOpen(src, width, height, radius);
    const closed = grayClose(src, width, height, radius);
    const out = new Uint8Array(src.length);
    for (let p = 0; p < src.length; p++) {
      const background = (opened[p] + closed[p]) / 2;
      // Recentre on 128 so the intensity scale, the polarity test and the
      // tolerance keep the same meaning as on the raw channel.
      const v = src[p] - background + 128;
      out[p] = v < 0 ? 0 : v > 255 ? 255 : v;
    }
    return out;
  }

  // A 3x3 mean blurs the lesion boundary as much as the noise, which weakens
  // the Sobel barrier that is supposed to stop the growth on that very
  // boundary. A median removes impulse noise while leaving edges sharp.
  //
  // The nine samples are sorted by the classic 19-comparison network rather
  // than a generic sort: no allocation, no branching on data size, and the
  // median lands in slot 4.
  function median3x3(src, width, height) {
    const out = new Uint8Array(src.length);
    const p = new Uint8Array(9);
    const sort2 = (a, b) => {
      if (p[a] > p[b]) {
        const t = p[a];
        p[a] = p[b];
        p[b] = t;
      }
    };
    for (let j = 0; j < height; j++) {
      const jm = j > 0 ? j - 1 : 0;
      const jp = j < height - 1 ? j + 1 : height - 1;
      for (let i = 0; i < width; i++) {
        const im = i > 0 ? i - 1 : 0;
        const ip = i < width - 1 ? i + 1 : width - 1;
        const rowm = jm * width;
        const row = j * width;
        const rowp = jp * width;
        p[0] = src[rowm + im];
        p[1] = src[rowm + i];
        p[2] = src[rowm + ip];
        p[3] = src[row + im];
        p[4] = src[row + i];
        p[5] = src[row + ip];
        p[6] = src[rowp + im];
        p[7] = src[rowp + i];
        p[8] = src[rowp + ip];
        sort2(1, 2); sort2(4, 5); sort2(7, 8);
        sort2(0, 1); sort2(3, 4); sort2(6, 7);
        sort2(1, 2); sort2(4, 5); sort2(7, 8);
        sort2(0, 3); sort2(5, 8); sort2(4, 7);
        sort2(3, 6); sort2(1, 4); sort2(2, 5);
        sort2(4, 7); sort2(4, 2); sort2(6, 4);
        sort2(4, 2);
        out[row + i] = p[4];
      }
    }
    return out;
  }

  function mean3x3(green, width, height, ci, cj) {
    let sum = 0;
    let count = 0;
    for (let j = Math.max(0, cj - 1); j <= Math.min(height - 1, cj + 1); j++) {
      for (let i = Math.max(0, ci - 1); i <= Math.min(width - 1, ci + 1); i++) {
        sum += green[j * width + i];
        count++;
      }
    }
    return count ? sum / count : green[cj * width + ci];
  }

  // Median intensity on a ring of radius r around the seed = local background.
  // Samples darker than 8 are ignored (black mask outside the retina).
  // Background level around the seed, or around the whole path when the
  // doctor drew a stroke. Ring samples from several points are pooled and the
  // median taken, so a ring that happens to cross the lesion itself only
  // shifts the estimate if such samples become the majority.
  function medianOnRings(green, width, height, seeds, r) {
    const samples = [];
    const picks = Math.min(seeds.length, 8);
    const steps = 72;
    for (let k = 0; k < picks; k++) {
      const offset = seeds[Math.floor((k * seeds.length) / picks)];
      const ci = offset % width;
      const cj = (offset - ci) / width;
      for (let s = 0; s < steps; s++) {
        const angle = (2 * Math.PI * s) / steps;
        const i = Math.round(ci + r * Math.cos(angle));
        const j = Math.round(cj + r * Math.sin(angle));
        if (i < 0 || j < 0 || i >= width || j >= height) continue;
        const v = green[j * width + i];
        if (v >= 8) samples.push(v); // the black surround of the retina
      }
    }
    if (samples.length < 8) return null;
    samples.sort((a, b) => a - b);
    return samples[samples.length >> 1];
  }

  // Seeded region growing, Adams & Bischof, 8-connectivity, inside a square
  // box. `seeds` is a list of pixel indices: one for a click, the whole path
  // for a stroke. Every seed is accepted up front, so the region starts from a
  // mean measured on several real lesion pixels instead of a single one, which
  // is what makes a stroke steadier than a click on a heterogeneous lesion.
  //
  // Similarity is a distance in (green, a*, b*): green carries the
  // illumination-corrected luminance, the two chroma channels carry the hue,
  // weighted by the doctor's Couleur setting.
  function growRegion(field, width, height, seeds, tolerance, box, polarity, background, margin, gradient, edgeThreshold) {
    const { green, chromaA, chromaB, weight } = field;
    const { x0, y0, size, maxArea } = box;
    const useColour = !!chromaA && !!chromaB && weight > 0;
    const w2 = weight * weight;
    const mask = new Uint8Array(size * size);
    const visited = new Uint8Array(size * size);
    // How far a pixel sits from the confident core, in pixels. Only read
    // during the permissive pass, where every candidate has an explicit value.
    const depth = new Uint8Array(size * size);
    // Candidate pixels wait in a min-heap ordered by their distance to the
    // region mean, and the most similar one is always absorbed first. The
    // boundary follows the actual contrast rather than the scan order, and the
    // result no longer depends on the order in which neighbours were enqueued.
    const capacity = size * size + 1;
    const heapDelta = new Float32Array(capacity);
    const heapPixel = new Int32Array(capacity); // j * width + i
    const heapSeq = new Int32Array(capacity); // deterministic tie-break
    let heapSize = 0;
    let sequence = 0;

    // Ties are broken by insertion order, so two runs on the same image give
    // exactly the same mask: reproducibility matters for a medical tool.
    const heapBefore = (a, b) =>
      heapDelta[a] < heapDelta[b] ||
      (heapDelta[a] === heapDelta[b] && heapSeq[a] < heapSeq[b]);

    const heapSwap = (a, b) => {
      const d = heapDelta[a];
      heapDelta[a] = heapDelta[b];
      heapDelta[b] = d;
      const p = heapPixel[a];
      heapPixel[a] = heapPixel[b];
      heapPixel[b] = p;
      const s = heapSeq[a];
      heapSeq[a] = heapSeq[b];
      heapSeq[b] = s;
    };

    const heapPush = (delta, pixel) => {
      if (heapSize >= capacity) return;
      let node = heapSize++;
      heapDelta[node] = delta;
      heapPixel[node] = pixel;
      heapSeq[node] = sequence++;
      while (node > 0) {
        const parent = (node - 1) >> 1;
        if (!heapBefore(node, parent)) break;
        heapSwap(node, parent);
        node = parent;
      }
    };

    const heapPop = () => {
      const top = heapPixel[0];
      heapSize--;
      if (heapSize > 0) {
        heapDelta[0] = heapDelta[heapSize];
        heapPixel[0] = heapPixel[heapSize];
        heapSeq[0] = heapSeq[heapSize];
        let node = 0;
        for (;;) {
          const left = 2 * node + 1;
          const right = left + 1;
          let best = node;
          if (left < heapSize && heapBefore(left, best)) best = left;
          if (right < heapSize && heapBefore(right, best)) best = right;
          if (best === node) break;
          heapSwap(node, best);
          node = best;
        }
      }
      return top;
    };

    const halfMargin = margin / 2;
    // The margin is a parameter: the strict pass demands half the seed's
    // contrast against the background, the permissive pass a quarter of it.
    const inside = polarity === 'dark'
      ? (v, m) => v < background - m
      : (v, m) => v > background + m;

    let sum = 0;
    let sumSquares = 0;
    let sumA = 0;
    let sumSquaresA = 0;
    let sumB = 0;
    let sumSquaresB = 0;
    let count = 0;
    let touchedBorder = false;
    let stoppedOnEdge = 0;
    const useEdges = !!gradient && Number.isFinite(edgeThreshold);

    // Pixels the strict pass refuses on intensity alone. They all touch the
    // core, since a candidate only ever enters the heap as the neighbour of an
    // accepted pixel, so they are exactly the entry points of the second pass.
    const weakPixels = new Int32Array(size * size);
    let weakPending = 0;

    const distance = (pixelIndex, mg, ma, mb) => {
      const dg = green[pixelIndex] - mg;
      if (!useColour) return dg < 0 ? -dg : dg;
      const da = chromaA[pixelIndex] - ma;
      const db = chromaB[pixelIndex] - mb;
      return Math.sqrt(dg * dg + w2 * (da * da + db * db));
    };

    const enqueue = (i, j, d, mg, ma, mb) => {
      for (let dj = -1; dj <= 1; dj++) {
        for (let di = -1; di <= 1; di++) {
          if (!di && !dj) continue;
          const ni = i + di;
          const nj = j + dj;
          if (ni < 0 || nj < 0 || ni >= width || nj >= height) continue;
          const nbi = ni - x0;
          const nbj = nj - y0;
          if (nbi < 0 || nbj < 0 || nbi >= size || nbj >= size) continue;
          const idx = nbj * size + nbi;
          if (visited[idx]) continue;
          visited[idx] = 1;
          depth[idx] = d;
          const neighbourIndex = nj * width + ni;
          heapPush(distance(neighbourIndex, mg, ma, mb), neighbourIndex);
        }
      }
    };

    const absorb = (pixelIndex, bi, bj) => {
      mask[bj * size + bi] = 1;
      const v = green[pixelIndex];
      sum += v;
      sumSquares += v * v;
      if (useColour) {
        const a = chromaA[pixelIndex];
        const b = chromaB[pixelIndex];
        sumA += a;
        sumSquaresA += a * a;
        sumB += b;
        sumSquaresB += b * b;
      }
      count++;
      if (bi === 0 || bj === 0 || bi === size - 1 || bj === size - 1) touchedBorder = true;
    };

    // ---- The seeds join, once they have been sanity-checked ---------------
    // A stroke traced ALONG the border instead of across the lesion drops part
    // of its seeds on the background side. Absorbed unconditionally, those
    // would hand the region a foothold in the background that bypasses every
    // test, and would inflate the seed spread with the whole lesion-to-
    // background range, opening the threshold on both counts.
    //
    // So the seeds of a stroke face the same polarity gate as everything else,
    // measured against the background estimated from the surrounding rings,
    // which is information the stroke itself cannot corrupt. If too few
    // survive, the doctor is pointing at a genuinely faint lesion rather than
    // tracing an edge, and the whole set is honoured instead.
    let onLesionSide = 0;
    if (seeds.length > 1) {
      for (let s = 0; s < seeds.length; s++) {
        if (inside(green[seeds[s]], halfMargin)) onLesionSide++;
      }
    }
    const filterSeeds = seeds.length > 1 && onLesionSide >= Math.max(4, seeds.length * 0.25);
    const keepSeed = pixelIndex => !filterSeeds || inside(green[pixelIndex], halfMargin);

    for (let s = 0; s < seeds.length; s++) {
      const pixelIndex = seeds[s];
      if (!keepSeed(pixelIndex)) continue;
      const i = pixelIndex % width;
      const j = (pixelIndex - i) / width;
      const bi = i - x0;
      const bj = j - y0;
      if (bi < 0 || bj < 0 || bi >= size || bj >= size) continue;
      if (visited[bj * size + bi]) continue;
      visited[bj * size + bi] = 1;
      absorb(pixelIndex, bi, bj);
    }
    if (!count) {
      return { mask, size, x0, y0, count: 0, coreCount: 0, halo: 0, stoppedOnEdge: 0, leak: false };
    }
    // How far the seeds themselves spread. A stroke across a lesion is the
    // doctor stating the range its intensity covers, and that statement has to
    // survive the growth: left to itself the running variance collapses onto
    // whichever side the region started filling, the threshold closes, and the
    // other side is abandoned. So the seed spread stays a floor throughout.
    // A click has a single seed, spread zero, and behaves exactly as before.
    let seedSpread = 0;
    if (count > 1) {
      const seedMean = sum / count;
      let seedVariance = Math.max(0, sumSquares / count - seedMean * seedMean);
      if (useColour) {
        const seedMeanA = sumA / count;
        const seedMeanB = sumB / count;
        seedVariance += w2 * (
          Math.max(0, sumSquaresA / count - seedMeanA * seedMeanA) +
          Math.max(0, sumSquaresB / count - seedMeanB * seedMeanB)
        );
      }
      seedSpread = WAND_K_SIGMA * Math.sqrt(seedVariance);
    }

    // Their neighbours are only enqueued once every seed has been counted, so
    // the priorities are measured against the full stroke, not a partial one.
    for (let s = 0; s < seeds.length; s++) {
      const pixelIndex = seeds[s];
      if (!keepSeed(pixelIndex)) continue;
      const i = pixelIndex % width;
      const j = (pixelIndex - i) / width;
      if (i - x0 < 0 || j - y0 < 0 || i - x0 >= size || j - y0 >= size) continue;
      enqueue(i, j, 0, sum / count, sumA / count, sumB / count);
    }

    // ---- Pass 1: strict threshold, the confident core --------------------
    while (heapSize > 0 && count < maxArea) {
      const pixelIndex = heapPop();
      const i = pixelIndex % width;
      const j = (pixelIndex - i) / width;
      const mg = sum / count;
      const ma = useColour ? sumA / count : 0;
      const mb = useColour ? sumB / count : 0;
      // Adaptive threshold: the slider is a floor, the spread of the region
      // widens it when the lesion is noisy or heterogeneous.
      let limit = Math.max(tolerance, seedSpread);
      if (count > 4) {
        let variance = Math.max(0, sumSquares / count - mg * mg);
        if (useColour) {
          variance += w2 * (
            Math.max(0, sumSquaresA / count - ma * ma) +
            Math.max(0, sumSquaresB / count - mb * mb)
          );
        }
        limit = Math.max(limit, WAND_K_SIGMA * Math.sqrt(variance));
      }
      if (distance(pixelIndex, mg, ma, mb) > limit || !inside(green[pixelIndex], halfMargin)) {
        // Too different for the core, perhaps not for the halo: keep it.
        if (weakPending < weakPixels.length) weakPixels[weakPending++] = pixelIndex;
        continue;
      }
      // Edge barrier: never cross a strong contour, which is what let the
      // region escape along a vessel. The seeds are exempt by construction,
      // since they were absorbed before the loop: a tiny lesion is all edge.
      if (useEdges && gradient[pixelIndex] > edgeThreshold) {
        stoppedOnEdge++;
        continue;
      }
      absorb(pixelIndex, i - x0, j - y0);
      enqueue(i, j, 0, sum / count, useColour ? sumA / count : 0, useColour ? sumB / count : 0);
    }

    // ---- Pass 2: loose threshold, but only hanging on the core -----------
    // A real lesion does not end on a step: its intensity fades over two or
    // three pixels, and those transition pixels systematically fail the strict
    // test, so the core is always slightly too tight.
    //
    // Canny's answer, transposed here: accept a much looser threshold, but
    // only for pixels connected to the core, and only within a narrow band. A
    // pale border is a thin band and is recovered; a leak along a vessel is a
    // long corridor and dies as soon as it leaves the band.
    const coreCount = count;
    const coreMean = sum / count;
    const coreMeanA = useColour ? sumA / count : 0;
    const coreMeanB = useColour ? sumB / count : 0;
    let coreVariance = Math.max(0, sumSquares / count - coreMean * coreMean);
    if (useColour) {
      coreVariance += w2 * (
        Math.max(0, sumSquaresA / count - coreMeanA * coreMeanA) +
        Math.max(0, sumSquaresB / count - coreMeanB * coreMeanB)
      );
    }
    // The statistics are frozen from here on. Letting the mean drift with the
    // loose pixels is exactly how a two-threshold scheme degenerates into a
    // single loose one, which is the leak we are trying to avoid.
    const weakLimit =
      Math.max(tolerance, seedSpread, WAND_K_SIGMA * Math.sqrt(coreVariance)) *
      WAND_HYSTERESIS_RATIO;
    const weakMargin = halfMargin / 2;

    heapSize = 0;
    for (let w = 0; w < weakPending; w++) {
      const pixelIndex = weakPixels[w];
      const i = pixelIndex % width;
      const j = (pixelIndex - i) / width;
      depth[(j - y0) * size + (i - x0)] = 1;
      heapPush(distance(pixelIndex, coreMean, coreMeanA, coreMeanB), pixelIndex);
    }

    let halo = 0;
    while (heapSize > 0 && count < maxArea) {
      const pixelIndex = heapPop();
      const i = pixelIndex % width;
      const j = (pixelIndex - i) / width;
      const bi = i - x0;
      const bj = j - y0;
      const here = depth[bj * size + bi];
      if (distance(pixelIndex, coreMean, coreMeanA, coreMeanB) > weakLimit ||
          !inside(green[pixelIndex], weakMargin)) {
        continue;
      }
      // The contour barrier is not relaxed. Loosening the intensity test is
      // the point; crossing a vessel is not.
      if (useEdges && gradient[pixelIndex] > edgeThreshold) {
        stoppedOnEdge++;
        continue;
      }
      mask[bj * size + bi] = 1;
      count++;
      halo++;
      if (bi === 0 || bj === 0 || bi === size - 1 || bj === size - 1) touchedBorder = true;
      // Accepted, but at the edge of the band it propagates no further.
      if (here >= WAND_HYSTERESIS_BAND) continue;
      for (let dj = -1; dj <= 1; dj++) {
        for (let di = -1; di <= 1; di++) {
          if (!di && !dj) continue;
          const ni = i + di;
          const nj = j + dj;
          if (ni < 0 || nj < 0 || ni >= width || nj >= height) continue;
          const nbi = ni - x0;
          const nbj = nj - y0;
          if (nbi < 0 || nbj < 0 || nbi >= size || nbj >= size) continue;
          const idx = nbj * size + nbi;
          if (visited[idx]) continue;
          visited[idx] = 1;
          depth[idx] = here + 1;
          const neighbourIndex = nj * width + ni;
          heapPush(distance(neighbourIndex, coreMean, coreMeanA, coreMeanB), neighbourIndex);
        }
      }
    }

    return {
      mask,
      size,
      x0,
      y0,
      count,
      coreCount,
      halo,
      stoppedOnEdge,
      leak: touchedBorder || count >= 0.9 * maxArea,
    };
  }

  function dilate3x3(mask, size) {
    const out = new Uint8Array(mask.length);
    for (let j = 0; j < size; j++) {
      for (let i = 0; i < size; i++) {
        if (!mask[j * size + i]) continue;
        for (let dj = -1; dj <= 1; dj++) {
          const jj = j + dj;
          if (jj < 0 || jj >= size) continue;
          for (let di = -1; di <= 1; di++) {
            const ii = i + di;
            if (ii < 0 || ii >= size) continue;
            out[jj * size + ii] = 1;
          }
        }
      }
    }
    return out;
  }

  function erode3x3(mask, size) {
    const out = new Uint8Array(mask.length);
    for (let j = 0; j < size; j++) {
      for (let i = 0; i < size; i++) {
        let keep = mask[j * size + i] === 1;
        for (let dj = -1; keep && dj <= 1; dj++) {
          const jj = j + dj;
          for (let di = -1; keep && di <= 1; di++) {
            const ii = i + di;
            if (ii < 0 || jj < 0 || ii >= size || jj >= size) continue; // outside box counts as set
            if (!mask[jj * size + ii]) keep = false;
          }
        }
        if (keep) out[j * size + i] = 1;
      }
    }
    return out;
  }

  function closeMask3x3(mask, size) {
    return erode3x3(dilate3x3(mask, size), size);
  }

  // Flood the background from the box border; any zero pixel not reached is a
  // hole inside the region and gets filled.
  function fillHoles(mask, size) {
    const reached = new Uint8Array(mask.length);
    const qi = new Int32Array(mask.length);
    const qj = new Int32Array(mask.length);
    let head = 0;
    let tail = 0;
    const push = (i, j) => {
      const idx = j * size + i;
      if (reached[idx] || mask[idx]) return;
      reached[idx] = 1;
      qi[tail] = i;
      qj[tail] = j;
      tail++;
    };
    for (let k = 0; k < size; k++) {
      push(k, 0);
      push(k, size - 1);
      push(0, k);
      push(size - 1, k);
    }
    while (head < tail) {
      const i = qi[head];
      const j = qj[head];
      head++;
      if (i > 0) push(i - 1, j);
      if (i < size - 1) push(i + 1, j);
      if (j > 0) push(i, j - 1);
      if (j < size - 1) push(i, j + 1);
    }
    const out = new Uint8Array(mask.length);
    for (let idx = 0; idx < mask.length; idx++) {
      out[idx] = mask[idx] || !reached[idx] ? 1 : 0;
    }
    return out;
  }

  // Keep only the connected component (8-connectivity) containing the seed.
  // Keep only the components the doctor pointed at. A stroke can legitimately
  // straddle two blobs that the growth never joined; both are kept, and
  // anything the growth reached without a seed in it is dropped.
  function keepSeedComponents(mask, size, seeds, width, x0, y0) {
    const out = new Uint8Array(mask.length);
    const qi = new Int32Array(mask.length);
    const qj = new Int32Array(mask.length);
    let head = 0;
    let tail = 0;
    let count = 0;
    for (let s = 0; s < seeds.length; s++) {
      const offset = seeds[s];
      const i = (offset % width) - x0;
      const j = ((offset - (offset % width)) / width) - y0;
      if (i < 0 || j < 0 || i >= size || j >= size) continue;
      const idx = j * size + i;
      if (!mask[idx] || out[idx]) continue;
      out[idx] = 1;
      qi[tail] = i;
      qj[tail] = j;
      tail++;
    }
    while (head < tail) {
      const i = qi[head];
      const j = qj[head];
      head++;
      count++;
      for (let dj = -1; dj <= 1; dj++) {
        for (let di = -1; di <= 1; di++) {
          if (!di && !dj) continue;
          const ii = i + di;
          const jj = j + dj;
          if (ii < 0 || jj < 0 || ii >= size || jj >= size) continue;
          const idx = jj * size + ii;
          if (!mask[idx] || out[idx]) continue;
          out[idx] = 1;
          qi[tail] = ii;
          qj[tail] = jj;
          tail++;
        }
      }
    }
    return { mask: out, count };
  }

  // Canvas path -> distinct image pixels. Gaps between two pointer events are
  // filled in, so a fast drag does not leave holes in the seed set.
  function seedsFromPath(viewport, points, width, height) {
    const seeds = [];
    const seen = new Set();
    const push = offset => {
      if (offset == null || seen.has(offset)) return;
      seen.add(offset);
      seeds.push(offset);
    };
    for (let k = 0; k < points.length; k++) {
      const [x, y] = points[k];
      if (k > 0) {
        const [px, py] = points[k - 1];
        const steps = Math.min(512, Math.ceil(Math.hypot(x - px, y - py)));
        for (let s = 1; s < steps; s++) {
          const t = s / steps;
          push(scalarOffsetFromCanvas(viewport, px + (x - px) * t, py + (y - py) * t));
        }
      }
      push(scalarOffsetFromCanvas(viewport, x, y));
    }
    return seeds;
  }

  // Does this path come back on itself? Three conditions, because two of them
  // alone are not enough: an out-and-back scribble also ends where it started,
  // and a tiny wiggle also encloses its own bounding box.
  //
  // The area is the discriminator. Computed by the shoelace formula on the
  // implicitly closed polygon, it is near zero for a there-and-back line and
  // about 0.79 of the bounding box for a circle.
  function strokeCloses(points) {
    if (!points || points.length < LASSO_MIN_POINTS) return false;
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    let twiceArea = 0;
    for (let k = 0; k < points.length; k++) {
      const [x, y] = points[k];
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
      const [nx, ny] = points[(k + 1) % points.length];
      twiceArea += x * ny - nx * y;
    }
    const boxArea = (maxX - minX) * (maxY - minY);
    if (boxArea < 144) return false; // smaller than 12 x 12: not a deliberate loop
    const area = Math.abs(twiceArea) / 2;
    if (area < 0.2 * boxArea) return false;
    const [sx, sy] = points[0];
    const [ex, ey] = points[points.length - 1];
    const diagonal = Math.hypot(maxX - minX, maxY - minY);
    return Math.hypot(ex - sx, ey - sy) <= Math.max(LASSO_CLOSE_PX, 0.15 * diagonal);
  }

  // Bresenham, in image coordinates. The canvas-space interpolation used for
  // seeding is not enough here: zoomed out, one canvas step spans several
  // image pixels and would leave gaps the fill could escape through.
  function rasteriseSegment(out, x0, y0, x1, y1) {
    let x = x0;
    let y = y0;
    const dx = Math.abs(x1 - x0);
    const dy = -Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1;
    const sy = y0 < y1 ? 1 : -1;
    let err = dx + dy;
    for (;;) {
      out.push(x, y);
      if (x === x1 && y === y1) break;
      const e2 = 2 * err;
      if (e2 >= dy) {
        err += dy;
        x += sx;
      }
      if (e2 <= dx) {
        err += dx;
        y += sy;
      }
    }
  }

  // Fill the inside of a closed outline. The outline is rasterised
  // 8-connected, then everything the outside cannot reach is the inside: the
  // same flood-from-the-border argument as fillHoles, whose flood is
  // 4-connected and is therefore blocked by an 8-connected curve.
  //
  // Nothing here looks at the pixels. That is the point of the gesture: where
  // the propagation decides for you, the outline is yours alone.
  function computeLassoRegion(fundus, viewport, points) {
    const { width, height } = fundus;
    const vertices = [];
    for (let k = 0; k < points.length; k++) {
      const offset = scalarOffsetFromCanvas(viewport, points[k][0], points[k][1]);
      if (offset == null) continue;
      const i = offset % width;
      const j = (offset - i) / width;
      const last = vertices.length;
      if (last && vertices[last - 2] === i && vertices[last - 1] === j) continue;
      vertices.push(i, j);
    }
    if (vertices.length < 6) return { error: 'outside' };

    const pixels = [];
    for (let v = 0; v + 1 < vertices.length; v += 2) {
      const n = (v + 2) % vertices.length; // the last segment closes the loop
      rasteriseSegment(pixels, vertices[v], vertices[v + 1], vertices[n], vertices[n + 1]);
    }

    let minI = Infinity;
    let maxI = -Infinity;
    let minJ = Infinity;
    let maxJ = -Infinity;
    for (let p = 0; p < pixels.length; p += 2) {
      if (pixels[p] < minI) minI = pixels[p];
      if (pixels[p] > maxI) maxI = pixels[p];
      if (pixels[p + 1] < minJ) minJ = pixels[p + 1];
      if (pixels[p + 1] > maxJ) maxJ = pixels[p + 1];
    }
    // Two pixels of slack all round, so the flood always has a way past the
    // outline even when it touches the edge of the box.
    const half = Math.ceil(Math.max(maxI - minI, maxJ - minJ) / 2) + 2;
    if (half > LASSO_MAX_HALF) return { error: 'too-big' };
    const size = 2 * half + 1;
    const x0 = Math.round((minI + maxI) / 2) - half;
    const y0 = Math.round((minJ + maxJ) / 2) - half;

    const outline = new Uint8Array(size * size);
    for (let p = 0; p < pixels.length; p += 2) {
      const bi = pixels[p] - x0;
      const bj = pixels[p + 1] - y0;
      if (bi < 0 || bj < 0 || bi >= size || bj >= size) continue;
      outline[bj * size + bi] = 1;
    }

    const filled = fillHoles(outline, size);
    let count = 0;
    for (let p = 0; p < filled.length; p++) {
      if (!filled[p]) continue;
      const bi = p % size;
      const bj = (p - bi) / size;
      const i = x0 + bi;
      const j = y0 + bj;
      // Clipped against the image, so the reported area matches what is written.
      if (i < 0 || j < 0 || i >= width || j >= height) {
        filled[p] = 0;
        continue;
      }
      count++;
    }
    if (count < 3) return { error: 'no-lesion' };
    return { region: { mask: filled, size, x0, y0, count, leak: false }, lasso: true };
  }

  // Full pipeline for one gesture. `points` holds canvas coordinates: a single
  // one for a click, the sampled path for a stroke. Returns { error } or
  // { region, polarity, seeds, ... }.
  function computeWandRegion(fundus, viewport, points) {
    const { gradient, width, height } = fundus;
    const green = getWandSetting('flatten') && fundus.flat ? fundus.flat : fundus.data;
    const tolerance = getWandSetting('tolerance');
    const radius = getWandSetting('radius');

    const seeds = seedsFromPath(viewport, points, width, height);
    if (!seeds.length) return { error: 'outside' };

    // The seed level is the median over the whole path, not the value under
    // one pixel: that is what makes a stroke steadier than a click when the
    // lesion is heterogeneous.
    const values = [];
    let minI = Infinity;
    let maxI = -Infinity;
    let minJ = Infinity;
    let maxJ = -Infinity;
    for (let s = 0; s < seeds.length; s++) {
      const offset = seeds[s];
      const i = offset % width;
      const j = (offset - i) / width;
      if (i < minI) minI = i;
      if (i > maxI) maxI = i;
      if (j < minJ) minJ = j;
      if (j > maxJ) maxJ = j;
      values.push(mean3x3(green, width, height, i, j));
    }
    values.sort((a, b) => a - b);
    const seedValue = values[values.length >> 1];
    if (seedValue < 8) return { error: 'outside' }; // black mask around the retina

    const background = medianOnRings(green, width, height, seeds, radius);
    if (background == null) return { error: 'outside' };
    const margin = Math.abs(seedValue - background);
    if (margin < 4) return { error: 'no-lesion' };
    const polarity = seedValue < background ? 'dark' : 'bright';

    // A square box covering the whole path plus the growth radius on each
    // side. Square, so every mask helper downstream keeps a single dimension.
    const centreI = Math.round((minI + maxI) / 2);
    const centreJ = Math.round((minJ + maxJ) / 2);
    const half = Math.min(
      WAND_MAX_BOX_HALF,
      Math.ceil(Math.max(maxI - minI, maxJ - minJ) / 2) + radius
    );
    // Plausible area: the disc of a click, widened by what a disc of the same
    // radius sweeps along the path (a Minkowski sum).
    const span = Math.hypot(maxI - minI, maxJ - minJ);
    const box = {
      x0: centreI - half,
      y0: centreJ - half,
      size: 2 * half + 1,
      maxArea: Math.PI * radius * radius + span * 2 * radius,
    };

    const edgeThreshold = gradientThreshold(
      gradient, width, height, centreI, centreJ, half, getWandSetting('edges')
    );
    const field = {
      green,
      chromaA: fundus.chroma ? fundus.chroma.a : null,
      chromaB: fundus.chroma ? fundus.chroma.b : null,
      weight: getWandSetting('colour') / 100,
    };
    const grown = growRegion(
      field, width, height, seeds, tolerance, box,
      polarity, background, margin, gradient, edgeThreshold
    );
    if (grown.count < 3) return { error: 'no-lesion' };
    const closed = closeMask3x3(grown.mask, grown.size);
    const filled = fillHoles(closed, grown.size);
    const kept = keepSeedComponents(filled, grown.size, seeds, width, grown.x0, grown.y0);
    if (kept.count < 3) return { error: 'no-lesion' };
    return {
      region: { mask: kept.mask, size: grown.size, x0: grown.x0, y0: grown.y0, count: kept.count, leak: grown.leak },
      polarity,
      seeds,
      offset: seeds[0],
    };
  }

  // Suggest a tolerance from the local noise around a point: about two standard
  // deviations of an 11x11 window, so the doctor rarely has to tune it by hand.
  function suggestTolerance(fundus, viewport, canvasX, canvasY) {
    const offset = scalarOffsetFromCanvas(viewport, canvasX, canvasY);
    if (offset == null || !fundus) return null;
    const { width, height } = fundus;
    const green = getWandSetting('flatten') && fundus.flat ? fundus.flat : fundus.data;
    const ci = offset % width;
    const cj = Math.floor(offset / width);
    let sum = 0;
    let sumSquares = 0;
    let n = 0;
    for (let j = cj - 5; j <= cj + 5; j++) {
      if (j < 0 || j >= height) continue;
      for (let i = ci - 5; i <= ci + 5; i++) {
        if (i < 0 || i >= width) continue;
        const v = green[j * width + i];
        sum += v;
        sumSquares += v * v;
        n++;
      }
    }
    if (n < 9) return null;
    const mean = sum / n;
    const sigma = Math.sqrt(Math.max(0, sumSquares / n - mean * mean));
    return clampWandSetting('tolerance', Math.round(2 * sigma));
  }

  // Write the region into the active labelmap through the accessor, recording
  // previous values so Annuler/Retablir work exactly like a pencil stroke.
  function applyRegionToLabelmap(accessor, region, width, height, writeValue, viewport) {
    const data = accessor?.getScalarData?.();
    if (!data) return 0;
    const strokeDiff = new Map();
    let changed = 0;
    for (let bj = 0; bj < region.size; bj++) {
      const j = region.y0 + bj;
      if (j < 0 || j >= height) continue;
      for (let bi = 0; bi < region.size; bi++) {
        if (!region.mask[bj * region.size + bi]) continue;
        const i = region.x0 + bi;
        if (i < 0 || i >= width) continue;
        const off = j * width + i;
        if (data[off] === writeValue) continue;
        strokeDiff.set(off, data[off]);
        data[off] = writeValue;
        changed++;
      }
    }
    if (changed) {
      accessor.setScalarData(data);
      pushUndoEntry(accessor.segmentationId, strokeDiff);
      notifySegmentationModified(accessor.segmentationId);
      viewport?.render?.();
    }
    return changed;
  }

  // Alt+click: erase the whole connected blob of the labelmap under the cursor.
  function eraseComponentAt(accessor, width, height, offset, viewport) {
    const data = accessor?.getScalarData?.();
    if (!data) return { changed: 0, reason: 'no-data' };
    const value = data[offset];
    if (!value) return { changed: 0, reason: 'empty' };
    const visited = new Uint8Array(data.length);
    const stack = [offset];
    visited[offset] = 1;
    const members = [];
    while (stack.length) {
      const off = stack.pop();
      members.push(off);
      if (members.length > WAND_MAX_ERASE_COMPONENT) return { changed: 0, reason: 'too-big' };
      const i = off % width;
      const j = Math.floor(off / width);
      for (let dj = -1; dj <= 1; dj++) {
        const jj = j + dj;
        if (jj < 0 || jj >= height) continue;
        for (let di = -1; di <= 1; di++) {
          if (!di && !dj) continue;
          const ii = i + di;
          if (ii < 0 || ii >= width) continue;
          const n = jj * width + ii;
          if (visited[n] || data[n] !== value) continue;
          visited[n] = 1;
          stack.push(n);
        }
      }
    }
    const strokeDiff = new Map();
    members.forEach(off => {
      strokeDiff.set(off, data[off]);
      data[off] = 0;
    });
    accessor.setScalarData(data);
    pushUndoEntry(accessor.segmentationId, strokeDiff);
    notifySegmentationModified(accessor.segmentationId);
    viewport?.render?.();
    return { changed: members.length, reason: 'ok', value };
  }

  // Affine transform image index (i, j) -> canvas (x, y) for the current view,
  // derived from three probe points so it follows zoom/pan/flip exactly.
  function indexToCanvasTransform(viewport) {
    const result = viewport?.getImageData?.();
    const imageData = result?.imageData || result;
    if (!imageData?.indexToWorld || !viewport?.worldToCanvas) return null;
    const p0 = viewport.worldToCanvas(imageData.indexToWorld([0, 0, 0]));
    const px = viewport.worldToCanvas(imageData.indexToWorld([1, 0, 0]));
    const py = viewport.worldToCanvas(imageData.indexToWorld([0, 1, 0]));
    if (!p0 || !px || !py) return null;
    return {
      a: px[0] - p0[0], b: px[1] - p0[1],
      c: py[0] - p0[0], d: py[1] - p0[1],
      e: p0[0], f: p0[1],
    };
  }

  function activeSegmentCss(viewportId, segmentationId, alpha) {
    try {
      const index = resolveActiveSegmentIndex(viewportId);
      const segment = segmentsForSegmentation(segmentationId).find(s => s.segmentIndex === index);
      const color = segment?.color;
      if (Array.isArray(color) && color.length >= 3) {
        return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha})`;
      }
    } catch (_) {
      // fall through
    }
    return `rgba(34, 197, 94, ${alpha})`;
  }

  function showWandPreview(element, viewportId) {
    hideWandPreview(viewportId);
    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-hidden', 'true');
    canvas.setAttribute('data-teleoph-overlay', 'wand-preview');
    Object.assign(canvas.style, {
      position: 'absolute', inset: '0', width: '100%', height: '100%',
      pointerEvents: 'none', zIndex: '11',
    });
    element.appendChild(canvas);
    const record = { canvas };
    wandPreviews.set(viewportId, record);
    return record;
  }

  function hideWandPreview(viewportId) {
    const record = wandPreviews.get(viewportId);
    if (record) {
      record.canvas.remove();
      wandPreviews.delete(viewportId);
    }
  }

  function clearWandPreview(record) {
    const ctx = record?.canvas?.getContext?.('2d');
    if (ctx) ctx.clearRect(0, 0, record.canvas.width, record.canvas.height);
  }

  function drawWandPreview(record, viewport, viewportId, segmentationId, result, pointer, strokePath) {
    const canvas = record?.canvas;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const wantW = Math.max(1, Math.round(rect.width * dpr));
    const wantH = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== wantW || canvas.height !== wantH) {
      canvas.width = wantW;
      canvas.height = wantH;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const t = indexToCanvasTransform(viewport);
    const pixelScale = t ? Math.hypot(t.a, t.b) : 1;

    if (result?.region && t) {
      const { mask, size, x0, y0 } = result.region;
      const fill = activeSegmentCss(viewportId, segmentationId, 0.35);
      const edge = result.region.leak ? 'rgba(248, 113, 113, 0.95)' : activeSegmentCss(viewportId, segmentationId, 0.95);
      ctx.save();
      ctx.transform(t.a, t.b, t.c, t.d, t.e, t.f);
      ctx.fillStyle = fill;
      for (let bj = 0; bj < size; bj++) {
        for (let bi = 0; bi < size; bi++) {
          if (mask[bj * size + bi]) ctx.fillRect(x0 + bi - 0.5, y0 + bj - 0.5, 1, 1);
        }
      }
      ctx.fillStyle = edge;
      for (let bj = 0; bj < size; bj++) {
        for (let bi = 0; bi < size; bi++) {
          const idx = bj * size + bi;
          if (!mask[idx]) continue;
          const isEdge =
            bi === 0 || bj === 0 || bi === size - 1 || bj === size - 1 ||
            !mask[idx - 1] || !mask[idx + 1] || !mask[idx - size] || !mask[idx + size];
          if (isEdge) ctx.fillRect(x0 + bi - 0.5, y0 + bj - 0.5, 1, 1);
        }
      }
      ctx.restore();
    }

    // While the button is held, the path itself is the feedback: the region
    // is only grown on release, since regrowing it on every move would cost a
    // full box scan per pointer event.
    if (strokePath && strokePath.length > 1) {
      const closes = strokeCloses(strokePath);
      const colour = activeSegmentCss(viewportId, segmentationId, 0.95);
      const trace = () => {
        ctx.beginPath();
        ctx.moveTo(strokePath[0][0], strokePath[0][1]);
        for (let k = 1; k < strokePath.length; k++) ctx.lineTo(strokePath[k][0], strokePath[k][1]);
      };
      ctx.save();
      // As soon as the loop would close, the preview switches to showing the
      // filled outline: releasing now paints exactly that, and nothing else.
      if (closes) {
        ctx.fillStyle = activeSegmentCss(viewportId, segmentationId, 0.3);
        trace();
        ctx.closePath();
        ctx.fill();
      }
      ctx.strokeStyle = colour;
      ctx.lineWidth = 3;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      trace();
      ctx.stroke();
      if (closes) {
        // The chord the release will add, drawn dashed so the shut is visible.
        ctx.setLineDash([5, 4]);
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(strokePath[strokePath.length - 1][0], strokePath[strokePath.length - 1][1]);
        ctx.lineTo(strokePath[0][0], strokePath[0][1]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // Where the loop has to come back to.
      ctx.fillStyle = closes ? colour : 'rgba(255, 255, 255, 0.9)';
      ctx.beginPath();
      ctx.arc(strokePath[0][0], strokePath[0][1], 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    if (pointer) {
      const [x, y] = pointer;
      const r = Math.max(4, getWandSetting('radius') * pixelScale);
      ctx.save();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.85)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(x - 8, y); ctx.lineTo(x + 8, y);
      ctx.moveTo(x, y - 8); ctx.lineTo(x, y + 8);
      ctx.stroke();
      ctx.restore();
    }
  }

  function buildSettingRow({ label, key, unit, step, accent }) {
    const [min, max] = WAND_LIMITS[key];
    const row = document.createElement('div');
    Object.assign(row.style, { display: 'flex', alignItems: 'center', gap: '6px' });

    const name = document.createElement('span');
    name.textContent = label;
    Object.assign(name.style, { minWidth: '64px', color: '#cbd5e1' });

    const makeButton = text => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = text;
      Object.assign(button.style, {
        width: '22px', height: '22px', lineHeight: '20px', padding: '0',
        borderRadius: '4px', border: '1px solid rgba(255,255,255,0.35)',
        background: 'rgba(255,255,255,0.08)', color: '#f8fafc',
        fontSize: '14px', fontWeight: '700', cursor: 'pointer',
      });
      return button;
    };
    const minus = makeButton('−');
    const plus = makeButton('+');
    const value = document.createElement('span');
    Object.assign(value.style, { minWidth: '46px', textAlign: 'center', fontVariantNumeric: 'tabular-nums' });
    const range = document.createElement('input');
    range.type = 'range';
    range.min = String(min);
    range.max = String(max);
    range.step = String(step);
    Object.assign(range.style, { width: '90px', cursor: 'pointer', accentColor: accent });

    const refresh = () => {
      const current = getWandSetting(key);
      value.textContent = `${current}${unit}`;
      if (range.value !== String(current)) range.value = String(current);
      minus.disabled = current <= min;
      plus.disabled = current >= max;
      minus.style.opacity = minus.disabled ? '0.4' : '1';
      plus.style.opacity = plus.disabled ? '0.4' : '1';
    };
    minus.addEventListener('click', () => setWandSetting(key, getWandSetting(key) - step));
    plus.addEventListener('click', () => setWandSetting(key, getWandSetting(key) + step));
    range.addEventListener('input', () => setWandSetting(key, range.value));

    row.appendChild(name);
    row.appendChild(minus);
    row.appendChild(value);
    row.appendChild(plus);
    row.appendChild(range);
    refresh();
    return { row, refresh };
  }

  function buildToggleRow({ label, key, accent }) {
    const row = document.createElement('label');
    Object.assign(row.style, {
      display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer',
    });
    const box = document.createElement('input');
    box.type = 'checkbox';
    Object.assign(box.style, { cursor: 'pointer', accentColor: accent, margin: 0 });
    const name = document.createElement('span');
    name.textContent = label;
    Object.assign(name.style, { color: '#cbd5e1' });
    const refresh = () => {
      box.checked = !!getWandSetting(key);
    };
    box.addEventListener('change', () => setWandSetting(key, box.checked ? 1 : 0));
    row.appendChild(box);
    row.appendChild(name);
    refresh();
    return { row, refresh };
  }

  function showWandPanel(element, viewportId) {
    hideWandPanel(viewportId);
    const accent = '#38bdf8';
    const panel = document.createElement('div');
    panel.setAttribute('data-wand-panel', '1');
    Object.assign(panel.style, {
      position: 'absolute', top: '8px', right: '8px', zIndex: '20',
      display: 'flex', flexDirection: 'column', gap: '4px',
      padding: '6px 8px', borderRadius: '6px',
      background: 'rgba(15, 23, 42, 0.88)', border: `1px solid ${accent}`,
      color: '#f8fafc', font: '12px system-ui, -apple-system, "Segoe UI", sans-serif',
      cursor: 'default', userSelect: 'none', pointerEvents: 'auto',
      boxShadow: '0 1px 4px rgba(0,0,0,0.5)',
    });
    const title = document.createElement('div');
    title.textContent = 'Baguette';
    Object.assign(title.style, { fontWeight: '600', color: accent });
    const tolerance = buildSettingRow({ label: 'Tolérance', key: 'tolerance', unit: '', step: 1, accent });
    const radius = buildSettingRow({ label: 'Rayon max', key: 'radius', unit: ' px', step: 1, accent });
    const edges = buildSettingRow({ label: 'Contours', key: 'edges', unit: ' %', step: 1, accent });
    const colour = buildSettingRow({ label: 'Couleur', key: 'colour', unit: ' %', step: 5, accent });
    const flatten = buildToggleRow({ label: "Corriger l'éclairement", key: 'flatten', accent });
    const hint = document.createElement('div');
    hint.textContent = 'Clic ou glisser le long de la lésion · Boucle fermée : le contour est rempli';
    Object.assign(hint.style, { color: '#94a3b8', fontSize: '11px' });
    const hint2 = document.createElement('div');
    hint2.textContent = 'Alt + clic : supprimer · Maj + clic : régler la tolérance';
    Object.assign(hint2.style, { color: '#94a3b8', fontSize: '11px' });

    [
      'pointerdown', 'pointermove', 'pointerup', 'pointerleave', 'pointercancel',
      'mousedown', 'mousemove', 'mouseup', 'click', 'dblclick', 'contextmenu',
      'wheel', 'touchstart', 'touchmove', 'touchend', 'keydown',
    ].forEach(type => panel.addEventListener(type, event => event.stopPropagation()));

    panel.appendChild(title);
    panel.appendChild(tolerance.row);
    panel.appendChild(radius.row);
    panel.appendChild(edges.row);
    panel.appendChild(colour.row);
    panel.appendChild(flatten.row);
    panel.appendChild(hint);
    panel.appendChild(hint2);
    element.appendChild(panel);
    const record = {
      panel,
      refresh: () => {
        tolerance.refresh();
        radius.refresh();
        edges.refresh();
        colour.refresh();
        flatten.refresh();
      },
    };
    wandPanels.set(viewportId, record);
    return record;
  }

  function hideWandPanel(viewportId) {
    const record = wandPanels.get(viewportId);
    if (record) {
      record.panel.remove();
      wandPanels.delete(viewportId);
    }
  }

  async function toggleSegmentationWand() {
    const modeLabel = 'Baguette';
    try {
      await loadCornerstone();
      const { activeViewportId, viewport } = getActiveViewport();
      const element = viewport?.element;
      if (!activeViewportId || !element) {
        reportSegmentationError(modeLabel, 'setup', new Error('Aucun viewport actif trouvé.'));
        return;
      }

      const existing = editSessions.get(activeViewportId);
      if (existing) {
        const wasSameMode = existing.mode === 'wand';
        existing.cleanup();
        editSessions.delete(activeViewportId);
        hideBrushCursor(activeViewportId);
        hideBrushPanel(activeViewportId);
        hideWandPanel(activeViewportId);
        hideWandPreview(activeViewportId);
        if (wasSameMode) {
          uiNotificationService.show({ title: modeLabel, message: 'Baguette désactivée.', type: 'info', duration: 1600 });
          return;
        }
      }

      let segmentationId = ensureActiveSegmentationId(activeViewportId);
      if (!segmentationId) {
        segmentationId = await loadSegmentationForEditing(activeViewportId, modeLabel);
        if (!segmentationId) return;
      }
      const accessor = segmentationId
        ? getLabelmapAccessor(segmentationId, activeViewportId, viewport)
        : null;
      let labelmap = null;
      try {
        labelmap = accessor ? accessor.getScalarData() : null;
      } catch (err) {
        console.warn('[SegmentationEdit] wand getScalarData failed', err);
      }
      if (!accessor || !labelmap) {
        uiNotificationService.show({
          title: modeLabel,
          message: segmentationId
            ? 'Segmentation trouvée mais ses pixels ne sont pas accessibles (voir console).'
            : "Aucune segmentation chargée. Cliquez sur CHARGER en haut à droite de l'image, puis réessayez.",
          type: 'warning',
          duration: 3500,
        });
        return;
      }

      const fundus = getFundusGreenChannel(viewport);
      console.log(
        '[SegmentationEdit] wand segmentationId=', segmentationId,
        'accessor.kind=', accessor.kind,
        'fundus=', fundus?.width, 'x', fundus?.height,
        'labelmap=', labelmap.length
      );
      if (!fundus) {
        uiNotificationService.show({ title: modeLabel, message: "Pixels de l'image de fond d'œil inaccessibles.", type: 'warning', duration: 3500 });
        return;
      }
      if (fundus.width * fundus.height !== labelmap.length) {
        uiNotificationService.show({
          title: modeLabel,
          message: `Dimensions image (${fundus.width}×${fundus.height}) et segmentation (${labelmap.length} px) différentes.`,
          type: 'warning',
          duration: 4000,
        });
        return;
      }

      ensureAllSegmentClasses(segmentationId, activeViewportId);
      ensureOriginalSnapshot(accessor);
      const previousCursor = element.style.cursor;
      element.style.cursor = 'none';
      const preview = showWandPreview(element, activeViewportId);
      showWandPanel(element, activeViewportId);

      let lastPointer = null;
      let pending = false;
      const pointFromEvent = event => {
        const rect = element.getBoundingClientRect();
        return [event.clientX - rect.left, event.clientY - rect.top];
      };
      const runPreview = () => {
        if (!lastPointer) {
          clearWandPreview(preview);
          return;
        }
        const [x, y] = lastPointer;
        const result = computeWandRegion(fundus, viewport, [[x, y]]);
        drawWandPreview(preview, viewport, activeViewportId, segmentationId, result, lastPointer);
      };
      const schedulePreview = () => {
        if (pending) return;
        pending = true;
        setTimeout(() => {
          pending = false;
          try {
            runPreview();
          } catch (err) {
            reportSegmentationError(modeLabel, 'preview', err);
          }
        }, 40);
      };
      const messageForError = code => {
        if (code === 'no-lesion') return 'Aucune lésion détectée ici : augmentez la tolérance ou utilisez le Crayon.';
        if (code === 'outside') return "Cliquez à l'intérieur de la rétine.";
        return 'Propagation impossible à cet endroit.';
      };
      const messageForLassoError = code => {
        if (code === 'too-big') return 'Contour trop grand pour être rempli en une fois.';
        if (code === 'outside') return "Tracez la boucle à l'intérieur de l'image.";
        return 'Contour trop petit pour être rempli.';
      };

      // The gesture is a stroke: press, drag, release. A plain click is just a
      // stroke of one point, so both go through the same code.
      let stroke = null;
      let strokePointerId = null;

      const applyStroke = path => {
        // A loop is an outline, and an outline is filled as drawn: no
        // propagation, no threshold, no surprise. An open stroke still seeds
        // the region growing.
        const closed = strokeCloses(path);
        const result = closed
          ? computeLassoRegion(fundus, viewport, path)
          : computeWandRegion(fundus, viewport, path);
        if (result.error) {
          uiNotificationService.show({
            title: modeLabel,
            message: closed ? messageForLassoError(result.error) : messageForError(result.error),
            type: 'info',
            duration: 2500,
          });
          return;
        }
        const writeValue = resolveActiveSegmentIndex(activeViewportId) ?? 1;
        const changed = applyRegionToLabelmap(accessor, result.region, fundus.width, fundus.height, writeValue, viewport);
        if (changed) usedModesThisSession.add('wand');
        if (result.region.leak) {
          uiNotificationService.show({
            title: modeLabel,
            message: 'Propagation trop large : baissez la tolérance ou le rayon (Annuler pour revenir en arrière).',
            type: 'warning',
            duration: 3500,
          });
          return;
        }
        if (!changed) {
          uiNotificationService.show({ title: modeLabel, message: 'Cette lésion est déjà segmentée dans cette classe.', type: 'info', duration: 1400 });
          return;
        }
        uiNotificationService.show({
          title: modeLabel,
          message: closed
            ? `Contour rempli (${result.region.count} px).`
            : path.length > 1
              ? `Lésion dessinée (${result.region.count} px) à partir d'un trait de ${result.seeds.length} points.`
              : `Lésion dessinée (${result.region.count} px).`,
          type: 'info',
          duration: 1400,
        });
      };

      const endStroke = (event, apply) => {
        const path = stroke;
        stroke = null;
        if (strokePointerId != null) {
          try { element.releasePointerCapture(strokePointerId); } catch (_) {}
          strokePointerId = null;
        }
        if (!path) return;
        if (apply) {
          const point = pointFromEvent(event);
          const [lx, ly] = path[path.length - 1];
          if (Math.hypot(point[0] - lx, point[1] - ly) >= 2) path.push(point);
          applyStroke(path);
        }
        schedulePreview();
      };

      const pointerMove = event => {
        const point = pointFromEvent(event);
        lastPointer = point;
        if (stroke) {
          const [lx, ly] = stroke[stroke.length - 1];
          // Two pixels is enough to follow the hand without filling the path
          // with near-duplicates; the gaps get interpolated anyway.
          if (Math.hypot(point[0] - lx, point[1] - ly) >= 2) stroke.push(point);
          drawWandPreview(preview, viewport, activeViewportId, segmentationId, null, point, stroke);
          return;
        }
        schedulePreview();
      };
      const pointerLeave = () => {
        if (stroke) return; // the pointer is captured, the stroke continues
        lastPointer = null;
        clearWandPreview(preview);
      };
      const pointerUp = event => {
        try {
          endStroke(event, true);
        } catch (err) {
          stroke = null;
          strokePointerId = null;
          reportSegmentationError(modeLabel, 'stroke', err);
        }
      };
      const pointerCancel = event => {
        try {
          endStroke(event, false);
        } catch (_) {
          stroke = null;
          strokePointerId = null;
        }
      };
      const pointerDown = event => {
        try {
          event.preventDefault();
          const [x, y] = pointFromEvent(event);
          lastPointer = [x, y];

          if (event.shiftKey) {
            const suggested = suggestTolerance(fundus, viewport, x, y);
            if (suggested != null) {
              setWandSetting('tolerance', suggested);
              uiNotificationService.show({
                title: modeLabel,
                message: `Tolérance réglée sur ${suggested} d'après le bruit local.`,
                type: 'info',
                duration: 2000,
              });
            }
            schedulePreview();
            return;
          }

          if (event.altKey) {
            const offset = scalarOffsetFromCanvas(viewport, x, y);
            if (offset == null) return;
            const result = eraseComponentAt(accessor, fundus.width, fundus.height, offset, viewport);
            if (result.changed) {
              usedModesThisSession.add('wand');
              uiNotificationService.show({ title: modeLabel, message: `Lésion supprimée (${result.changed} px).`, type: 'info', duration: 1500 });
            } else if (result.reason === 'too-big') {
              uiNotificationService.show({ title: modeLabel, message: 'Zone trop grande pour être supprimée en un clic (vaisseaux ?). Utilisez la Gomme.', type: 'warning', duration: 3500 });
            } else {
              uiNotificationService.show({ title: modeLabel, message: 'Aucune segmentation sous le curseur.', type: 'info', duration: 1500 });
            }
            schedulePreview();
            return;
          }

          // Start a stroke. Dragging along the lesion feeds the growth several
          // seeds instead of one, so the starting mean is measured on a sample
          // of the lesion rather than on a single pixel, and the doctor points
          // at the shape instead of hoping one spot is representative.
          stroke = [[x, y]];
          strokePointerId = event.pointerId;
          try { element.setPointerCapture(event.pointerId); } catch (_) {}
          drawWandPreview(preview, viewport, activeViewportId, segmentationId, null, [x, y], stroke);
        } catch (err) {
          stroke = null;
          reportSegmentationError(modeLabel, 'click', err);
        }
      };
      const wheel = event => {
        if (event.ctrlKey) {
          setWandSetting('tolerance', getWandSetting('tolerance') + (event.deltaY > 0 ? -1 : 1));
          event.preventDefault();
        } else if (event.altKey) {
          setWandSetting('radius', getWandSetting('radius') + (event.deltaY > 0 ? -1 : 1));
          event.preventDefault();
        }
      };

      element.addEventListener('pointerdown', pointerDown);
      element.addEventListener('pointermove', pointerMove);
      element.addEventListener('pointerup', pointerUp);
      element.addEventListener('pointercancel', pointerCancel);
      element.addEventListener('pointerleave', pointerLeave);
      element.addEventListener('wheel', wheel, { passive: false });

      editSessions.set(activeViewportId, {
        mode: 'wand',
        onSettingsChanged: schedulePreview,
        cleanup: () => {
          element.style.cursor = previousCursor;
          element.removeEventListener('pointerdown', pointerDown);
          element.removeEventListener('pointermove', pointerMove);
          element.removeEventListener('pointerup', pointerUp);
          element.removeEventListener('pointercancel', pointerCancel);
          element.removeEventListener('pointerleave', pointerLeave);
          element.removeEventListener('wheel', wheel);
        },
      });

      uiNotificationService.show({
        title: modeLabel,
        message: `Baguette active (tolérance ${getWandSetting('tolerance')}, rayon ${getWandSetting('radius')} px, contours ${getWandSetting('edges')} %). Clic : dessiner. Alt + clic : supprimer. Maj + clic : régler la tolérance. Ctrl + molette : tolérance.`,
        type: 'success',
        duration: 4000,
      });
    } catch (err) {
      reportSegmentationError(modeLabel, 'setup', err);
    }
  }

  function toggleSegmentationEraser() {
    toggleSegmentationEdit('erase');
  }

  function toggleSegmentationPencil() {
    toggleSegmentationEdit('pencil');
  }

  // Single entry point for the toolbar: regenerate the AI report once the
  // doctor has finished correcting and checking everything.
  async function regenerateAiReport() {
    const studyInstanceUid = currentStudyInstanceUid();
    if (!studyInstanceUid) {
      uiNotificationService.show({
        title: 'Rapport IA',
        message: "Aucune étude active.",
        type: 'warning',
        duration: 3000,
      });
      return;
    }
    const token = window.localStorage.getItem('teleoph.token')
      || window.sessionStorage.getItem('teleoph.token');
    try {
      const response = await fetch('/api/exams/regenerate-report/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ study_instance_uid: studyInstanceUid }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      uiNotificationService.show({
        title: 'Rapport IA',
        message: 'Régénération du rapport lancée. Le texte se mettra à jour automatiquement.',
        type: 'success',
        duration: 5000,
      });
      return data;
    } catch (err) {
      console.error('[AiReport] regeneration failed:', err);
      uiNotificationService.show({
        title: 'Rapport IA',
        message: err?.message || 'Échec du lancement de la régénération.',
        type: 'error',
        duration: 6000,
      });
    }
  }

  async function saveSegmentationCorrections({ eye } = {}) {
    await loadCornerstone();
    const summary = summarizeActiveSegmentation();
    const studyInstanceUid = currentStudyInstanceUid();
    if (!summary || !studyInstanceUid) {
      uiNotificationService.show({
        title: 'Corrections',
        message: 'Aucune correction sauvegardable trouvée.',
        type: 'warning',
        duration: 2500,
      });
      return;
    }

    const token = window.localStorage.getItem('teleoph.token')
      || window.sessionStorage.getItem('teleoph.token');
    const headers = {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
    const usedModes = Array.from(usedModesThisSession);
    const correctionType = usedModes.length > 1
      ? 'mixed'
      : usedModes[0] === 'pencil'
        ? 'pencil'
        : usedModes[0] === 'wand'
          ? 'wand'
          : 'eraser';

    const response = await fetch('/api/exams/segmentation-corrections/', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        study_instance_uid: studyInstanceUid,
        correction_type: correctionType,
        eye,
        ...summary,
      }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || 'Correction save failed');
    }
    const data = await response.json().catch(() => ({}));
    usedModesThisSession.clear();
    uiNotificationService.show({
      title: 'Corrections',
      message: 'Segmentation corrigée sauvegardée.',
      type: 'success',
      duration: 2500,
    });
    return data;
  }

  const actions = {
    setFoveaMarkers: ({ markers = [] } = {}) => {
      foveaMarkers = markers.filter(marker =>
        marker && marker.sop_instance_uid &&
        Number.isFinite(marker.x_px) && Number.isFinite(marker.y_px)
      );
      if (foveaVisible) renderFoveaOverlays();
    },
    toggleFoveaMarker: () => {
      if (!foveaMarkers.length) {
        uiNotificationService.show({
          title: 'Fovéa',
          message: "Aucune localisation de fovéa n'est disponible pour cette étude.",
          type: 'info',
          duration: 3500,
        });
        return;
      }
      foveaVisible = !foveaVisible;
      if (foveaVisible) renderFoveaOverlays();
      else removeFoveaOverlays();
    },
    toggleClaheFilter: () => {
      const { viewportGridService, cornerstoneViewportService } = servicesManager.services;
      const { activeViewportId } = viewportGridService.getState();
      const viewport = cornerstoneViewportService.getCornerstoneViewport(activeViewportId);
      const element = viewport?.element;
      if (!element) return;

      const existing = claheOverlays.get(activeViewportId);
      if (existing) {
        existing.dispose();
        claheOverlays.delete(activeViewportId);
        return;
      }

      const source = findViewportCanvas(element);
      if (!source) return;

      const overlay = document.createElement('canvas');
      overlay.width = source.width;
      overlay.height = source.height;
      overlay.setAttribute('aria-label', 'Filtre CLAHE actif');
      overlay.setAttribute('data-teleoph-overlay', 'clahe');
      Object.assign(overlay.style, {
        position: 'absolute',
        inset: '0',
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: '4',
      });

      // The overlay used to be a one-shot snapshot pasted on top, so anything
      // painted afterwards by Crayon, Gomme or Baguette stayed hidden beneath
      // it. Recompute it from the live Cornerstone canvas on every render,
      // throttled, so corrections remain visible while CLAHE is on.
      let lastRun = 0;
      let trailing = null;
      const CLAHE_MIN_INTERVAL = 80;

      const paint = () => {
        const current = findViewportCanvas(element);
        if (!current) return;
        if (overlay.width !== current.width || overlay.height !== current.height) {
          overlay.width = current.width;
          overlay.height = current.height;
        }
        try {
          applyClahe(current, overlay);
        } catch (err) {
          console.warn('[CLAHE] refresh failed', err);
        }
        lastRun = Date.now();
      };

      const render = () => {
        const elapsed = Date.now() - lastRun;
        if (elapsed >= CLAHE_MIN_INTERVAL) {
          paint();
          return;
        }
        if (trailing) return;
        trailing = setTimeout(() => {
          trailing = null;
          paint();
        }, CLAHE_MIN_INTERVAL - elapsed);
      };

      element.addEventListener('CORNERSTONE_IMAGE_RENDERED', render);
      element.addEventListener('CORNERSTONE_NEW_IMAGE', render);
      const resizeObserver = typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(render)
        : null;
      resizeObserver?.observe(element);

      overlay.dispose = () => {
        element.removeEventListener('CORNERSTONE_IMAGE_RENDERED', render);
        element.removeEventListener('CORNERSTONE_NEW_IMAGE', render);
        resizeObserver?.disconnect();
        if (trailing) clearTimeout(trailing);
        overlay.remove();
      };

      paint();
      element.appendChild(overlay);
      claheOverlays.set(activeViewportId, overlay);
    },
    toggleSegmentationEraser,
    toggleSegmentationPencil,
    toggleSegmentationWand,
    cycleActivePencilSegment,
    undoSegmentationEdit,
    redoSegmentationEdit,
    resetSegmentationToOriginal,
    saveSegmentationCorrections,
    regenerateAiReport,
    notifyStudyOpened: ({ studyInstanceUid }) => {
      sendToParent('study-opened', { studyInstanceUid });
    },
    notifyStudyClosed: () => {
      sendToParent('study-closed');
    },
    notifySeriesSelected: ({ seriesInstanceUid }) => {
      sendToParent('series-selected', { seriesInstanceUid });
    },
    notifyMeasurementAdded: ({ measurementId, toolType }) => {
      sendToParent('measurement-added', { measurementId, toolType });
    },
    notifyViewportChanged: ({ viewportId }) => {
      sendToParent('viewport-changed', { viewportId });
    },
  };

  const definitions = {
    setFoveaMarkers: { commandFn: actions.setFoveaMarkers },
    toggleFoveaMarker: { commandFn: actions.toggleFoveaMarker },
    toggleClaheFilter: {
      commandFn: actions.toggleClaheFilter,
    },
    toggleSegmentationEraser: {
      commandFn: actions.toggleSegmentationEraser,
    },
    toggleSegmentationPencil: {
      commandFn: actions.toggleSegmentationPencil,
    },
    toggleSegmentationWand: {
      commandFn: actions.toggleSegmentationWand,
    },
    cycleActivePencilSegment: {
      commandFn: actions.cycleActivePencilSegment,
    },
    undoSegmentationEdit: {
      commandFn: actions.undoSegmentationEdit,
    },
    redoSegmentationEdit: {
      commandFn: actions.redoSegmentationEdit,
    },
    resetSegmentationToOriginal: {
      commandFn: actions.resetSegmentationToOriginal,
    },
    saveSegmentationCorrections: {
      commandFn: actions.saveSegmentationCorrections,
    },
    regenerateAiReport: {
      commandFn: actions.regenerateAiReport,
    },
  };

  return {
    actions,
    definitions,
    defaultContext: 'CORNERSTONE',
  };
}
