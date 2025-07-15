export interface TokenMessage {
  t: 'tok';
  d: string;
}

export interface ToolCallMessage {
  t: 'tool_call';
  d: {
    name: string;
    args: Record<string, any>;
  };
}

export interface ToolResultMessage {
  t: 'tool_result';
  d: {
    tool_name: string;
    result: any;
  };
}

export interface FinalMessage {
  t: 'final';
  d: string;
}

export interface ErrorMessage {
  t: 'error';
  d: string;
}

// PTY Task Streaming Messages

export interface TaskStartedData {
  task_id: string; // UUID is a string in TS
  name: string;
  started_at: string; // ISO 8601 datetime string
}

export interface TaskStartedMessage {
  t: 'task_started';
  d: TaskStartedData;
}

export interface TaskLogData {
  task_id: string;
  chunk: string;
}

export interface TaskLogMessage {
  t: 'task_log';
  d: TaskLogData;
}

export interface TaskFinishedData {
  task_id: string;
  state: 'success' | 'error' | 'timeout';
  exit_code: number | null;
  duration_ms: number;
}

export interface TaskFinishedMessage {
  t: 'task_finished';
  d: TaskFinishedData;
}

// File system update message
export interface FileUpdateData {
  path: string;
  content: string;
}

export interface FileUpdateMessage {
  t: 'file_update';
  d: FileUpdateData;
}

// Message for streaming initial file contents
export interface FileContentMessage {
    t: 'file_content';
    d: {
        path: string;
        content: string;
    };
}

// Message to signal that all initial files have been sent
export interface InitialFilesLoadedMessage {
    t: 'initial_files_loaded';
    d: null; // No data needed for this signal
}


// Union type for all possible incoming WebSocket messages
export type WsMessage = 
  | TokenMessage 
  | ToolCallMessage 
  | ToolResultMessage 
  | FinalMessage 
  | ErrorMessage
  | TaskStartedMessage
  | TaskLogMessage
  | TaskFinishedMessage
  | FileUpdateMessage
  | FileContentMessage
  | InitialFilesLoadedMessage;

