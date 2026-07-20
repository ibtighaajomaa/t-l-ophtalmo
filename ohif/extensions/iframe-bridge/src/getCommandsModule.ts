export default function getCommandsModule({ servicesManager }) {
  const { uiNotificationService } = servicesManager.services;

  const claheOverlays = new Map();

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
