export default function getCommandsModule({ servicesManager }) {
  const { uiNotificationService } = servicesManager.services;

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

  const definitions = {};

  return {
    actions,
    definitions,
    defaultContext: 'IFRAME_BRIDGE',
  };
}
