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
  let eraserBrushSize = 24;

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
    if (!segmentationId) return undefined;
    const { segmentationService } = servicesManager.services;
    return segmentationService?.getLabelmapVolume?.(segmentationId);
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
      // eslint-disable-next-line no-console
      console.log('[SegmentationEdit] getSegmentations() raw:', raw);
      const entries = Array.isArray(raw) ? raw : Object.entries(raw || {});
      for (const entry of entries) {
        const [key, value] = Array.isArray(entry) ? entry : [null, entry];
        const candidateId = value?.segmentationId || value?.id || key;
        if (!candidateId) continue;
        try {
          segmentationService.setActiveSegmentation(viewportId, candidateId);
        } catch (setErr) {
          console.warn('[SegmentationEdit] setActiveSegmentation failed for', candidateId, setErr);
          continue;
        }
        const confirmed = resolveActiveSegmentationId(viewportId);
        if (confirmed) return confirmed;
        // setActiveSegmentation didn't throw but didn't take either -- try the
        // candidate id directly against getLabelmapVolume as a last resort.
        if (getActiveLabelmapVolume(candidateId)) return candidateId;
      }
      console.warn('[SegmentationEdit] No usable segmentation id found among', entries.length, 'entries');
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

  function paintAtCanvasPoint(viewport, segmentationId, canvasX, canvasY, brushSize, writeValue, strokeDiff) {
    const volumeLoadObject = getActiveLabelmapVolume(segmentationId);
    const scalarData = volumeLoadObject?.voxelManager?.getCompleteScalarDataArray?.();
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
      volumeLoadObject.voxelManager?.setCompleteScalarDataArray?.(scalarData);
      notifySegmentationModified(segmentationId);
    }
    return changed;
  }

  function ensureOriginalSnapshot(segmentationId) {
    if (!segmentationId || originalSnapshots.has(segmentationId)) return;
    const volumeLoadObject = getActiveLabelmapVolume(segmentationId);
    const scalarData = volumeLoadObject?.voxelManager?.getCompleteScalarDataArray?.();
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

  function undoSegmentationEdit(segmentationId) {
    if (!segmentationId) {
      const { activeViewportId } = getActiveViewport();
      segmentationId = resolveActiveSegmentationId(activeViewportId);
    }
    const stack = segmentationId && undoStacks.get(segmentationId);
    if (!stack || !stack.length) {
      uiNotificationService.show({ title: 'Annuler', message: 'Rien à annuler.', type: 'info', duration: 1500 });
      return;
    }
    const strokeDiff = stack.pop();
    const volumeLoadObject = getActiveLabelmapVolume(segmentationId);
    const scalarData = volumeLoadObject?.voxelManager?.getCompleteScalarDataArray?.();
    if (!scalarData) return;
    const redoDiff = new Map();
    strokeDiff.forEach((oldValue, offset) => {
      redoDiff.set(offset, scalarData[offset]);
      scalarData[offset] = oldValue;
    });
    volumeLoadObject.voxelManager?.setCompleteScalarDataArray?.(scalarData);
    notifySegmentationModified(segmentationId);
    const redoStack = redoStacks.get(segmentationId) || [];
    redoStack.push(redoDiff);
    redoStacks.set(segmentationId, redoStack);
  }

  function redoSegmentationEdit(segmentationId) {
    if (!segmentationId) {
      const { activeViewportId } = getActiveViewport();
      segmentationId = resolveActiveSegmentationId(activeViewportId);
    }
    const stack = segmentationId && redoStacks.get(segmentationId);
    if (!stack || !stack.length) {
      uiNotificationService.show({ title: 'Rétablir', message: 'Rien à rétablir.', type: 'info', duration: 1500 });
      return;
    }
    const redoDiff = stack.pop();
    const volumeLoadObject = getActiveLabelmapVolume(segmentationId);
    const scalarData = volumeLoadObject?.voxelManager?.getCompleteScalarDataArray?.();
    if (!scalarData) return;
    const undoDiff = new Map();
    redoDiff.forEach((newValue, offset) => {
      undoDiff.set(offset, scalarData[offset]);
      scalarData[offset] = newValue;
    });
    volumeLoadObject.voxelManager?.setCompleteScalarDataArray?.(scalarData);
    notifySegmentationModified(segmentationId);
    const undoStack = undoStacks.get(segmentationId) || [];
    undoStack.push(undoDiff);
    undoStacks.set(segmentationId, undoStack);
  }

  function resetSegmentationToOriginal(segmentationId) {
    if (!segmentationId) {
      const { activeViewportId } = getActiveViewport();
      segmentationId = resolveActiveSegmentationId(activeViewportId);
    }
    const original = segmentationId && originalSnapshots.get(segmentationId);
    const volumeLoadObject = segmentationId && getActiveLabelmapVolume(segmentationId);
    const scalarData = volumeLoadObject?.voxelManager?.getCompleteScalarDataArray?.();
    if (!original || !scalarData) {
      uiNotificationService.show({
        title: 'Réinitialiser',
        message: 'Aucune modification à annuler pour cette segmentation.',
        type: 'info',
        duration: 2000,
      });
      return;
    }
    scalarData.set(original);
    volumeLoadObject.voxelManager?.setCompleteScalarDataArray?.(scalarData);
    notifySegmentationModified(segmentationId);
    undoStacks.set(segmentationId, []);
    redoStacks.set(segmentationId, []);
    uiNotificationService.show({
      title: 'Réinitialiser',
      message: 'Masque restauré à la version IA initiale.',
      type: 'success',
      duration: 2000,
    });
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

  function summarizeActiveSegmentation() {
    const { activeViewportId } = getActiveViewport();
    const segmentationId = ensureActiveSegmentationId(activeViewportId);
    if (!segmentationId) return null;
    const volumeLoadObject = getActiveLabelmapVolume(segmentationId);
    const scalarData = volumeLoadObject?.voxelManager?.getCompleteScalarDataArray?.();
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

  function toggleSegmentationEdit(mode) {
    const modeLabel = mode === 'pencil' ? 'Crayon' : 'Gomme';
    try {
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
      if (!segmentationId || !getActiveLabelmapVolume(segmentationId)) {
        uiNotificationService.show({
          title: modeLabel,
          message: 'Aucune segmentation éditable trouvée pour cette étude.',
          type: 'warning',
          duration: 3500,
        });
        return;
      }

      ensureOriginalSnapshot(segmentationId);

      let drawing = false;
      let strokeDiff = null;
      const previousCursor = element.style.cursor;
      element.style.cursor = 'none';
      const cursor = showBrushCursor(element, activeViewportId);

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
          if (paintAtCanvasPoint(viewport, segmentationId, x, y, eraserBrushSize, writeValue, strokeDiff)) {
            usedModesThisSession.add(mode);
          }
        } catch (err) {
          reportSegmentationError(modeLabel, 'paint', err);
        }
      };
      const updateCursor = event => {
        try {
          const [x, y] = pointFromEvent(event);
          const radius = Math.max(2, eraserBrushSize / 2);
          cursor.circle.setAttribute('cx', String(x));
          cursor.circle.setAttribute('cy', String(y));
          cursor.circle.setAttribute('r', String(radius));
          cursor.circle.setAttribute('stroke', mode === 'pencil' ? '#22c55e' : '#ffffff');
        } catch (err) {
          reportSegmentationError(modeLabel, 'cursor', err);
        }
      };
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
        eraserBrushSize = Math.max(4, Math.min(96, eraserBrushSize + (event.deltaY > 0 ? -4 : 4)));
        uiNotificationService.show({
          title: modeLabel,
          message: `Taille: ${eraserBrushSize}px`,
          type: 'info',
          duration: 900,
        });
        event.preventDefault();
      };

      element.addEventListener('pointerdown', pointerDown);
      element.addEventListener('pointermove', pointerMove);
      element.addEventListener('pointerup', pointerUp);
      element.addEventListener('pointerleave', pointerUp);
      element.addEventListener('wheel', wheel, { passive: false });

      editSessions.set(activeViewportId, {
        mode,
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
            ? 'Crayon actif. Alt + molette : taille. Bouton "Segment" : choisir la classe à dessiner.'
            : 'Gomme active. Maintenez Alt + molette pour changer la taille.',
        type: 'success',
        duration: 3000,
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
    const correctionType = usedModesThisSession.size === 2
      ? 'mixed'
      : usedModesThisSession.has('pencil')
        ? 'pencil'
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
