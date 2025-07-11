import React, { useEffect, useRef } from 'react';

interface TerminalViewProps {
  logs: string[];
}

const TerminalView: React.FC<TerminalViewProps> = ({ logs }) => {
  const endOfLogsRef = useRef<null | HTMLDivElement>(null);

  useEffect(() => {
    endOfLogsRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="bg-black text-white font-mono p-4 h-full overflow-y-auto">
      {logs.map((log, index) => (
        <p key={index} className="whitespace-pre-wrap">{`> ${log}`}</p>
      ))}
      <div ref={endOfLogsRef} />
    </div>
  );
};

export default TerminalView;
