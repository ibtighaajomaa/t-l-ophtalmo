export default function getCommandsModule({ servicesManager }) {
  const { uiNotificationService } = servicesManager.services;

  const claheOverlays = new Map();
  const foveaOverlays = new Map();
  const eraserSessions = new Map();
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

  function getActiveLabelmapVolume(segmentationId = '1') {
    const { segmentationService } = servicesManager.services;
    return segmentationService?.getLabelmapVolume?.(segmentationId);
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

  function eraseAtCanvasPoint(viewport, canvasX, canvasY, brushSize = eraserBrushSize) {
    const volumeLoadObject = getActiveLabelmapVolume('1');
    const scalarData = volumeLoadObject?.voxelManager?.getCompleteScalarDataArray?.();
    if (!scalarData) return 0;

    const radius = Math.max(2, brushSize / 2);
    const radiusSquared = radius * radius;
    let changed = 0;

    for (let dy = -radius; dy <= radius; dy++) {
      for (let dx = -radius; dx <= radius; dx++) {
        if (dx * dx + dy * dy > radiusSquared) continue;
        const offset = scalarOffsetFromCanvas(viewport, canvasX + dx, canvasY + dy);
        if (offset == null || !scalarData[offset]) continue;
        scalarData[offset] = 0;
        changed++;
      }
    }

    if (changed) {
      volumeLoadObject.voxelManager?.setCompleteScalarDataArray?.(scalarData);
      notifySegmentationModified('1');
    }
    return changed;
  }

  function summarizeActiveSegmentation() {
    const volumeLoadObject = getActiveLabelmapVolume('1');
    const scalarData = volumeLoadObject?.voxelManager?.getCompleteScalarDataArray?.();
    if (!scalarData) return null;

    const counts = {};
    for (let i = 0; i < scalarData.length; i++) {
      const value = scalarData[i];
      if (!value) continue;
      counts[value] = (counts[value] || 0) + 1;
    }
    return {
      segmentation_id: '1',
      pixel_counts_by_segment: counts,
      total_labeled_pixels: Object.values(counts).reduce((sum, value) => sum + value, 0),
    };
  }

  function toggleSegmentationEraser() {
    const { activeViewportId, viewport } = getActiveViewport();
    const element = viewport?.element;
    if (!activeViewportId || !element) return;

    const existing = eraserSessions.get(activeViewportId);
    if (existing) {
      existing.cleanup();
      eraserSessions.delete(activeViewportId);
      uiNotificationService.show({
        title: 'Gomme segmentation',
        message: 'Gomme désactivée.',
        type: 'info',
        duration: 1600,
      });
      return;
    }

    if (!getActiveLabelmapVolume('1')) {
      uiNotificationService.show({
        title: 'Gomme segmentation',
        message: 'Aucune segmentation éditable active.',
        type: 'warning',
        duration: 3000,
      });
      return;
    }

    let drawing = false;
    const previousCursor = element.style.cursor;
    element.style.cursor = 'crosshair';

    const pointFromEvent = event => {
      const rect = element.getBoundingClientRect();
      return [event.clientX - rect.left, event.clientY - rect.top];
    };
    const erase = event => {
      const [x, y] = pointFromEvent(event);
      eraseAtCanvasPoint(viewport, x, y);
    };
    const pointerDown = event => {
      drawing = true;
      element.setPointerCapture?.(event.pointerId);
      erase(event);
      event.preventDefault();
    };
    const pointerMove = event => {
      if (!drawing) return;
      erase(event);
      event.preventDefault();
    };
    const pointerUp = event => {
      drawing = false;
      element.releasePointerCapture?.(event.pointerId);
      event.preventDefault();
    };
    const wheel = event => {
      if (!event.altKey) return;
      eraserBrushSize = Math.max(4, Math.min(96, eraserBrushSize + (event.deltaY > 0 ? -4 : 4)));
      uiNotificationService.show({
        title: 'Gomme segmentation',
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

    eraserSessions.set(activeViewportId, {
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
      title: 'Gomme segmentation',
      message: 'Gomme active. Maintenez Alt + molette pour changer la taille.',
      type: 'success',
      duration: 3000,
    });
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
    const response = await fetch('/api/exams/segmentation-corrections/', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        study_instance_uid: studyInstanceUid,
        correction_type: 'eraser',
        eye,
        ...summary,
      }),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || 'Correction save failed');
    }
    const data = await response.json().catch(() => ({}));
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
    saveSegmentationCorrections: {
      commandFn: actions.saveSegmentationCorrections,
    },
  };

  return {
    actions,
    definitions,
    defaultContext: 'IFRAME_BRIDGE',
  };
}
