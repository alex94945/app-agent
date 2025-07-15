'use client';

import React, { useEffect, useRef, useState } from 'react';
import { WebContainer, FileSystemTree } from '@webcontainer/api';

interface PreviewFrameProps {
  files: Record<string, string>;
}

let webContainerInstance: WebContainer;

const PreviewFrame: React.FC<PreviewFrameProps> = ({ files }) => {
  const [previewUrl, setPreviewUrl] = useState<string>('');
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [status, setStatus] = useState<string>('Booting WebContainer...');

  useEffect(() => {
    if (!files || Object.keys(files).length === 0) {
      // Don't boot until we have files
      setStatus('Waiting for files from agent...');
      return;
    }

    const bootWebContainer = async () => {
      if (webContainerInstance) {
        return;
      }

      try {
        setStatus('Booting WebContainer...');
        webContainerInstance = await WebContainer.boot();
        setStatus('WebContainer booted.');

        const fileSystemTree: FileSystemTree = {};
        for (const [path, content] of Object.entries(files)) {
          const pathParts = path.split('/');
          let currentLevel = fileSystemTree;
          for (let i = 0; i < pathParts.length - 1; i++) {
            const part = pathParts[i];
            if (!currentLevel[part]) {
              currentLevel[part] = { directory: {} };
            }
            currentLevel = (currentLevel[part] as { directory: {} }).directory;
          }
          currentLevel[pathParts[pathParts.length - 1]] = {
            file: { contents: content },
          };
        }

        setStatus('Mounting files...');
        await webContainerInstance.mount(fileSystemTree);

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

    bootWebContainer();
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
