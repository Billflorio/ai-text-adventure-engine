import { useState, useEffect } from 'react';
import { Send, Settings, Play, Image as ImageIcon } from 'lucide-react';
import './App.css';

function App() {
  const [status, setStatus] = useState('checking'); // checking, missing, downloading, ready
  const [progress, setProgress] = useState({ item: '', percent: 0 });
  const [messages, setMessages] = useState([
    { role: 'system', content: 'Welcome to your AI Text Adventure. You wake up in a dark, damp cave...' }
  ]);
  const [input, setInput] = useState('');
  const [imageUrl, setImageUrl] = useState('');

  useEffect(() => {
    // Check if models exist on startup
    if (window.electronAPI) {
      window.electronAPI.checkModels().then((res: any) => {
        if (res.textModel && res.serverExe) {
          startServers();
        } else {
          setStatus('missing');
        }
      });

      window.electronAPI.onDownloadProgress((data: any) => {
        setProgress(data);
      });
    } else {
      // Browser fallback (dev mode without electron)
      setStatus('ready');
    }
  }, []);

  const handleDownload = () => {
    setStatus('downloading');
    window.electronAPI.downloadModels().then((res: any) => {
      if (res.success) {
        startServers();
      } else {
        alert('Download failed: ' + res.error);
        setStatus('missing');
      }
    });
  };

  const startServers = () => {
    setStatus('starting');
    window.electronAPI.startLocalServers().then(() => {
      setStatus('ready');
    });
  };

  const [showSettings, setShowSettings] = useState(false);
  const [useCloud, setUseCloud] = useState(() => localStorage.getItem('useCloud') === 'true');
  const [openAiKey, setOpenAiKey] = useState(() => localStorage.getItem('openAiKey') || '');

  const saveSettings = () => {
    localStorage.setItem('useCloud', useCloud.toString());
    localStorage.setItem('openAiKey', openAiKey);
    setShowSettings(false);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;
    
    const userMessage = { role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setStatus('generating-text');
    
    try {
      let url = 'http://127.0.0.1:8080/v1/chat/completions';
      let headers: any = { 'Content-Type': 'application/json' };
      
      if (useCloud && openAiKey) {
        url = 'https://api.openai.com/v1/chat/completions';
        headers['Authorization'] = `Bearer ${openAiKey}`;
      }
      
      const response = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          model: useCloud ? 'gpt-4o-mini' : undefined,
          messages: [...messages, userMessage],
          temperature: 0.7,
          max_tokens: 200,
        }),
      });
      
      const data = await response.json();
      const aiReply = data.choices[0].message.content;
      
      setMessages(prev => [...prev, { role: 'system', content: aiReply }]);
      
      // Simulate image generation for the new scene
      setImageUrl(`https://picsum.photos/seed/${Date.now()}/800/600`);
      
      setStatus('ready');
    } catch (err) {
      console.error(err);
      setMessages(prev => [...prev, { role: 'system', content: `[Error communicating with AI engine. Check settings or wait for local server to boot.]` }]);
      setStatus('ready');
    }
  };

  if (status !== 'ready') {
    return (
      <div className="setup-container">
        <div className="setup-card">
          <h1>AI Text Adventure</h1>
          {status === 'checking' && <p>Checking local models...</p>}
          
          {status === 'missing' && (
            <div className="missing-models">
              <p>Welcome! We need to download the local AI models (approx. 3.5GB) to run the game securely on your machine.</p>
              <button onClick={handleDownload} className="btn primary"><Play size={18}/> Start Download</button>
            </div>
          )}

          {status === 'downloading' && (
            <div className="download-progress">
              <p>Downloading {progress.item}...</p>
              <div className="progress-bar">
                <div className="progress-fill" style={{ width: `${typeof progress.percent === 'number' ? progress.percent : 100}%` }}></div>
              </div>
              <span>{progress.percent}%</span>
            </div>
          )}

          {status === 'starting' && <p>Starting Local AI Servers...</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <header className="app-header">
        <h2>AI Text Adventure</h2>
        <button className="icon-btn" onClick={() => setShowSettings(true)}><Settings size={20} /></button>
      </header>
      
      {showSettings && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3>Settings</h3>
            <div className="setting-row">
              <label>
                <input type="checkbox" checked={useCloud} onChange={e => setUseCloud(e.target.checked)} />
                Use Cloud API (OpenAI)
              </label>
            </div>
            {useCloud && (
              <div className="setting-row">
                <label>OpenAI API Key:</label>
                <input type="password" value={openAiKey} onChange={e => setOpenAiKey(e.target.value)} />
              </div>
            )}
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowSettings(false)}>Cancel</button>
              <button className="btn primary" onClick={saveSettings}>Save Settings</button>
            </div>
          </div>
        </div>
      )}
      
      <div className="split-pane">
        {/* Left Pane: Image */}
        <div className="pane image-pane">
          {imageUrl ? (
            <img src={imageUrl} alt="Current Scene" className="scene-image" />
          ) : (
            <div className="image-placeholder">
              <ImageIcon size={48} opacity={0.5} />
              <p>Scene image generating...</p>
            </div>
          )}
        </div>

        {/* Divider */}
        <div className="resizer"></div>

        {/* Right Pane: Text */}
        <div className="pane text-pane">
          <div className="story-container">
            {messages.map((m, i) => (
              <div key={i} className={`message ${m.role}`}>
                {m.role === 'user' ? '> ' : ''}{m.content}
              </div>
            ))}
          </div>
          
          <form className="input-container" onSubmit={handleSubmit}>
            <input 
              type="text" 
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="What do you want to do?" 
              autoFocus
            />
            <button type="submit" className="icon-btn submit-btn"><Send size={20} /></button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default App;
