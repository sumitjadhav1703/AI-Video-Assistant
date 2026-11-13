import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import EvalPage from './components/EvalPage.jsx';
import UsagePage from './components/UsagePage.jsx';
import PipelinePage from './components/PipelinePage.jsx';
import { pageForPath } from './components/InfoShell.jsx';
import './styles.css';

const PAGES = { '/eval': EvalPage, '/usage': UsagePage, '/pipeline': PipelinePage };
const Page = PAGES[pageForPath(window.location.pathname)] || App;

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Page />
  </React.StrictMode>,
);
