'use client';

import { useState, FormEvent } from 'react';

// This type will be lifted to a shared location or the parent component.
export interface DisplayMessage {
  source: 'user' | 'agent' | 'system' | 'tool';
  content: string;
  type: 'text' | 'tool_call' | 'tool_result' | 'error';
}

interface ChatInterfaceProps {
  messages: DisplayMessage[];
  onSendMessage: (message: string) => void;
  isConnected: boolean;
}

export default function ChatInterface({ messages, onSendMessage, isConnected }: ChatInterfaceProps) {
  const [input, setInput] = useState('');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (input.trim() && isConnected) {
      onSendMessage(input);
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
