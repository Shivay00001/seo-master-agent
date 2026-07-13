'use client';

import { useState, useEffect } from 'react';

export default function Home() {
  const [provider, setProvider] = useState('gpt-4o');
  const [keys, setKeys] = useState({ openai: '', anthropic: '', gemini: '', glm: '' });
  
  const [activeTab, setActiveTab] = useState('onpage');
  const [inputs, setInputs] = useState<any>({
    url: '', keyword: '',
    niche: '',
    business_name: '', services: '',
    blog_url: '',
    city: '', service: ''
  });
  
  const [status, setStatus] = useState<'idle' | 'pending' | 'running' | 'success' | 'error'>('idle');
  const [taskId, setTaskId] = useState('');
  const [resultData, setResultData] = useState<any>(null);
  const [message, setMessage] = useState('');

  useEffect(() => {
    setKeys({
      openai: localStorage.getItem('seo_openai_key') || '',
      anthropic: localStorage.getItem('seo_anthropic_key') || '',
      gemini: localStorage.getItem('seo_gemini_key') || '',
      glm: localStorage.getItem('seo_glm_key') || ''
    });

    let interval: NodeJS.Timeout;
    if (taskId && (status === 'pending' || status === 'running')) {
      interval = setInterval(async () => {
        try {
          const res = await fetch(`http://localhost:8009/api/tasks/${taskId}`);
          if (res.ok) {
            const data = await res.json();
            setStatus(data.status);
            if (data.status === 'success') {
              setResultData(data.result);
              setMessage('SEO Task Complete!');
            } else if (data.status === 'error') {
              setMessage('Error performing SEO task.');
            }
          }
        } catch (e) {
          console.error("Polling error", e);
        }
      }, 3000);
    }
    return () => clearInterval(interval);
  }, [taskId, status]);

  const handleKeyChange = (provider: string, val: string) => {
    setKeys(prev => ({...prev, [provider]: val}));
  };

  const handleInputChange = (field: string, val: string) => {
    setInputs((prev: any) => ({...prev, [field]: val}));
  };

  const handleExecute = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus('pending');
    setMessage(`Running ${activeTab.toUpperCase()} workflow via ${provider}...`);
    setResultData(null);
    
    try {
      localStorage.setItem('seo_openai_key', keys.openai);
      localStorage.setItem('seo_anthropic_key', keys.anthropic);
      localStorage.setItem('seo_gemini_key', keys.gemini);
      localStorage.setItem('seo_glm_key', keys.glm);

      const res = await fetch('http://localhost:8009/api/execute', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'X-OpenAI-Key': keys.openai,
          'X-Anthropic-Key': keys.anthropic,
          'X-Gemini-Key': keys.gemini,
          'X-GLM-Key': keys.glm,
        },
        body: JSON.stringify({
          task_type: activeTab,
          inputs: inputs,
          model_id: provider
        }),
      });
      
      const data = await res.json();
      if (res.ok) {
        setTaskId(data.task_id);
      } else {
        setStatus('error');
        setMessage('Failed to start task.');
      }
    } catch (e) {
      console.error(e);
      setStatus('error');
      setMessage('Network error.');
    }
  };

  const renderInputs = () => {
    switch(activeTab) {
      case 'onpage': return (
        <>
          <div className="form-group"><label>Target URL</label><input type="url" value={inputs.url} onChange={e => handleInputChange('url', e.target.value)} required /></div>
          <div className="form-group"><label>Primary Keyword</label><input type="text" value={inputs.keyword} onChange={e => handleInputChange('keyword', e.target.value)} required /></div>
        </>
      );
      case 'offpage': return (
        <div className="form-group"><label>Brand/Niche Overview</label><textarea rows={4} value={inputs.niche} onChange={e => handleInputChange('niche', e.target.value)} placeholder="e.g. B2B SaaS for accountants..." required /></div>
      );
      case 'gmb': return (
        <>
          <div className="form-group"><label>Business Name</label><input type="text" value={inputs.business_name} onChange={e => handleInputChange('business_name', e.target.value)} required /></div>
          <div className="form-group"><label>Services Offered</label><textarea rows={3} value={inputs.services} onChange={e => handleInputChange('services', e.target.value)} required /></div>
        </>
      );
      case 'content': return (
        <div className="form-group"><label>Source Blog Post URL</label><input type="url" value={inputs.blog_url} onChange={e => handleInputChange('blog_url', e.target.value)} required /></div>
      );
      case 'geo': return (
        <>
          <div className="form-group"><label>Target City</label><input type="text" value={inputs.city} onChange={e => handleInputChange('city', e.target.value)} required placeholder="e.g. Austin, TX" /></div>
          <div className="form-group"><label>Service Keyword</label><input type="text" value={inputs.service} onChange={e => handleInputChange('service', e.target.value)} required placeholder="e.g. Emergency Plumber" /></div>
        </>
      );
    }
  };

  return (
    <main className="dashboard-container">
      <div className="dashboard-header">
        <h1>SEO Master Agent</h1>
        <p style={{fontSize: '1.2rem', color: '#718096', marginTop: '10px'}}>The 5-Pillar Autonomous Command Center</p>
      </div>

      <div style={{display: 'flex', gap: '30px', flexWrap: 'wrap'}}>
        <div style={{flex: '1 1 400px'}}>
          <div className="panel">
            <h2 className="panel-title">Universal Multi-LLM Gateway</h2>
            
            <div className="form-group"><label>OpenAI (GPT-4o)</label><input type="password" value={keys.openai} onChange={(e) => handleKeyChange('openai', e.target.value)} /></div>
            <div className="form-group"><label>Anthropic (Claude 3.5)</label><input type="password" value={keys.anthropic} onChange={(e) => handleKeyChange('anthropic', e.target.value)} /></div>
            <div className="form-group"><label>Google AI (Gemini 1.5)</label><input type="password" value={keys.gemini} onChange={(e) => handleKeyChange('gemini', e.target.value)} /></div>
            <div className="form-group"><label>ZhipuAI (GLM-4)</label><input type="password" value={keys.glm} onChange={(e) => handleKeyChange('glm', e.target.value)} /></div>

            <div className="form-group" style={{marginTop: '20px'}}>
              <label style={{color: 'var(--primary)'}}>Active AI Engine</label>
              <select value={provider} onChange={(e) => setProvider(e.target.value)} disabled={status === 'pending' || status === 'running'}>
                <option value="gpt-4o">OpenAI (gpt-4o)</option>
                <option value="claude-3-5-sonnet-20240620">Anthropic (claude-3-5-sonnet) - Best for SEO Copy</option>
                <option value="gemini/gemini-1.5-pro">Google AI (gemini-1.5-pro)</option>
                <option value="zhipu/glm-4">ZhipuAI (glm-4)</option>
                <option value="ollama/llama3">Ollama (llama3 - local privacy)</option>
              </select>
            </div>
          </div>

          <div className="panel">
            <div className="tabs-container">
              <div className={`tab ${activeTab==='onpage'?'active':''}`} onClick={()=>setActiveTab('onpage')}>On-Page</div>
              <div className={`tab ${activeTab==='offpage'?'active':''}`} onClick={()=>setActiveTab('offpage')}>Off-Page</div>
              <div className={`tab ${activeTab==='gmb'?'active':''}`} onClick={()=>setActiveTab('gmb')}>GMB</div>
              <div className={`tab ${activeTab==='content'?'active':''}`} onClick={()=>setActiveTab('content')}>Content</div>
              <div className={`tab ${activeTab==='geo'?'active':''}`} onClick={()=>setActiveTab('geo')}>Geo SEO</div>
            </div>
            
            <form onSubmit={handleExecute}>
              {renderInputs()}
              <button type="submit" className="btn" style={{width: '100%', marginTop: '20px'}} disabled={status === 'pending' || status === 'running'}>
                {status === 'pending' || status === 'running' ? 'Executing Pipeline...' : `Run ${activeTab.toUpperCase()} Strategy`}
              </button>
            </form>
          </div>

          {status !== 'idle' && status !== 'success' && (
            <div className={`status-message ${status}`}>{message}</div>
          )}
        </div>

        <div style={{flex: '2 1 600px'}}>
          <div className="panel" style={{height: '100%', minHeight: '600px'}}>
            <h2 className="panel-title">SEO Output Matrix</h2>
            
            {status === 'idle' ? (
              <p style={{color: '#a0aec0', textAlign: 'center', marginTop: '100px'}}>Select a pillar and run the strategy to generate SEO outputs.</p>
            ) : status === 'running' || status === 'pending' ? (
              <div style={{textAlign: 'center', marginTop: '100px'}}>
                <div style={{width: '60px', height: '60px', border: '4px solid #e2e8f0', borderTopColor: 'var(--primary)', borderRadius: '50%', animation: 'spin 1s linear infinite', margin: '0 auto'}}></div>
                <style>{`@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }`}</style>
                <p style={{marginTop: '20px', fontWeight: 'bold', color: 'var(--primary)'}}>Architecting SEO Strategy...</p>
              </div>
            ) : resultData ? (
              <div>
                {Object.keys(resultData).map((key, i) => (
                  <div key={i} className="result-card">
                    <h3>{key.replace(/_/g, ' ').toUpperCase()}</h3>
                    {typeof resultData[key] === 'string' ? (
                      <p>{resultData[key]}</p>
                    ) : (
                      <pre>{JSON.stringify(resultData[key], null, 2)}</pre>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <p>Failed to load data.</p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
