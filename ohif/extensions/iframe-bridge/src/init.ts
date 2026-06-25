export default function preRegistration({
  servicesManager,
  commandsManager,
}) {
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
      // cross-origin errors are silently ignored
    }
  }

  window.addEventListener('message', async event => {
    const { type, ...data } = event.data || {};
    if (!type || !type.startsWith('ohif-bridge:')) return;

    const command = type.replace('ohif-bridge:', '');

    switch (command) {
      case 'open-study': {
        const { studyInstanceUids } = data;
        if (!studyInstanceUids) {
          sendToParent('error', { message: 'studyInstanceUids required' });
          return;
        }
        try {
          await commandsManager.runCommand('openStudy', {
            studyInstanceUids: Array.isArray(studyInstanceUids)
              ? studyInstanceUids
              : [studyInstanceUids],
          });
        } catch (e) {
          sendToParent('error', {
            message: `Failed to open study: ${e.message}`,
          });
        }
        break;
      }
      case 'set-tool': {
        const { toolName } = data;
        if (toolName) {
          commandsManager.runCommand('setToolActive', {
            toolName,
          });
        }
        break;
      }
      case 'get-status': {
        sendToParent('status', { status: 'ready' });
        break;
      }
      case 'jump-to-measurement': {
        const { measurementId } = data;
        if (measurementId) {
          commandsManager.runCommand('jumpToMeasurement', {
            uid: measurementId,
          });
        }
        break;
      }
      case 'set-segmentation-visibility': {
        const { segmentationId, visible } = data;
        if (segmentationId) {
          commandsManager.runCommand('setSegmentationVisibility', {
            segmentationId,
            visible,
          });
        }
        break;
      }
      default:
        sendToParent('error', { message: `Unknown command: ${command}` });
    }
  });

  sendToParent('ready', {
    version: '3.0.0',
  });
}
