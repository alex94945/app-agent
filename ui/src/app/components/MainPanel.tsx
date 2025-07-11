import React from 'react';
import TerminalView from './TerminalView';

interface MainPanelProps {
  activeTab: 'preview' | 'terminal';
  setActiveTab: (tab: 'preview' | 'terminal') => void;
  terminalLogs: string[];
}

const MainPanel: React.FC<MainPanelProps> = ({ activeTab, setActiveTab, terminalLogs }) => {
  return (
    <div className="flex-1 flex flex-col p-4">
      <div className="flex border-b border-gray-300 dark:border-gray-700">
        <button
          className={`px-4 py-2 ${activeTab === 'preview' ? 'border-b-2 border-blue-500' : ''}`}
          onClick={() => setActiveTab('preview')}
        >
          Live App Preview
        </button>
        <button
          className={`px-4 py-2 ${activeTab === 'terminal' ? 'border-b-2 border-blue-500' : ''}`}
          onClick={() => setActiveTab('terminal')}
        >
          Terminal
        </button>
      </div>
      <div className="flex-1 mt-4">
        {activeTab === 'preview' ? (
          <iframe
            className="w-full h-full bg-white border-2 border-gray-300 rounded-lg dark:border-gray-700"
            title="Live Preview"
          ></iframe>
        ) : (
          <TerminalView logs={terminalLogs} />
        )}
      </div>
    </div>
  );
};

export default MainPanel;
