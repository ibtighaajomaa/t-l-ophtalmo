import React from 'react';
import MonaiLabelPanel from './components/MonaiLabelPanel';
import AiAnalysisPanel from './components/AiAnalysisPanel';

function getPanelModule({
  commandsManager,
  extensionManager,
  servicesManager,
}) {
  const WrappedMonaiLabelPanel = () => {
    return (
      <MonaiLabelPanel
        commandsManager={commandsManager}
        servicesManager={servicesManager}
        extensionManager={extensionManager}
      />
    );
  };

  const WrappedAiAnalysisPanel = () => {
    return (
      <AiAnalysisPanel
        commandsManager={commandsManager}
        servicesManager={servicesManager}
        extensionManager={extensionManager}
      />
    );
  };

  return [
    {
      name: 'monailabel',
      iconName: 'tab-patient-info',
      iconLabel: 'MONAI',
      label: 'MONAI Label',
      secondaryLabel: 'MONAI Label',
      component: WrappedMonaiLabelPanel,
    },
    {
      name: 'aiAnalysis',
      iconName: 'tab-patient-info',
      iconLabel: 'AI Analysis',
      label: 'AI Analysis',
      secondaryLabel: 'AI Analysis',
      component: WrappedAiAnalysisPanel,
    },
  ];
}

export default getPanelModule;
