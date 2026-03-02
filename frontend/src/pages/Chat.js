import React, { useState, useRef, useEffect } from 'react';
import { api } from '../services/api';

function Chat() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: "I'm **Supply Chain Ghost** — your AI supply chain analyst powered by Amazon Nova. Ask me about active risks, supplier reliability, disruption forecasts, or mitigation strategies. I'll cite evidence and show my cost math.",
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function sendMessage(e) {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = input.trim();
    setInput('');
    const updatedMessages = [...messages, { role: 'user', content: userMessage }];
    setMessages(updatedMessages);
    setLoading(true);

    try {
      // Send conversation history (excluding the intro message)
      const history = updatedMessages
        .filter((_, i) => i > 0) // skip initial assistant greeting
        .map(m => ({ role: m.role, content: m.content }));
      const data = await api.chat(userMessage, '', history);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.response || 'I encountered an issue processing your request.',
        sources: data.sources,
        confidence: data.confidence,
      }]);
    } catch (err) {
      console.error('Chat error:', err);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: `Sorry, I encountered an error: ${err.message || 'Unknown error'}. Please try again.`,
        error: true,
      }]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  const quickPrompts = [
    'What are the current active risks?',
    'Which suppliers have reliability below 90%?',
    'Analyze Shanghai port congestion impact',
    'Compare costs of switching vs waiting for delays',
    'What disruptions should I prepare for next week?',
  ];

  function renderMarkdown(text) {
    // Simple markdown-like rendering
    return text
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`(.*?)`/g, '<code style="background:var(--bg-primary);padding:2px 6px;border-radius:4px;font-size:13px">$1</code>')
      .replace(/\n/g, '<br/>');
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 120px)' }}>
      <div className="page-header" style={{ flexShrink: 0 }}>
        <h2>Ask the Ghost 👻</h2>
        <p>Conversational AI supply chain analyst — powered by Amazon Nova 2 Lite</p>
      </div>

      {/* Chat Messages */}
      <div className="chat-container" style={{ flex: 1, overflowY: 'auto' }}>
        {messages.map((msg, i) => (
          <div key={i} className={`chat-message ${msg.role}`}>
            <div className="chat-avatar">
              {msg.role === 'assistant' ? '👻' : '👤'}
            </div>
            <div className="chat-bubble">
              <div
                dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                style={{ lineHeight: 1.6 }}
              />
              {msg.sources && msg.sources.length > 0 && (
                <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid var(--border-color)' }}>
                  <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>SOURCES</div>
                  {msg.sources.map((src, si) => (
                    <span key={si} style={{
                      display: 'inline-block', fontSize: '12px', padding: '2px 8px',
                      background: 'var(--bg-primary)', borderRadius: '4px', margin: '2px 4px 2px 0',
                      color: 'var(--accent-cyan)',
                    }}>
                      {src}
                    </span>
                  ))}
                </div>
              )}
              {msg.confidence && (
                <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--text-muted)' }}>
                  Confidence: {msg.confidence}%
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="chat-message assistant">
            <div className="chat-avatar">👻</div>
            <div className="chat-bubble" style={{ color: 'var(--text-muted)' }}>
              <div className="typing-indicator">
                <span></span><span></span><span></span>
              </div>
              Analyzing supply chain data...
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Quick Prompts */}
      {messages.length <= 1 && (
        <div style={{ padding: '12px 0', display: 'flex', flexWrap: 'wrap', gap: '8px', flexShrink: 0 }}>
          {quickPrompts.map((prompt, i) => (
            <button
              key={i}
              className="btn btn-secondary"
              style={{ fontSize: '13px', padding: '6px 12px' }}
              onClick={() => {
                setInput(prompt);
                inputRef.current?.focus();
              }}
            >
              {prompt}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <form onSubmit={sendMessage} className="chat-input-area" style={{ flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-end' }}>
          <textarea
            ref={inputRef}
            className="input"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage(e);
              }
            }}
            placeholder="Ask about risks, suppliers, disruptions, costs..."
            rows={2}
            style={{ flex: 1, resize: 'none' }}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={!input.trim() || loading}
            style={{ height: '52px', minWidth: '80px' }}
          >
            {loading ? '...' : 'Send'}
          </button>
        </div>
      </form>
    </div>
  );
}

export default Chat;
