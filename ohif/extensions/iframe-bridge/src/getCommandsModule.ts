export default function getCommandsModule({ servicesManager }) {
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
  const BRUSH_MIN = 2;
  const BRUSH_MAX = 120;
  const BRUSH_STEP = 2;
  const BRUSH_STORAGE_KEY = 'teleophtalmo.segmentation.brushSizes';
  const brushPanels = new Map(); // viewportId -> { panel, refresh }
  const brushSizes = loadBrushSizes();
  // "Baguette" (magic wand): one click on a lesion, seeded region growing on the
  // fundus image fills the whole lesion. Two doctor-facing settings, persisted.
  const WAND_STORAGE_KEY = 'teleophtalmo.segmentation.wand';
  const WAND_LIMITS = { tolerance: [5, 80], radius: [10, 150] };
  const WAND_DEFAULTS = { tolerance: 25, radius: 40 };
  const WAND_MAX_ERASE_COMPONENT = 250000; // px, guards Alt+click on a vessel tree
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
  function ensureActiveSegmentationId(viewportId) {
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
      console.warn(
        '[SegmentationEdit] No usable segmentation id found. length=', length, 'tried=', tried, 'raw=', raw
      );
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

    const radius = Math.max(2, brushSize / 2);
    const radiusSquared = radius * radius;
    let changed = 0;

    for (let dy = -radius; dy <= radius; dy++) {
      for (let dx = -radius; dx <= radius; dx++) {
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

  function summarizeActiveSegmentation() {
    const { activeViewportId, viewport } = getActiveViewport();
    const segmentationId = ensureActiveSegmentationId(activeViewportId);
    if (!segmentationId) return null;
    const accessor = getLabelmapAccessor(segmentationId, activeViewportId, viewport);
    const scalarData = accessor?.getScalarData?.();
    if (!scalarData) return null;

    const counts = {};
    for (let i = 0; i < scalarData.length; i++) {
      const value = scalarData[i];
      if (!value) continue;
      counts[value] = (counts[value] || 0) + 1;
    }
    return {
      segmentation_id: segmentationId,
      pixel_counts_by_segment: counts,
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

      const segmentationId = ensureActiveSegmentationId(activeViewportId);
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
            : 'Aucune segmentation éditable trouvée pour cette étude.',
          type: 'warning',
          duration: 3500,
        });
        return;
      }

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
    if (image.color || pixels.length >= total * 3) {
      const stride = pixels.length >= total * 4 ? 4 : 3;
      for (let p = 0; p < total; p++) raw[p] = pixels[p * stride + 1];
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
    return { data: boxBlur3x3(raw, width, height), width, height, imageId };
  }

  function boxBlur3x3(src, width, height) {
    const out = new Uint8Array(src.length);
    for (let j = 0; j < height; j++) {
      const j0 = Math.max(0, j - 1);
      const j1 = Math.min(height - 1, j + 1);
      for (let i = 0; i < width; i++) {
        const i0 = Math.max(0, i - 1);
        const i1 = Math.min(width - 1, i + 1);
        let sum = 0;
        let count = 0;
        for (let jj = j0; jj <= j1; jj++) {
          const row = jj * width;
          for (let ii = i0; ii <= i1; ii++) {
            sum += src[row + ii];
            count++;
          }
        }
        out[j * width + i] = Math.round(sum / count);
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
  function medianOnRing(green, width, height, ci, cj, r) {
    const samples = [];
    const steps = 72;
    for (let s = 0; s < steps; s++) {
      const angle = (2 * Math.PI * s) / steps;
      const i = Math.round(ci + r * Math.cos(angle));
      const j = Math.round(cj + r * Math.sin(angle));
      if (i < 0 || j < 0 || i >= width || j >= height) continue;
      const v = green[j * width + i];
      if (v >= 8) samples.push(v);
    }
    if (samples.length < 8) return null;
    samples.sort((a, b) => a - b);
    return samples[Math.floor(samples.length / 2)];
  }

  // Seeded region growing (BFS, 8-connectivity) inside a (2r+1)^2 box.
  // A pixel joins the region when it stays within `tolerance` of the running
  // mean of the region AND on the seed's side of the background (dark lesion
  // stays dark, bright lesion stays bright).
  function growRegion(green, width, height, seedI, seedJ, tolerance, radius, polarity, background, margin) {
    const size = 2 * radius + 1;
    const x0 = seedI - radius;
    const y0 = seedJ - radius;
    const mask = new Uint8Array(size * size);
    const visited = new Uint8Array(size * size);
    const qi = new Int32Array(size * size);
    const qj = new Int32Array(size * size);
    const maxArea = Math.PI * radius * radius;
    const halfMargin = margin / 2;
    const inside = polarity === 'dark'
      ? v => v < background - halfMargin
      : v => v > background + halfMargin;

    let head = 0;
    let tail = 0;
    qi[tail] = seedI;
    qj[tail] = seedJ;
    tail++;
    visited[(seedJ - y0) * size + (seedI - x0)] = 1;

    let sum = 0;
    let count = 0;
    let touchedBorder = false;
    while (head < tail && count < maxArea) {
      const i = qi[head];
      const j = qj[head];
      head++;
      const v = green[j * width + i];
      const mean = count ? sum / count : v;
      if (Math.abs(v - mean) > tolerance || !inside(v)) continue;
      const bi = i - x0;
      const bj = j - y0;
      mask[bj * size + bi] = 1;
      sum += v;
      count++;
      if (bi === 0 || bj === 0 || bi === size - 1 || bj === size - 1) touchedBorder = true;
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
          qi[tail] = ni;
          qj[tail] = nj;
          tail++;
        }
      }
    }
    return { mask, size, x0, y0, count, leak: touchedBorder || count >= 0.9 * maxArea };
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
  function keepSeedComponent(mask, size, seedBi, seedBj) {
    const out = new Uint8Array(mask.length);
    if (!mask[seedBj * size + seedBi]) return { mask: out, count: 0 };
    const qi = new Int32Array(mask.length);
    const qj = new Int32Array(mask.length);
    let head = 0;
    let tail = 0;
    let count = 0;
    out[seedBj * size + seedBi] = 1;
    qi[tail] = seedBi;
    qj[tail] = seedBj;
    tail++;
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

  // Full pipeline for one click / hover position. Returns either { error } or
  // { region, polarity, seedI, seedJ, offset }.
  function computeWandRegion(fundus, viewport, canvasX, canvasY) {
    const offset = scalarOffsetFromCanvas(viewport, canvasX, canvasY);
    if (offset == null) return { error: 'outside' };
    const { data: green, width, height } = fundus;
    const seedI = offset % width;
    const seedJ = Math.floor(offset / width);
    const tolerance = getWandSetting('tolerance');
    const radius = getWandSetting('radius');

    const seedValue = mean3x3(green, width, height, seedI, seedJ);
    if (seedValue < 8) return { error: 'outside' }; // black mask around the retina
    const background = medianOnRing(green, width, height, seedI, seedJ, radius);
    if (background == null) return { error: 'outside' };
    const margin = Math.abs(seedValue - background);
    if (margin < 4) return { error: 'no-lesion' };
    const polarity = seedValue < background ? 'dark' : 'bright';

    const grown = growRegion(green, width, height, seedI, seedJ, tolerance, radius, polarity, background, margin);
    if (grown.count < 3) return { error: 'no-lesion' };
    const closed = closeMask3x3(grown.mask, grown.size);
    const filled = fillHoles(closed, grown.size);
    const kept = keepSeedComponent(filled, grown.size, radius, radius);
    if (kept.count < 3) return { error: 'no-lesion' };
    return {
      region: { mask: kept.mask, size: grown.size, x0: grown.x0, y0: grown.y0, count: kept.count, leak: grown.leak },
      polarity,
      seedI,
      seedJ,
      offset,
    };
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

  function drawWandPreview(record, viewport, viewportId, segmentationId, result, pointer) {
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
    const radius = buildSettingRow({ label: 'Rayon max', key: 'radius', unit: ' px', step: 2, accent });
    const hint = document.createElement('div');
    hint.textContent = 'Clic : dessiner la lésion · Alt + clic : supprimer';
    Object.assign(hint.style, { color: '#94a3b8', fontSize: '11px' });

    [
      'pointerdown', 'pointermove', 'pointerup', 'pointerleave', 'pointercancel',
      'mousedown', 'mousemove', 'mouseup', 'click', 'dblclick', 'contextmenu',
      'wheel', 'touchstart', 'touchmove', 'touchend', 'keydown',
    ].forEach(type => panel.addEventListener(type, event => event.stopPropagation()));

    panel.appendChild(title);
    panel.appendChild(tolerance.row);
    panel.appendChild(radius.row);
    panel.appendChild(hint);
    element.appendChild(panel);
    const record = {
      panel,
      refresh: () => {
        tolerance.refresh();
        radius.refresh();
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

      const segmentationId = ensureActiveSegmentationId(activeViewportId);
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
            : 'Aucune segmentation éditable trouvée pour cette étude.',
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
        const result = computeWandRegion(fundus, viewport, x, y);
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

      const pointerMove = event => {
        lastPointer = pointFromEvent(event);
        schedulePreview();
      };
      const pointerLeave = () => {
        lastPointer = null;
        clearWandPreview(preview);
      };
      const pointerDown = event => {
        try {
          event.preventDefault();
          const [x, y] = pointFromEvent(event);
          lastPointer = [x, y];

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

          const result = computeWandRegion(fundus, viewport, x, y);
          if (result.error) {
            uiNotificationService.show({ title: modeLabel, message: messageForError(result.error), type: 'info', duration: 2500 });
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
          } else {
            uiNotificationService.show({
              title: modeLabel,
              message: changed ? `Lésion dessinée (${result.region.count} px).` : 'Cette lésion est déjà segmentée dans cette classe.',
              type: 'info',
              duration: 1400,
            });
          }
          schedulePreview();
        } catch (err) {
          reportSegmentationError(modeLabel, 'click', err);
        }
      };
      const wheel = event => {
        if (event.ctrlKey) {
          setWandSetting('tolerance', getWandSetting('tolerance') + (event.deltaY > 0 ? -1 : 1));
          event.preventDefault();
        } else if (event.altKey) {
          setWandSetting('radius', getWandSetting('radius') + (event.deltaY > 0 ? -2 : 2));
          event.preventDefault();
        }
      };

      element.addEventListener('pointerdown', pointerDown);
      element.addEventListener('pointermove', pointerMove);
      element.addEventListener('pointerleave', pointerLeave);
      element.addEventListener('wheel', wheel, { passive: false });

      editSessions.set(activeViewportId, {
        mode: 'wand',
        onSettingsChanged: schedulePreview,
        cleanup: () => {
          element.style.cursor = previousCursor;
          element.removeEventListener('pointerdown', pointerDown);
          element.removeEventListener('pointermove', pointerMove);
          element.removeEventListener('pointerleave', pointerLeave);
          element.removeEventListener('wheel', wheel);
        },
      });

      uiNotificationService.show({
        title: modeLabel,
        message: `Baguette active (tolérance ${getWandSetting('tolerance')}, rayon ${getWandSetting('radius')} px). Cliquez sur une lésion. Alt + clic : supprimer. Ctrl + molette : tolérance.`,
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
        existing.remove();
        claheOverlays.delete(activeViewportId);
        return;
      }

      const source = Array.from(element.querySelectorAll('canvas')).find(
        canvas => canvas.width > 0 && canvas.height > 0
      );
      if (!source) return;

      const overlay = document.createElement('canvas');
      overlay.width = source.width;
      overlay.height = source.height;
      overlay.setAttribute('aria-label', 'Filtre CLAHE actif');
      Object.assign(overlay.style, {
        position: 'absolute',
        inset: '0',
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: '4',
      });
      applyClahe(source, overlay);
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
  };

  return {
    actions,
    definitions,
    defaultContext: 'CORNERSTONE',
  };
}
