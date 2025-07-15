'use client';

import React, { useEffect, useState, useRef } from 'react';
import { useWebSocket } from '@/contexts/WebSocketContext';
import { WebContainer, FileSystemTree } from '@webcontainer/api';

// NOTE: We will get files from an API endpoint now, not props.
interface PreviewFrameProps {}

let webContainerInstance: WebContainer;

const PreviewFrame: React.FC<PreviewFrameProps> = () => {
  const { lastMessage, sendMessage } = useWebSocket();
  const [fileSystemTree, setFileSystemTree] = useState<FileSystemTree>({});
  const hasBooted = useRef(false); // Prevent multiple boots
  const [previewUrl, setPreviewUrl] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [status, setStatus] = useState<string>('Booting WebContainer...');

    useEffect(() => {
    const bootWebContainer = async (files: FileSystemTree) => {
      try {
        setStatus('Booting WebContainer...');
        // Set a more permissive CORS policy to allow the iframe to connect
        webContainerInstance = await WebContainer.boot();
        setStatus('WebContainer booted.');

        setStatus('Mounting files...');
        await webContainerInstance.mount(files);

        setStatus('Running npm install...');
        const installProcess = await webContainerInstance.spawn('npm', ['install']);
        installProcess.output.pipeTo(new WritableStream({
          write(data) {
            setStatus(`npm install: ${data}`);
          }
        }));
        const installExitCode = await installProcess.exit;
        if (installExitCode !== 0) {
          setStatus(`npm install failed with code ${installExitCode}`);
          return;
        }

        setStatus('Running npm run dev...');
        await webContainerInstance.spawn('npm', ['run', 'dev']);

        webContainerInstance.on('server-ready', (port, url) => {
          setStatus(`Server ready at ${url}`);
          setPreviewUrl(url);
          setIsLoading(false);
        });

        webContainerInstance.on('error', (error) => {
          console.error('WebContainer error:', error);
          setStatus(`Error: ${error.message}`);
          setIsLoading(false);
        });

      } catch (error) {
        console.error('Failed to boot WebContainer:', error);
        setStatus('Failed to boot WebContainer.');
        setIsLoading(false);
      }
    };

    // Request initial files when component mounts
    useEffect(() => {
      setStatus('Requesting initial project files...');
      sendMessage(JSON.stringify({ type: 'request_initial_files' }));
    }, [sendMessage]);

    // Handle incoming WebSocket messages for file content
    useEffect(() => {
      if (!lastMessage) return;

      const msg = JSON.parse(lastMessage.data);

      if (msg.t === 'file_content') {
        const { path, content } = msg.d;
        setFileSystemTree(prevTree => {
          const newTree = { ...prevTree };
          const pathParts = path.split('/');
          let currentLevel: FileSystemTree = newTree;

          for (let i = 0; i < pathParts.length - 1; i++) {
            const part = pathParts[i];
            if (!currentLevel[part]) {
              currentLevel[part] = { directory: {} };
            }
            currentLevel = (currentLevel[part] as { directory: FileSystemTree }).directory;
          }
          currentLevel[pathParts[pathParts.length - 1]] = {
            file: { contents: content },
          };
          return newTree;
        });
      } else if (msg.t === 'initial_files_loaded' && !hasBooted.current) {
        hasBooted.current = true; // Ensure we only boot once
        setStatus('All files received. Booting WebContainer...');
        bootWebContainer(fileSystemTree);
      }
    }, [lastMessage, fileSystemTree]);

  }, []);

  if (isLoading) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-gray-100 dark:bg-gray-800">
        <p className="text-lg">{status}</p>
      </div>
    );
  }

  return (
    <iframe
      src={previewUrl}
      className="w-full h-full bg-white border-2 border-gray-300 rounded-lg dark:border-gray-700"
      title="Live Preview"
    ></iframe>
  );
};

export default PreviewFrame;
