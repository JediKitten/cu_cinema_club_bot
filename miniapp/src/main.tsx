import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { watchForUpdates } from './legacy/freshness'
import { initTelegram } from './lib/tg'
import './index.css'
import './legacy/legacy.css'

initTelegram()
watchForUpdates()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
