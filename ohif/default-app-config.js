window.config = {
  routerBasename: '/ohif',

  // =========================
  // 🧩 EXTENSIONS
  // =========================
  extensions: [
    '@ohif/extension-default',
    '@ohif/extension-cornerstone',
    '@ohif/extension-cornerstone-dicom-sr',
    '@ohif/extension-cornerstone-dicom-seg',
    '@ohif/extension-measurement-tracking',
    '@ohif/extension-monai-label',
    '@ohif/extension-iframe-bridge',
  ],

  modes: ['@ohif/mode-monai-label', '@ohif/mode-longitudinal', '@ohif/mode-segmentation'],

  customizationService: {
    // ❌ DO NOT use MONAI_Label here (OHIF ignores it)
    // ✔ MONAI is handled via extension + server config
  },

  showStudyList: true,

  maxNumberOfWebWorkers: 3,
  omitQuotationForMultipartRequest: true,
  showWarningMessageForCrossOrigin: true,
  showCPUFallbackMessage: true,
  showLoadingIndicator: true,
  strictZSpacingForVolumeViewport: true,

  maxNumRequests: {
    interaction: 100,
    thumbnail: 75,
    prefetch: 25,
  },

  // =========================
  // 🏥 DATA SOURCES (ORTHANC)
  // =========================
  dataSources: [
    {
      friendlyName: 'Orthanc local',
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'dicomweb',
      configuration: {
        name: 'orthanc',

        wadoUriRoot: '/orthanc-container/dicom-web',
        qidoRoot: '/orthanc-container/dicom-web',
        wadoRoot: '/orthanc-container/dicom-web',

        qidoSupportsIncludeField: false,
        supportsReject: false,

        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',

        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,

        staticWado: false,
        singlepart: 'bulkdata',

        acceptHeader: [
          'multipart/related; type=application/octet-stream; transfer-syntax=*',
        ],
      },
    },
  ],

  defaultDataSourceName: 'dicomweb',

  httpErrorHandler: error => {
    console.warn(error.status);
  },

  // =========================
  // ⌨️ HOTKEYS (UNCHANGED)
  // =========================
  hotkeys: [
    { commandName: 'incrementActiveViewport', label: 'Next Viewport', keys: ['right'] },
    { commandName: 'decrementActiveViewport', label: 'Previous Viewport', keys: ['left'] },
    { commandName: 'rotateViewportCW', label: 'Rotate Right', keys: ['r'] },
    { commandName: 'rotateViewportCCW', label: 'Rotate Left', keys: ['l'] },
    { commandName: 'invertViewport', label: 'Invert', keys: ['i'] },
    { commandName: 'flipViewportHorizontal', label: 'Flip Horizontally', keys: ['h'] },
    { commandName: 'flipViewportVertical', label: 'Flip Vertically', keys: ['v'] },
    { commandName: 'scaleUpViewport', label: 'Zoom In', keys: ['+'] },
    { commandName: 'scaleDownViewport', label: 'Zoom Out', keys: ['-'] },
    { commandName: 'fitViewportToWindow', label: 'Zoom to Fit', keys: ['='] },
    { commandName: 'resetViewport', label: 'Reset', keys: ['space'] },
    { commandName: 'nextImage', label: 'Next Image', keys: ['down'] },
    { commandName: 'previousImage', label: 'Previous Image', keys: ['up'] },

    {
      commandName: 'setToolActive',
      commandOptions: { toolName: 'Zoom' },
      label: 'Zoom',
      keys: ['z'],
    },

    {
      commandName: 'windowLevelPreset1',
      label: 'W/L Preset 1',
      keys: ['1'],
    },
    {
      commandName: 'windowLevelPreset2',
      label: 'W/L Preset 2',
      keys: ['2'],
    },
    {
      commandName: 'windowLevelPreset3',
      label: 'W/L Preset 3',
      keys: ['3'],
    },
    {
      commandName: 'windowLevelPreset4',
      label: 'W/L Preset 4',
      keys: ['4'],
    },
    {
      commandName: 'windowLevelPreset5',
      label: 'W/L Preset 5',
      keys: ['5'],
    },
    {
      commandName: 'windowLevelPreset6',
      label: 'W/L Preset 6',
      keys: ['6'],
    },
    {
      commandName: 'windowLevelPreset7',
      label: 'W/L Preset 7',
      keys: ['7'],
    },
    {
      commandName: 'windowLevelPreset8',
      label: 'W/L Preset 8',
      keys: ['8'],
    },
    {
      commandName: 'windowLevelPreset9',
      label: 'W/L Preset 9',
      keys: ['9'],
    },
  ],
};