import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { TopologyPreview } from './TopologyPreview.tsx'

const topologyPreview = import.meta.env.DEV && new URLSearchParams(window.location.search).has('topology-preview')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {topologyPreview ? <TopologyPreview /> : <App />}
  </StrictMode>,
)
