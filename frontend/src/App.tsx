import { useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { api } from './lib/api'
import { applyUi, useStore } from './lib/store'
import History from './pages/History'
import RunPage from './pages/RunPage'
import SettingsPage from './pages/Settings'
import Start from './pages/Start'

export default function App() {
  const setSettings = useStore((s) => s.setSettings)
  const settings = useStore((s) => s.settings)

  useEffect(() => {
    api.settings().then((r) => setSettings(r.settings, r.ollama_models)).catch(() => {})
  }, [setSettings])
  useEffect(() => applyUi(settings), [settings])

  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Start />} />
          <Route path="/runs" element={<History />} />
          <Route path="/runs/:runId" element={<RunPage />} />
          <Route path="/runs/:runId/:tab" element={<RunPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
