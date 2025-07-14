'use client';

import { useState, useEffect } from 'react';
import ChatInterface, { DisplayMessage } from '@/app/components/ChatInterface';
import MainPanel from '@/app/components/MainPanel';
import { WsMessage } from '@/types/ws_messages';

export default function Home() {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<'preview' | 'terminal'>('preview');

  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8001/api/agent');

    ws.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
      setMessages([{ source: 'system', content: 'Connected to agent.', type: 'text' }]);
    };

    ws.onmessage = (event) => {
      try {
        const message: WsMessage = JSON.parse(event.data);
        handleIncomingMessage(message);
      } catch (error) {
        console.error('Failed to parse incoming message:', event.data);
        setMessages(prev => [...prev, { source: 'system', content: 'Received malformed message.', type: 'error' }]);
      }
    };

    ws.onclose = () => {
      console.log('WebSocket disconnected');
      setIsConnected(false);
      setMessages(prev => [...prev, { source: 'system', content: 'Connection lost.', type: 'error' }]);
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
      setMessages(prev => [...prev, { source: 'system', content: 'Connection error.', type: 'error' }]);
    };

    setSocket(ws);

    return () => {
      ws.close();
    };
  }, []);

  const handleIncomingMessage = (msg: WsMessage) => {
    let displayMsg: DisplayMessage | null = null;
    switch (msg.t) {
      case 'tok':
        setMessages(prev => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.source === 'agent' && lastMsg.type === 'text') {
            return [...prev.slice(0, -1), { ...lastMsg, content: lastMsg.content + msg.d }];
          }
          return [...prev, { source: 'agent', content: msg.d, type: 'text' }];
        });
        break;
      case 'tool_call':
        displayMsg = { source: 'tool', content: `Calling: ${msg.d.name}(${JSON.stringify(msg.d.args)})`, type: 'tool_call' };
        break;
      case 'tool_result':
        displayMsg = { source: 'tool', content: `Result from ${msg.d.tool_name}: ${JSON.stringify(msg.d.result)}`, type: 'tool_result' };
        break;
      case 'final':
        displayMsg = { source: 'agent', content: msg.d, type: 'text' };
        // When a final message is received, switch back to the preview
        setActiveTab('preview');
        break;
      case 'error':
        displayMsg = { source: 'system', content: msg.d, type: 'error' };
        break;
      case 'task_started':
        setMessages(prev => [...prev, { source: 'system', content: `Task started: ${msg.d.name}`, type: 'text' }]);
        setTerminalLogs([`Task started: ${msg.d.name}`]);
        setActiveTab('terminal');
        break;
      case 'task_log':
        setTerminalLogs(prev => [...prev, msg.d.chunk]);
        break;
      case 'task_finished':
        setMessages(prev => [...prev, { source: 'system', content: `Task finished with state: ${msg.d.state}`, type: 'text' }]);
        setTerminalLogs(prev => [...prev, `Task finished with state: ${msg.d.state}`]);
        break;
    }
    if (displayMsg) {
      setMessages(prev => [...prev, displayMsg]);
    }
  };

  const handleSendMessage = (prompt: string) => {
    if (socket && isConnected) {
      const messageToSend = { prompt };
      socket.send(JSON.stringify(messageToSend));
      setMessages(prev => [...prev, { source: 'user', content: prompt, type: 'text' }]);
    }
  };

  return (
    <main className="flex h-screen bg-gray-100 dark:bg-gray-900">
      <ChatInterface 
        messages={messages}
        onSendMessage={handleSendMessage}
        isConnected={isConnected}
      />
      <MainPanel
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        terminalLogs={terminalLogs}
      />
    </main>
  );
}
