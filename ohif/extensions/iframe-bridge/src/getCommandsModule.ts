export default function getCommandsModule({ servicesManager }) {
  const { uiNotificationService } = servicesManager.services;

  const claheOverlays = new Map();
  const foveaOverlays = new Map();
  let foveaMarkers = [];
  let foveaVisible = false;

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
  };

  return {
    actions,
    definitions,
    defaultContext: 'IFRAME_BRIDGE',
  };
}
