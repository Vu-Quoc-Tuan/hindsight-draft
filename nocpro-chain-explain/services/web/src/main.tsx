import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { TopologyPreview } from './TopologyPreview.tsx'

const topologyPreview = import.meta.env.DEV && new URLSearchParams(window.location.search).has('topology-preview')

// Refresh tab favicon to ensure browser doesn't retain old cached icon
try {
  let link = document.querySelector("link[rel~='icon']") as HTMLLinkElement | null
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  link.type = 'image/svg+xml'
  link.href = `/favicon.svg?t=${Date.now()}`
} catch {
  // Ignore in test/SSR environments
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {topologyPreview ? <TopologyPreview /> : <App />}
  </StrictMode>,
)
