import ChatInterface from "@/app/components/ChatInterface";

export default function Home() {
  return (
    <main className="flex h-screen bg-gray-100 dark:bg-gray-900">
      <ChatInterface />

      {/* Preview Panel */}
      <div className="flex-1 flex items-center justify-center p-4">
        <iframe
          className="w-full h-full bg-white border-2 border-gray-300 rounded-lg dark:border-gray-700"
          title="Live Preview"
        ></iframe>
      </div>
    </main>
  );
}
