export default function getCommandsModule({ servicesManager }) {
  const { uiNotificationService, uiViewportService } = servicesManager.services;

  const actions = {
    setToolActive: ({ toolName }) => {
      uiNotificationService.show({
        title: 'MONAI Label probe',
        message: 'MONAI Label Probe Activated.',
        type: 'info',
        duration: 3000,
      });
    },
    runAiAnalysis: () => {
      uiNotificationService.show({
        title: 'AI Analysis',
        message: 'Open the AI Analysis panel to run analysis.',
        type: 'info',
        duration: 3000,
      });
    },
    selectAiEyeRight: () => {
      window.dispatchEvent(new CustomEvent('teleophtalmo:ai-eye-selected', {
        detail: { eye: 'right' },
      }));
    },
    selectAiEyeLeft: () => {
      window.dispatchEvent(new CustomEvent('teleophtalmo:ai-eye-selected', {
        detail: { eye: 'left' },
      }));
    },
  };

  const definitions = {
  };

  return {
    actions,
    definitions,
    defaultContext: 'MONAILabel',
  };
}
