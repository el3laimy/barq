import { render } from 'preact';
import { useState, useEffect } from 'preact/hooks';

function App() {
  const [status, setStatus] = useState('Disconnected');

  useEffect(() => {
    // Check connection status placeholder
    setStatus('Connected');
  }, []);

  const handleDownload = () => {
    console.log('Download current page clicked');
  };

  return (
    <div style={{ width: '300px', padding: '16px', fontFamily: 'sans-serif' }}>
      <h2>Barq Integration</h2>
      <p>Status: <strong>{status}</strong></p>
      <button 
        onClick={handleDownload}
        style={{ width: '100%', padding: '8px', cursor: 'pointer' }}
      >
        Download current page
      </button>
      <p style={{ fontSize: '12px', marginTop: '16px', color: '#666' }}>Version 1.0.0</p>
    </div>
  );
}

render(<App />, document.getElementById('app')!);
