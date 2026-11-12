import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import DemoSample from './components/DemoSample.jsx';
import './styles.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {['/sample', '/sample/'].includes(window.location.pathname)
      ? <main><DemoSample onBack={() => window.location.assign('/')} /></main>
      : <App />}
  </React.StrictMode>,
);
