type BridgeEventType =
  | 'ready'
  | 'status'
  | 'study-opened'
  | 'study-closed'
  | 'series-selected'
  | 'measurement-added'
  | 'viewport-changed'
  | 'error';

interface BridgeMessage {
  type: `ohif-bridge:${BridgeEventType}`;
  [key: string]: unknown;
}

interface BridgeOptions {
  iframeRef: React.RefObject<HTMLIFrameElement | null>;
  onReady?: () => void;
  onStudyOpened?: (studyInstanceUid: string) => void;
  onStudyClosed?: () => void;
  onSeriesSelected?: (seriesInstanceUid: string) => void;
  onError?: (message: string) => void;
}

export class OhifBridge {
  private iframeRef: BridgeOptions['iframeRef'];
  private handlers: Map<BridgeEventType, Set<(...args: unknown[]) => void>> = new Map();
  private ready = false;

  constructor(private opts: BridgeOptions) {
    this.iframeRef = opts.iframeRef;
    if (opts.onReady) this.on('ready', opts.onReady);
    if (opts.onStudyOpened) this.on('study-opened', opts.onStudyOpened);
    if (opts.onStudyClosed) this.on('study-closed', opts.onStudyClosed);
    if (opts.onSeriesSelected) this.on('series-selected', opts.onSeriesSelected);
    if (opts.onError) this.on('error', opts.onError);
    this.listen();
  }

  private listen() {
    window.addEventListener('message', (event: MessageEvent<BridgeMessage>) => {
      const { type, ...payload } = event.data || {};
      if (!type || !type.startsWith('ohif-bridge:')) return;

      const eventType = type.replace('ohif-bridge:', '') as BridgeEventType;

      if (eventType === 'ready') {
        this.ready = true;
      }

      const handlers = this.handlers.get(eventType);
      if (handlers) {
        handlers.forEach(fn => fn(payload));
      }
    });
  }

  on(event: BridgeEventType, fn: (...args: unknown[]) => void) {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(fn);
  }

  off(event: BridgeEventType, fn: (...args: unknown[]) => void) {
    this.handlers.get(event)?.delete(fn);
  }

  private postMessage(type: string, payload: Record<string, unknown> = {}) {
    const iframe = this.iframeRef.current;
    if (!iframe?.contentWindow) {
      console.warn('[OhifBridge] iframe not available');
      return;
    }
    iframe.contentWindow.postMessage(
      { type: `ohif-bridge:${type}`, ...payload },
      '*',
    );
  }

  openStudy(studyInstanceUids: string | string[]) {
    this.postMessage('open-study', {
      studyInstanceUids: Array.isArray(studyInstanceUids)
        ? studyInstanceUids
        : [studyInstanceUids],
    });
  }

  setTool(toolName: string) {
    this.postMessage('set-tool', { toolName });
  }

  getStatus() {
    this.postMessage('get-status');
  }

  setSegmentationVisibility(segmentationId: string, visible: boolean) {
    this.postMessage('set-segmentation-visibility', {
      segmentationId,
      visible,
    });
  }

  isReady() {
    return this.ready;
  }

  destroy() {
    this.handlers.clear();
    this.ready = false;
  }
}

export function createOhifBridge(opts: BridgeOptions) {
  return new OhifBridge(opts);
}
