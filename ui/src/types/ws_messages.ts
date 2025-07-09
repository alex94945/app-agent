// ui/src/types/ws_messages.ts

// Base interface for all WebSocket messages
export interface WsMessageBase {
  t: string; // The type of the message
  d: any;    // The data payload
}

// Specific message types for different events

export interface TokenMessage extends WsMessageBase {
  t: 'tok';
  d: string; // A piece of a streamed LLM response
}

export interface ToolCallMessage extends WsMessageBase {
  t: 'tool_call';
  d: {
    name: string;
    args: Record<string, any>;
  };
}

export interface ToolResultMessage extends WsMessageBase {
  t: 'tool_result';
  d: {
    tool_name: string;
    result: any;
  };
}

export interface FinalMessage extends WsMessageBase {
  t: 'final';
  d: string; // The final agent response
}

export interface ErrorMessage extends WsMessageBase {
  t: 'error';
  d: string; // The error message
}

// A type union for all possible incoming messages
export type WsMessage =
  | TokenMessage
  | ToolCallMessage
  | ToolResultMessage
  | FinalMessage
  | ErrorMessage;
