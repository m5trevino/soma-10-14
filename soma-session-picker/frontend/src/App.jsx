import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import './App.css'
import './components/FavoritesPanel.css'
import SessionTable from './components/SessionTable'
import FilterBar from './components/FilterBar'
import StatusBar from './components/StatusBar'
import SessionMetaPanel from './components/SessionMetaPanel'

const API = '/api'

// Renders a metadata value that may be a plain string or a
// {label: count} histogram — avoids "Objects are not valid as a React child".
function topLabel(value) {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return String(value[0] ?? '')
  if (typeof value === 'object') {
    const top = Object.entries(value).sort((a, b) => (b[1] || 0) - (a[1] || 0))[0]
    return top ? top[0] : ''
  }
  return String(value)
}

function App() {
  const [sessions, setSessions] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState(new Set())
  const [exporting, setExporting] = useState(false)
  const [exportStatus, setExportStatus] = useState('')
  
  // Favorites — persistent across reloads
  const [favorites, setFavorites] = useState(() => {
    try {
      const stored = localStorage.getItem('soma_favorites')
      return stored ? new Set(JSON.parse(stored)) : new Set()
    } catch { return new Set() }
  })
  
  // Selected favorites for export (separate from the favorites collection)
  const [exportSelected, setExportSelected] = useState(new Set())
  
  const [allFavorites, setAllFavorites] = useState([])  // full session data for favs
  const [showFavoritesPanel, setShowFavoritesPanel] = useState(false)
  const [showStartPanel, setShowStartPanel] = useState(false)
  const [jsonPath, setJsonPath] = useState('')
  const [loadedSessions, setLoadedSessions] = useState([])
  const [loadError, setLoadError] = useState('')
  const [startMode, setStartMode] = useState('all')
  const [pickN, setPickN] = useState(1)
  const [selectFirstN, setSelectFirstN] = useState(0)

  // Current profile
  const [profile, setProfile] = useState(null)
  const [profileError, setProfileError] = useState('')
  const [profileLoading, setProfileLoading] = useState(false)

  // Selected session for detail panel
  const [selectedSessionId, setSelectedSessionId] = useState(null)
  const [sessionMeta, setSessionMeta] = useState(null)
  const [metaLoading, setMetaLoading] = useState(false)
  const [metaError, setMetaError] = useState('')
  const [panelOpen, setPanelOpen] = useState(true)

  // Filter state
  const [search, setSearch] = useState('')
  const [domain, setDomain] = useState('')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [minScore, setMinScore] = useState(0)
  const [sort, setSort] = useState('score')
  const [order, setOrder] = useState('desc')
  const [limit, setLimit] = useState(500)
  const [minSets, setMinSets] = useState(0)

  // Filter options
  const [providers, setProviders] = useState([])
  const [domains, setDomains] = useState([])
  const [models, setModels] = useState([])
  const [scoreRange, setScoreRange] = useState({ min: 0, max: 0 })
  const [filterOptionsLoaded, setFilterOptionsLoaded] = useState(false)

  // Persist favorites
  useEffect(() => {
    localStorage.setItem('soma_favorites', JSON.stringify([...favorites]))
  }, [favorites])

  // Fetch filter options (DB only — fast)
  useEffect(() => {
    fetch(`${API}/sessions/counts`)
      .then((r) => r.json())
      .then((d) => {
        setProviders(d.providers || [])
        setDomains(d.domains || [])
        setModels(d.models || [])
        setScoreRange(d.score_range || { min: 0, max: 0 })
        setFilterOptionsLoaded(true)
      })
      .catch(() => setFilterOptionsLoaded(true))
  }, [])

  // Fetch current TurnKey profile
  useEffect(() => {
    setProfileLoading(true)
    fetch(`${API}/profile`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((d) => {
        setProfile(d)
        setProfileError('')
      })
      .catch((err) => {
        setProfile(null)
        setProfileError(err.message || 'Profile not available')
      })
      .finally(() => setProfileLoading(false))
  }, [])

  const fetchSessions = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams({
        search: search || '',
        domain: domain || '',
        provider: provider || '',
        model: model || '',
        min_score: String(minScore),
        sort: sort,
        order: order,
        limit: String(limit),
        min_sets: String(minSets),
      })
      const res = await fetch(`${API}/sessions?${params}`)
      const data = await res.json()
      setSessions(data.sessions || [])
      setTotal(data.total || 0)
    } catch (err) {
      console.error('Failed to fetch sessions:', err)
    } finally {
      setLoading(false)
    }
  }, [search, domain, provider, model, minScore, sort, order, limit, minSets])

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  // Fetch metadata when a session is selected
  const fetchSessionMeta = useCallback(async (sessionId) => {
    if (!sessionId) {
      setSessionMeta(null)
      setMetaError('')
      return
    }
    setMetaLoading(true)
    setMetaError('')
    try {
      const res = await fetch(`${API}/session/${encodeURIComponent(sessionId)}/metadata`)
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}))
        throw new Error(errData.error || `HTTP ${res.status}`)
      }
      const data = await res.json()
      setSessionMeta(data)
    } catch (err) {
      setMetaError(err.message)
      setSessionMeta(null)
    } finally {
      setMetaLoading(false)
    }
  }, [])

  // Selection management
  const toggleSelect = useCallback((sessionId) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(sessionId)) next.delete(sessionId)
      else next.add(sessionId)
      return next
    })
  }, [])

  const toggleAll = useCallback(() => {
    if (selected.size === sessions.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(sessions.map((s) => s.session_id)))
    }
  }, [sessions])

  // Favorites — add selected to favorites
  const addSelectedToFavorites = useCallback(() => {
    if (selected.size === 0) return
    setFavorites((prev) => {
      const next = new Set(prev)
      selected.forEach(id => next.add(id))
      return next
    })
    setExportStatus(`Added ${selected.size} to favorites (${favorites.size + selected.size} total)`)
  }, [selected, favorites.size])

  // Favorites — remove from favorites
  const removeFavorite = useCallback((sessionId) => {
    setFavorites((prev) => {
      const next = new Set(prev)
      next.delete(sessionId)
      return next
    })
  }, [])

  // Toggle favorite star on a session row
  const toggleFavorite = useCallback((sessionId) => {
    setFavorites((prev) => {
      const next = new Set(prev)
      if (next.has(sessionId)) next.delete(sessionId)
      else next.add(sessionId)
      return next
    })
  }, [])

  // Favorites — load full data for favorites
  const loadFavoritesData = useCallback(async () => {
    const favList = []
    const favIds = Array.from(favorites)
    if (favIds.length === 0) {
      setAllFavorites([])
      return
    }
    // Fetch metadata for each favorite (lazy-load from disk)
    const promises = favIds.map(async (sid) => {
      try {
        const res = await fetch(`${API}/session/${encodeURIComponent(sid)}/metadata`)
        if (res.ok) {
          const data = await res.json()
          favList.push({ ...data, _session_id: sid })
        }
      } catch (e) {
        console.error('Failed to load favorite:', sid, e)
      }
    })
    await Promise.all(promises)
    setAllFavorites(favList)
  }, [favorites])

  // Load sessions from a JSON file
  const loadSessions = useCallback(async () => {
    if (!jsonPath.trim()) {
      setLoadError('Enter a JSON file path first')
      setLoadedSessions([])
      return
    }
    setLoadError('')
    try {
      const res = await fetch(`${API}/sessions/load?path=${encodeURIComponent(jsonPath.trim())}`)
      const data = await res.json()
      if (!res.ok || data.error) {
        setLoadError(data.error || `HTTP ${res.status}`)
        setLoadedSessions([])
        return
      }
      setLoadedSessions(data.sessions || [])
    } catch (err) {
      setLoadError(err.message || 'Failed to load sessions')
      setLoadedSessions([])
    }
  }, [jsonPath])

  // Launch — POST the start config to /api/launch
  const launchHandler = useCallback(async () => {
    if (!jsonPath.trim()) {
      setExportStatus('Enter a JSON file path first')
      return
    }
    try {
      const res = await fetch(`${API}/launch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          json_path: jsonPath.trim(),
          mode: startMode,
          count: startMode === 'one' ? 1 : startMode === 'few' ? pickN : undefined,
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        throw new Error(data.error || `HTTP ${res.status}`)
      }
      setExportStatus('✓ Launch submitted')
      setShowStartPanel(false)
    } catch (err) {
      setExportStatus(err.message || 'Launch failed')
    }
  }, [jsonPath, startMode, pickN])

  // Load favorites data when panel opens
  useEffect(() => {
    if (showFavoritesPanel) {
      loadFavoritesData()
    } else {
      setAllFavorites([])
      setExportSelected(new Set())
    }
  }, [showFavoritesPanel, loadFavoritesData])

  // Favorites — toggle individual favorite for export
  const toggleExportFavorite = useCallback((sessionId) => {
    setExportSelected((prev) => {
      const next = new Set(prev)
      if (next.has(sessionId)) next.delete(sessionId)
      else next.add(sessionId)
      return next
    })
  }, [])

  // Favorites — select all / none for export
  const toggleAllExport = useCallback(() => {
    if (exportSelected.size === allFavorites.length) {
      setExportSelected(new Set())
    } else {
      setExportSelected(new Set(allFavorites.map((f) => f.session_id || f._session_id)))
    }
  }, [allFavorites, exportSelected])

  // Favorites — export as lean JSON
  const exportFavorites = useCallback(async () => {
    if (favorites.size === 0) {
      setExportStatus('No favorites to export')
      return
    }
    setExporting(true)
    setExportStatus('Loading favorites metadata...')
    
    const favoritesList = []
    for (const fav of allFavorites) {
      if (!fav.error) {
        const sid = fav.session_id || fav._session_id
        // Only include favorites that are checked for export
        if (exportSelected.size === 0 || exportSelected.has(sid)) {
          favoritesList.push({
            session_id: fav.session_id,
            provider: fav.provider || fav._session_id?.split('/')?.pop() || '',
            total_sets: fav.total_sets || 0,
            total_session_chars: fav.total_session_chars || 0,
            file_count: fav.file_count || 0,
            anchors: fav.anchors || [],
            tool_calls: fav.tool_calls || [],
            metadata: fav.metadata || {},
            json_file_list: fav.json_file_list || [],
          })
        }
      }
    }

    // Write queue file with only selected session IDs
    const selectedIds = Array.from(exportSelected) || Array.from(favorites)
    const queueData = {
      selected: selectedIds,
      count: selectedIds.length,
      timestamp: Date.now(),
    }
    try {
      await fetch(`${API}/select`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(queueData),
      })
    } catch (e) {
      console.error('Failed to update queue:', e)
    }

    // Download metadata JSON
    const metadataBlob = new Blob(
      [JSON.stringify(favoritesList, null, 2)],
      { type: 'application/json' }
    )
    const metaUrl = URL.createObjectURL(metadataBlob)
    const a = document.createElement('a')
    a.href = metaUrl
    a.download = `soma_favorites_${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(metaUrl)
    setExportStatus(`✓ Exported ${favoritesList.length} favorites to JSON`)
    setExporting(false)
  }, [favorites, allFavorites, exportSelected])

  // When a row is clicked, show metadata
  const handleRowClick = useCallback((sessionId) => {
    setSelectedSessionId((prev) => {
      if (prev === sessionId) {
        setPanelOpen(false)
        return null
      }
      setPanelOpen(true)
      fetchSessionMeta(sessionId)
      return sessionId
    })
  }, [fetchSessionMeta])

  const displayedSessions = useMemo(() => sessions, [sessions])

  const filterBarProps = {
    search, setSearch,
    domain, setDomain,
    provider, setProvider,
    model, setModel,
    minScore, setMinScore,
    sort, setSort,
    order, setOrder,
    limit, setLimit,
    minSets, setMinSets,
    providers, domains, models,
    scoreRange, filterOptionsLoaded,
    onRefresh: fetchSessions,
  }

  return (
    <div className="app">
      <header className="header">
        <h1>Soma Session Picker</h1>
        <div className="header-actions">
          <button
            className="btn-start"
            onClick={() => setShowStartPanel(!showStartPanel)}
          >
            ▶ Start
          </button>
          <button
            className="btn-favorites"
            onClick={() => {
              setShowFavoritesPanel(!showFavoritesPanel)
              if (showFavoritesPanel) {
                setPanelOpen(true)
              }
            }}
            style={{ background: showFavoritesPanel ? '#f59e0b' : '#374151' }}
          >
            {showFavoritesPanel ? '✕ Close Favorites' : `★ Favorites (${favorites.size})`}
          </button>
          {selected.size > 0 && (
            <button
              className="btn-add-fav"
              onClick={addSelectedToFavorites}
              title={`Add ${selected.size} selected sessions to favorites`}
            >
              + Add {selected.size} to Favorites
            </button>
          )}
          {showFavoritesPanel && (
            <button
              className="btn-export-fav"
              onClick={exportFavorites}
              disabled={exporting || favorites.size === 0}
            >
              {exporting ? 'Exporting...' : `Export ${favorites.size} Favorites`}
            </button>
          )}
        </div>
      </header>

      {/* Start Panel — fixed overlay */}
      {showStartPanel && (
        <div className="start-panel-overlay">
          <div className="start-panel">
            <div className="start-panel-header">
              <h2>Start Run</h2>
              <button className="start-panel-close" onClick={() => setShowStartPanel(false)} title="Close panel">
                ✕
              </button>
            </div>
            <div className="start-panel-body">
              {/* Current Profile Section */}
              <div className="start-field profile-section">
                <label>Current Profile</label>
                {profileLoading ? (
                  <div className="profile-loading">Loading profile…</div>
                ) : profileError ? (
                  <div className="profile-error" title={profileError}>
                    ⚠ {profileError}
                  </div>
                ) : profile ? (
                  <>
                    <div className="profile-name">{profile.name || 'Unnamed'}</div>
                    <div className="profile-models">
                      {profile.models.map((m, i) => (
                        <div key={i} className="profile-model-row">
                          <span className="profile-model-id">{m.modelId}</span>
                          <span className="profile-model-provider">{m.provider}</span>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
              </div>
              {/* End Profile Section */}

              <div className="start-field">
                <label htmlFor="json-path">JSON file path</label>
                <input
                  id="json-path"
                  type="text"
                  placeholder="/path/to/soma_favorites.json"
                  value={jsonPath}
                  onChange={(e) => setJsonPath(e.target.value)}
                />
                <div style={{ marginTop: '8px' }}>
                  <button
                    className="btn-load-sessions"
                    onClick={loadSessions}
                    disabled={!jsonPath.trim()}
                  >
                    Load Sessions
                  </button>
                </div>
              </div>
              {loadError && (
                <div className="start-field">
                  <div style={{ color: '#f85149', fontSize: '13px', padding: '8px 12px', background: '#2d1616', borderRadius: '6px', border: '1px solid #f8514933' }}>
                    {loadError}
                  </div>
                </div>
              )}
              {loadedSessions.length > 0 && (
                <div className="start-field start-sessions-list">
                  <div className="start-sessions-list-header">
                    <label>Sessions ({loadedSessions.length})</label>
                    <span className="start-selected-count">{selected.size} selected</span>
                  </div>
                  <div className="start-sessions-list-controls">
                    <button
                      className="btn-select-all"
                      onClick={() => setSelected(new Set(loadedSessions.map((s) => s.session_id)))}
                    >
                      Select All
                    </button>
                    <button
                      className="btn-select-none"
                      onClick={() => setSelected(new Set())}
                    >
                      Select None
                    </button>
                    <div className="select-first-n">
                      <input
                        type="number"
                        min={0}
                        max={loadedSessions.length}
                        value={selectFirstN}
                        onChange={(e) => setSelectFirstN(Math.min(loadedSessions.length, Math.max(0, Number(e.target.value) || 0)))}
                        placeholder="First N"
                      />
                      <button
                        className="btn-select-first-n"
                        onClick={() => {
                          const n = Math.min(loadedSessions.length, Math.max(0, selectFirstN))
                          const firstN = new Set(loadedSessions.slice(0, n).map((s) => s.session_id))
                          setSelected(firstN)
                        }}
                      >
                        Check first N
                      </button>
                    </div>
                  </div>
                  <div className="start-sessions-list-body">
                    {loadedSessions.map((s) => (
                      <label key={s.session_id} className="start-session-row">
                        <input
                          type="checkbox"
                          checked={selected.has(s.session_id)}
                          onChange={() => toggleSelect(s.session_id)}
                        />
                        <span className="start-session-id">{s.session_id}</span>
                      </label>
                    ))}
                  </div>
                </div>
              )}
              <div className="start-field">
                <label>Run mode</label>
                <div className="radio-group">
                  <label className="radio-label">
                    <input
                      type="radio"
                      name="startMode"
                      value="all"
                      checked={startMode === 'all'}
                      onChange={(e) => setStartMode(e.target.value)}
                    />
                    All sessions
                  </label>
                  <label className="radio-label">
                    <input
                      type="radio"
                      name="startMode"
                      value="one"
                      checked={startMode === 'one'}
                      onChange={(e) => setStartMode(e.target.value)}
                    />
                    Just one
                  </label>
                  <label className="radio-label">
                    <input
                      type="radio"
                      name="startMode"
                      value="few"
                      checked={startMode === 'few'}
                      onChange={(e) => setStartMode(e.target.value)}
                    />
                    Pick N (1-3)
                  </label>
                </div>
              </div>
              <div className="start-field">
                <label htmlFor="pick-n" className={startMode === 'few' ? '' : 'disabled-label'}>
                  Number of sessions
                </label>
                <input
                  id="pick-n"
                  type="number"
                  min={1}
                  max={3}
                  value={pickN}
                  onChange={(e) => setPickN(Math.min(3, Math.max(1, Number(e.target.value) || 1)))}
                  disabled={startMode !== 'few'}
                />
              </div>
              <div className="start-field">
                <button
                  className="btn-launch"
                  onClick={() => {
                    if (!jsonPath.trim()) {
                      setExportStatus('Enter a JSON file path first')
                      return
                    }
                    launchHandler()
                  }}
                  disabled={!jsonPath.trim()}
                >
                  ▶ Launch
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      <FilterBar {...filterBarProps} />

      <div className="main-layout">
        <main className="main">
          <SessionTable
            sessions={displayedSessions}
            selected={selected}
            favorites={favorites}
            loading={loading}
            onToggleSelect={toggleSelect}
            onToggleAll={() => setSelected(selected.size === sessions.length ? new Set() : new Set(sessions.map(s => s.session_id)))}
            onToggleFavorite={toggleFavorite}
            onRowClick={handleRowClick}
            activeRowId={selectedSessionId}
          />
        </main>

        {/* Favorites panel — left sidebar */}
        {showFavoritesPanel && (
          <aside className="favorites-panel">
            <div className="favorites-panel-header">
              <span>Favorites ({allFavorites.length})</span>
              <button className="favorites-panel-close" onClick={() => setShowFavoritesPanel(false)} title="Close panel">✕</button>
            </div>
            {allFavorites.length > 0 && (
              <div className="favorites-panel-controls">
                <button
                  className="btn-select-all"
                  onClick={toggleAllExport}
                >
                  {exportSelected.size === allFavorites.length ? 'Select None' : 'Select All'}
                </button>
                {exportSelected.size > 0 && (
                  <span className="fav-selected-count">
                    {exportSelected.size} selected for export
                  </span>
                )}
              </div>
            )}
            <div className="favorites-panel-body">
              {allFavorites.length === 0 ? (
                <p className="fav-empty">No favorites yet. Select sessions and click "Add to Favorites".</p>
              ) : (
                <div className="favorites-list">
                  {allFavorites.map((fav, i) => {
                    const sid = fav.session_id || fav._session_id
                    const checked = exportSelected.has(sid)
                    return (
                      <div key={i} className={`fav-item ${checked ? 'fav-item-checked' : ''}`}>
                        <label className="fav-item-checkbox">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleExportFavorite(sid)}
                          />
                          <span className="fav-item-id">{sid?.split('/').pop() || sid}</span>
                        </label>
                        <div className="fav-item-meta">
                          {fav.metadata?.domain && <span className="fav-badge">{topLabel(fav.metadata.domain)}</span>}
                          {fav.metadata?.sentiment && <span className="fav-badge fav-sentiment">{topLabel(fav.metadata.sentiment)}</span>}
                        </div>
                        <button
                          className="fav-remove-btn"
                          onClick={() => {
                            if (sid) {
                              removeFavorite(sid)
                              setExportSelected(prev => { const n = new Set(prev); n.delete(sid); return n })
                            }
                          }}
                          title="Remove from favorites"
                        >
                          ✕
                        </button>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </aside>
        )}

        {/* Metadata detail panel — right sidebar */}
        {panelOpen && (
          <aside className="meta-panel">
            <div className="meta-panel-header">
              <span>Session Details</span>
              <button className="meta-panel-close" onClick={() => setPanelOpen(false)} title="Close panel">✕</button>
            </div>
            <SessionMetaPanel
              sessionId={selectedSessionId}
              metadata={sessionMeta}
              loading={metaLoading}
              error={metaError}
            />
          </aside>
        )}
      </div>

      <StatusBar
        total={total}
        filtered={displayedSessions.length}
        selected={selected.size}
        favoritesCount={favorites.size}
        loading={loading}
        exportStatus={exportStatus}
      />
    </div>
  )
}

export default App
