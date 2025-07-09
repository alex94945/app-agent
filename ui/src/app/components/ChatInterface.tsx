'use client';

import { useState, useEffect, FormEvent } from 'react';
import { WsMessage } from '@/types/ws_messages';

// A simple message type for our local state
interface DisplayMessage {
  source: 'user' | 'agent' | 'system' | 'tool';
  content: string;
  type: 'text' | 'tool_call' | 'tool_result' | 'error';
}

export default function ChatInterface() {
  const [socket, setSocket] = useState<WebSocket | null>(null);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    // Assuming the gateway runs on port 8001
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

    // Clean up the connection when the component unmounts
    return () => {
      ws.close();
    };
  }, []);

  const handleIncomingMessage = (msg: WsMessage) => {
    let displayMsg: DisplayMessage | null = null;
    switch (msg.t) {
      case 'tok':
        // Append token to the last message if it's from the agent
        setMessages(prev => {
          const lastMsg = prev[prev.length - 1];
          if (lastMsg && lastMsg.source === 'agent') {
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
        break;
      case 'error':
        displayMsg = { source: 'system', content: msg.d, type: 'error' };
        break;
    }
    if (displayMsg) {
      setMessages(prev => [...prev, displayMsg]);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (input.trim() && socket && isConnected) {
      const messageToSend = { prompt: input };
      socket.send(JSON.stringify(messageToSend));
      setMessages(prev => [...prev, { source: 'user', content: input, type: 'text' }]);
      setInput('');
    }
  };

  const getMessageStyle = (source: DisplayMessage['source']) => {
    switch (source) {
      case 'user': return 'bg-blue-100 dark:bg-blue-900 self-end';
      case 'agent': return 'bg-gray-200 dark:bg-gray-700 self-start';
      case 'tool': return 'bg-yellow-100 dark:bg-yellow-800 text-xs italic self-start';
      case 'system': return 'bg-red-100 dark:bg-red-900 text-xs text-center self-center';
      default: return 'bg-white dark:bg-gray-800';
    }
  };

  return (
    <div className="flex flex-col w-1/3 max-w-md border-r border-gray-200 dark:border-gray-800 h-full">
      <div className="flex-1 p-4 overflow-y-auto flex flex-col gap-3">
        {messages.map((msg, index) => (
          <div key={index} className={`p-2 rounded-lg max-w-xs ${getMessageStyle(msg.source)}`}>
            <p className="whitespace-pre-wrap">{msg.content}</p>
          </div>
        ))}
      </div>
      <div className="p-4 border-t border-gray-200 dark:border-gray-800">
        <form className="flex gap-2" onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder={isConnected ? 'Type your message...' : 'Connecting...'}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="flex-1 p-2 border rounded-lg focus:ring-blue-500 focus:border-blue-500 dark:bg-gray-800 dark:border-gray-700 dark:text-white"
            disabled={!isConnected}
          />
          <button
            type="submit"
            className="px-4 py-2 font-semibold text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:bg-gray-500"
            disabled={!isConnected}
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
