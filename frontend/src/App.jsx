import React, { useState, useEffect, useRef } from 'react';
import {
  Send,
  Zap,
  Radio,
  Server,
  RefreshCw,
  AlertTriangle,
  Settings,
  ChevronDown,
  ChevronUp,
  Cpu,
  Layers,
  CheckCircle2,
  Clock,
  Sparkles
} from 'lucide-react';

const DEFAULT_BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';

function generateSessionId() {
  const rand = Math.random().toString(36).substring(2, 10);
  return `s-${rand}`;
}

export default function App() {
  // Session starts on each page load
  const [sessionId, setSessionId] = useState(() => generateSessionId());
  const [systemPrompt, setSystemPrompt] = useState('');
  const [showSystemPrompt, setShowSystemPrompt] = useState(false);
  const [simulateFailure, setSimulateFailure] = useState('none');
  const [backendUrl, setBackendUrl] = useState(DEFAULT_BACKEND_URL);

  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [healthStatus, setHealthStatus] = useState(null);

  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  // Check backend health on mount
  useEffect(() => {
    fetchHealth();
  }, [backendUrl]);

  const fetchHealth = async () => {
    try {
      const res = await fetch(`${backendUrl}/health`);
      if (res.ok) {
        const data = await res.json();
        setHealthStatus(data);
      } else {
        setHealthStatus({ status: 'error' });
      }
    } catch (err) {
      setHealthStatus({ status: 'unreachable' });
    }
  };

  const startNewSession = () => {
    const newId = generateSessionId();
    setSessionId(newId);
    setMessages([]);
  };

  const handleSendMessage = async (e) => {
    if (e) e.preventDefault();
    const trimmed = inputMessage.trim();
    if (!trimmed || isLoading) return;

    // Clear input immediately after sending
    setInputMessage('');

    // Append user message locally
    const userMsg = {
      role: 'user',
      content: trimmed,
      id: Date.now()
    };
    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    try {
      // Build headers
      const headers = {
        'Content-Type': 'application/json'
      };

      if (simulateFailure !== 'none') {
        headers['X-Simulate-Failure'] = simulateFailure;
      }

      // Build payload
      const payload = {
        session_id: sessionId,
        message: trimmed
      };
      if (systemPrompt.trim()) {
        payload.system_prompt = systemPrompt.trim();
      }

      const res = await fetch(`${backendUrl}/chat`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });

      const data = await res.json();

      if (!res.ok) {
        // Display readable error message in chat (never blank screen)
        const errorDetail = typeof data.detail === 'string'
          ? data.detail
          : (Array.isArray(data.detail) ? data.detail.map(d => d.msg || d).join(', ') : JSON.stringify(data.detail));

        const errorMsg = {
          role: 'error',
          statusCode: res.status,
          content: errorDetail || `Error ${res.status}: Failed to process message`,
          id: Date.now() + 1
        };
        setMessages((prev) => [...prev, errorMsg]);
      } else {
        // Successful response
        const assistantMsg = {
          role: 'assistant',
          content: data.reply,
          metadata: data.metadata,
          id: Date.now() + 1
        };
        setMessages((prev) => [...prev, assistantMsg]);
      }
    } catch (err) {
      // Network or connection error
      const errorMsg = {
        role: 'error',
        statusCode: 0,
        content: `Network Connection Error: Could not reach backend at ${backendUrl}. Check if server is running.`,
        id: Date.now() + 1
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className="flex flex-col h-screen max-w-5xl mx-auto bg-slate-900 shadow-2xl border-x border-slate-800">
      {/* Top Header */}
      <header className="px-6 py-4 border-b border-slate-800 bg-slate-950 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-cyan-400 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-lg font-bold text-white tracking-tight">Lyftr AI Chatbot</h1>
              <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                Resilient Gateway
              </span>
            </div>
            <div className="flex items-center space-x-2 text-xs text-slate-400 mt-0.5">
              <span>Session:</span>
              <span className="font-mono text-cyan-400 bg-slate-900 px-1.5 py-0.5 rounded border border-slate-800">
                {sessionId}
              </span>
            </div>
          </div>
        </div>

        {/* Status and Action Buttons */}
        <div className="flex items-center space-x-3">
          {/* Health Pill */}
          <div
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-full text-xs font-medium border ${
              healthStatus?.status === 'ok'
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
            }`}
          >
            <Server className="w-3.5 h-3.5" />
            <span>
              {healthStatus?.status === 'ok'
                ? `${healthStatus.keys_configured} Keys Ready • Cache ON`
                : 'Backend Offline'}
            </span>
          </div>

          {/* New Chat Button */}
          <button
            onClick={startNewSession}
            className="flex items-center space-x-1 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg border border-slate-700 transition"
            title="Start New Session (Generates new session_id)"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>New Chat</span>
          </button>
        </div>
      </header>

      {/* Control Strip: Simulation & System Prompt */}
      <div className="px-6 py-2.5 bg-slate-950/60 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center space-x-3">
          <span className="text-slate-400 font-medium flex items-center gap-1">
            <Radio className="w-3.5 h-3.5 text-amber-400" />
            Failover Test:
          </span>
          <select
            value={simulateFailure}
            onChange={(e) => setSimulateFailure(e.target.value)}
            className="bg-slate-900 text-slate-200 border border-slate-700 rounded-md px-2.5 py-1 text-xs focus:ring-1 focus:ring-indigo-500 outline-none"
          >
            <option value="none">Normal (Real Execution)</option>
            <option value="key_1=429">Simulate key_1=429 (Fallback to key_2)</option>
            <option value="key_1=500">Simulate key_1=500 (Fallback to key_2)</option>
            <option value="*=429">Simulate *=429 (All keys fail → 503)</option>
          </select>
          {simulateFailure !== 'none' && (
            <span className="text-amber-400 text-[11px] font-mono">
              [Header: X-Simulate-Failure: {simulateFailure}]
            </span>
          )}
        </div>

        <button
          onClick={() => setShowSystemPrompt(!showSystemPrompt)}
          className="flex items-center space-x-1 text-slate-400 hover:text-slate-200 transition"
        >
          <Settings className="w-3.5 h-3.5" />
          <span>System Prompt</span>
          {showSystemPrompt ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
      </div>

      {/* Expandable System Prompt Field */}
      {showSystemPrompt && (
        <div className="px-6 py-3 bg-slate-950/80 border-b border-slate-800">
          <label className="block text-xs font-medium text-slate-300 mb-1">
            System Prompt Override (Optional)
          </label>
          <input
            data-testid="system-prompt-input"
            type="text"
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            placeholder="e.g. You are a pirate who explains concepts in maritime terminology."
            className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
      )}

      {/* Message Stream */}
      <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center text-slate-500 space-y-4 py-16">
            <div className="w-16 h-16 rounded-2xl bg-slate-800/80 border border-slate-700/60 flex items-center justify-center text-indigo-400">
              <Cpu className="w-8 h-8" />
            </div>
            <div>
              <h3 className="text-base font-semibold text-slate-300">Ready to Chat</h3>
              <p className="text-xs text-slate-400 max-w-sm mt-1">
                Multi-turn context is saved per session in SQLite. LiteLLM handles automated response caching and key fallback.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-2 text-left max-w-md w-full pt-4">
              <button
                onClick={() => setInputMessage('What is the capital of France?')}
                className="p-2.5 rounded-lg bg-slate-800/40 hover:bg-slate-800/80 border border-slate-800 text-xs text-slate-300 transition"
              >
                💡 "What is the capital of France?"
              </button>
              <button
                onClick={() => setInputMessage('Explain quantum computing in one sentence.')}
                className="p-2.5 rounded-lg bg-slate-800/40 hover:bg-slate-800/80 border border-slate-800 text-xs text-slate-300 transition"
              >
                ⚡ "Explain quantum computing in one sentence."
              </button>
            </div>
          </div>
        )}

        {messages.map((msg) => {
          if (msg.role === 'user') {
            return (
              <div key={msg.id} className="flex justify-end">
                <div className="max-w-[75%] rounded-2xl px-4 py-3 bg-indigo-600 text-white shadow-md text-sm leading-relaxed rounded-br-none">
                  {msg.content}
                </div>
              </div>
            );
          }

          if (msg.role === 'error') {
            return (
              <div key={msg.id} className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl p-4 bg-rose-950/40 border border-rose-800/50 text-rose-200 text-xs shadow-md">
                  <div className="flex items-center space-x-2 font-semibold text-rose-400 mb-1">
                    <AlertTriangle className="w-4 h-4" />
                    <span>Error {msg.statusCode ? `(${msg.statusCode})` : ''}</span>
                  </div>
                  <div className="leading-relaxed font-mono">{msg.content}</div>
                </div>
              </div>
            );
          }

          // Assistant message with exact contract data-testids
          const meta = msg.metadata || {};
          const isCached = meta.resolution_source === 'LLM_CACHE';

          return (
            <div
              key={msg.id}
              data-testid="assistant-message"
              className="flex flex-col space-y-2 max-w-[85%]"
            >
              <div className="rounded-2xl px-5 py-4 bg-slate-800/80 border border-slate-700/60 text-slate-100 shadow-md text-sm leading-relaxed rounded-bl-none whitespace-pre-wrap">
                {msg.content}
              </div>

              {/* Metadata Panel adhering strictly to data-testid attributes */}
              <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-400 pl-1">
                {/* Resolution Source */}
                <div
                  data-testid="meta-source"
                  className={`px-2 py-0.5 rounded-md font-semibold flex items-center space-x-1 ${
                    isCached
                      ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                      : 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20'
                  }`}
                >
                  {isCached ? <Zap className="w-3 h-3" /> : <Radio className="w-3 h-3" />}
                  <span>{meta.resolution_source}</span>
                </div>

                {/* Model */}
                <div className="flex items-center space-x-1 bg-slate-800/60 px-2 py-0.5 rounded border border-slate-700">
                  <Cpu className="w-3 h-3 text-slate-500" />
                  <span data-testid="meta-model" className="font-mono text-slate-300">
                    {meta.model}
                  </span>
                </div>

                {/* Latency */}
                <div className="flex items-center space-x-1 bg-slate-800/60 px-2 py-0.5 rounded border border-slate-700">
                  <Clock className="w-3 h-3 text-slate-500" />
                  <span data-testid="meta-latency" className="font-mono text-slate-300">
                    {meta.latency_ms} ms
                  </span>
                </div>

                {/* Tokens */}
                <div className="flex items-center space-x-1.5 bg-slate-800/60 px-2 py-0.5 rounded border border-slate-700">
                  <Layers className="w-3 h-3 text-slate-500" />
                  <span>Prompt:</span>
                  <span data-testid="meta-input-tokens" className="font-mono text-indigo-400 font-semibold">
                    {meta.input_tokens}
                  </span>
                  <span className="text-slate-600">•</span>
                  <span>Completion:</span>
                  <span data-testid="meta-output-tokens" className="font-mono text-emerald-400 font-semibold">
                    {meta.output_tokens}
                  </span>
                </div>

                {/* Key ID / Fallback Information */}
                {meta.key_id && (
                  <div className="flex items-center space-x-1 bg-slate-800/60 px-2 py-0.5 rounded border border-slate-700">
                    <span className="text-slate-500">Key:</span>
                    <span className="font-mono text-amber-400 font-medium">{meta.key_id}</span>
                  </div>
                )}
                {meta.fallback_attempts > 0 && (
                  <div className="flex items-center space-x-1 bg-amber-500/10 text-amber-400 px-2 py-0.5 rounded border border-amber-500/20">
                    <span>Fallbacks: {meta.fallback_attempts}</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {isLoading && (
          <div className="flex justify-start">
            <div className="rounded-2xl px-5 py-4 bg-slate-800/60 border border-slate-700/40 text-slate-400 text-xs flex items-center space-x-2">
              <RefreshCw className="w-4 h-4 animate-spin text-indigo-400" />
              <span>Querying gateway with failover & caching...</span>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Bar */}
      <footer className="p-4 border-t border-slate-800 bg-slate-950">
        <form onSubmit={handleSendMessage} className="flex items-center space-x-3">
          <input
            data-testid="chat-input"
            type="text"
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type your message... (Enter to send)"
            disabled={isLoading}
            className="flex-1 bg-slate-900 border border-slate-700 focus:border-indigo-500 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 transition disabled:opacity-50"
          />
          <button
            data-testid="send-button"
            type="submit"
            disabled={isLoading || !inputMessage.trim()}
            className="p-3 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl shadow-lg shadow-indigo-600/30 transition disabled:opacity-40 disabled:hover:bg-indigo-600 disabled:shadow-none flex items-center justify-center"
            title="Send Message"
          >
            <Send className="w-4 h-4" />
          </button>
        </form>
      </footer>
    </div>
  );
}
