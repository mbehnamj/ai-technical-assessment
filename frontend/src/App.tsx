import { useChat } from "./hooks/useChat";
import { ChatPanel } from "./components/ChatPanel";
import { DocumentPanel } from "./components/DocumentPanel";

export default function App() {
  const {
    messages,
    document,
    metadata,
    isStreaming,
    isLoading,
    error,
    sendMessage,
    resetConversation,
  } = useChat();

  return (
    <div className="app-layout">
      <ChatPanel
        messages={messages}
        metadata={metadata}
        isStreaming={isStreaming}
        isLoading={isLoading}
        error={error}
        onSendMessage={sendMessage}
        onReset={resetConversation}
      />
      <div className="app-divider" />
      <DocumentPanel
        document={document}
        metadata={metadata}
        isStreaming={isStreaming}
      />
    </div>
  );
}
