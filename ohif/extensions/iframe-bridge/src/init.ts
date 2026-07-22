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

  async function loadStandaloneFoveaMarkers() {
    const query = new URLSearchParams(window.location.search);
    const studyInstanceUid = query.get('StudyInstanceUIDs') || query.get('studyInstanceUids');
    if (!studyInstanceUid) return;

    const token = window.localStorage.getItem('teleoph.token')
      || window.sessionStorage.getItem('teleoph.token');
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    try {
      const response = await fetch(
        `/api/exams/analysis/?study_instance_uid=${encodeURIComponent(studyInstanceUid)}`,
        { headers }
      );
      if (!response.ok) return;
      const result = await response.json();
      commandsManager.runCommand('setFoveaMarkers', {
        markers: Array.isArray(result.fovea_markers) ? result.fovea_markers : [],
      });
    } catch (_) {
      // The toolbar remains usable; it will report that no localization exists.
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
      case 'set-fovea-markers': {
        commandsManager.runCommand('setFoveaMarkers', {
          markers: Array.isArray(data.markers) ? data.markers : [],
        });
        break;
      }
      default:
        sendToParent('error', { message: `Unknown command: ${command}` });
    }
  });

  sendToParent('ready', {
    version: '3.0.0',
  });

  // Also support OHIF opened directly, without the worklist iframe bridge.
  // Defer until command modules have completed registration.
  window.setTimeout(loadStandaloneFoveaMarkers, 0);
}
