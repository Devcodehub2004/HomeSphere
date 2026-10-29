import { Component, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from 'motion/react'
import {
  ArrowDownToLine, ArrowUpRight, CheckCircle2, ChevronDown,
  Activity, Database, Hexagon, CloudUpload, File, FileText, FolderOpen, HardDrive, Image,
  LayoutGrid, List, LoaderCircle, Music2, Pause, Pencil, Play,
  RefreshCw, RotateCcw, RotateCw, Search, ShieldCheck, Trash2, Video, X, FolderPlus, Link2, Clock,
} from 'lucide-react'
import './App.css'
import FilePreview from './components/FilePreview'
import { FolderDialog, ShareDialog } from './components/CloudDialogs'
import { useDialog } from './hooks/useDialog'
import { authFetch, notifySignedOut } from './authClient'

const CloudScene = lazy(() => import('./components/CloudScene'))
const MAX_SIZE = 25 * 1024 * 1024
const categories = [
  { id: 'all', label: 'All files', icon: FolderOpen },
  { id: 'documents', label: 'Documents', icon: FileText },
  { id: 'images', label: 'Images', icon: Image },
  { id: 'videos', label: 'Videos', icon: Video },
  { id: 'audio', label: 'Audio', icon: Music2 },
  { id: 'other', label: 'Other files', icon: File },
]

function fileKind(file) {
  const extension = file.name.split('.').pop().toLowerCase()
  if (file.content_type.startsWith('image/') || /^(png|jpe?g|gif|webp|avif|svg|heic)$/.test(extension)) return 'images'
  if (file.content_type.startsWith('video/') || /^(mp4|mov|webm|mkv|avi)$/.test(extension)) return 'videos'
  if (file.content_type.startsWith('audio/') || /^(mp3|wav|flac|m4a|ogg)$/.test(extension)) return 'audio'
  if (/^(pdf|docx?|xlsx?|pptx?|txt|md|csv|json|html|css|js|jsx|py|yaml|yml|sql)$/.test(extension)) return 'documents'
  return 'other'
}

function bytes(value) {
  if (!value) return '0 B'
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 3)
  return `${(value / 1024 ** unit).toLocaleString(undefined, { maximumFractionDigits: unit ? 1 : 0 })} ${['B', 'KiB', 'MiB', 'GiB'][unit]}`
}

function date(value) {
  return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

async function errorMessage(response) {
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) return body.detail.map((item) => item.msg).join('. ')
  } catch { /* A proxy error may have no JSON body. */ }
  return `Request failed (${response.status}). Check the API and try again.`
}

async function api(path, options = {}) {
  const response = await authFetch(path, { ...options, signal: options.signal || AbortSignal.timeout(30000) })
  if (!response.ok) throw new Error(await errorMessage(response))
  return response.status === 204 ? null : response.json()
}

function sendUpload(file, onProgress, folderId) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest()
    request.open('POST', folderId ? `/files?folder_id=${folderId}` : '/files')
    request.timeout = 120000
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100))
    }
    request.onerror = () => reject(new Error('Connection lost. Refresh the file list before retrying.'))
    request.ontimeout = () => reject(new Error('Upload timed out. Refresh the file list before retrying.'))
    request.onload = () => {
      if (request.status === 401) notifySignedOut()
      let body
      try { body = JSON.parse(request.responseText) } catch { body = {} }
      if (request.status >= 200 && request.status < 300) resolve(body)
      else reject(new Error(typeof body.detail === 'string' ? body.detail : `Upload failed (${request.status}).`))
    }
    const form = new FormData()
    form.append('file', file)
    request.send(form)
  })
}

class SceneBoundary extends Component {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? this.props.fallback : this.props.children }
}

function FileIcon({ file, large = false }) {
  const kind = fileKind(file)
  const Icon = categories.find((item) => item.id === kind).icon
  const extension = file.name.includes('.') ? file.name.split('.').pop().slice(0, 7).toUpperCase() : 'FILE'
  return <div className={`file-symbol ${kind} ${large ? 'large' : ''}`}><Icon aria-hidden="true" size={large ? 34 : 23} strokeWidth={1.6} />{large && <span>{extension}</span>}</div>
}

function ActionDialog({ modal, onClose, onDone }) {
  const dialog = useRef()
  const [name, setName] = useState(modal.file.name)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const permanent = modal.type === 'permanent'
  const deleting = modal.type === 'delete' || permanent
  useDialog(dialog)
  async function submit(event) {
    event.preventDefault()
    setPending(true)
    setError('')
    try {
      await api(`/files/${modal.file.id}${permanent ? '/permanent' : ''}`, deleting ? { method: 'DELETE' } : {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim() }),
      })
      onDone(permanent ? 'File permanently deleted' : deleting ? 'File moved to recycle bin' : 'File renamed')
    } catch (failure) { setError(`${failure.message} Refresh the list before retrying if the result is uncertain.`) }
    finally { setPending(false) }
  }
  return (
    <dialog ref={dialog} className="action-dialog" aria-labelledby="dialog-title" onCancel={(event) => { event.preventDefault(); if (!pending) onClose() }}>
      <motion.form onSubmit={submit} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
        <div className={`dialog-symbol ${deleting ? 'danger' : ''}`}>{deleting ? <Trash2 aria-hidden="true" /> : <Pencil aria-hidden="true" />}</div>
        <h2 id="dialog-title">{permanent ? 'Permanently delete this file?' : deleting ? 'Move to recycle bin?' : 'Give it a new name'}</h2>
        <p>{permanent ? 'This removes the stored copy permanently. You cannot undo this action.' : deleting ? 'You can restore it later. Existing sharing links will be revoked.' : 'Keep the extension so the file remains easy to recognize.'}</p>
        {deleting ? <div className="delete-file"><FileIcon file={modal.file} /><span>{modal.file.name}</span></div> : <>
          <label htmlFor="filename">File name</label>
          <input id="filename" value={name} onChange={(event) => setName(event.target.value)} required autoFocus disabled={pending} aria-describedby={error ? 'dialog-error' : undefined} />
        </>}
        {error && <p className="inline-error" id="dialog-error" role="alert">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button secondary" onClick={onClose} disabled={pending} autoFocus={deleting}>Cancel</button>
          <button type="submit" className={`button ${deleting ? 'destructive' : 'primary'}`} disabled={pending || (!deleting && !name.trim())}>{pending && <LoaderCircle className="spin" size={17} aria-hidden="true" />}{pending ? 'Saving…' : permanent ? 'Delete forever' : deleting ? 'Move to bin' : 'Save name'}</button>
        </div>
      </motion.form>
    </dialog>
  )
}

export default function App({ owner, onLogout, loggingOut }) {
  const reducedMotion = useReducedMotion()
  const [files, setFiles] = useState([])
  const [trashed, setTrashed] = useState([])
  const [folders, setFolders] = useState([])
  const [mode, setMode] = useState('browse')
  const [trail, setTrail] = useState([])
  const folderId = trail.at(-1)?.id || null
  const [restoring, setRestoring] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [failure, setFailure] = useState('')
  const [category, setCategory] = useState('all')
  const [query, setQuery] = useState('')
  const [view, setView] = useState('grid')
  const [sort, setSort] = useState('newest')
  const [upload, setUpload] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [modal, setModal] = useState(null)
  const [preview, setPreview] = useState(null)
  const [toast, setToast] = useState('')
  const [paused, setPaused] = useState(false)
  const [rotation, setRotation] = useState(-0.25)
  const input = useRef()
  const uploadLock = useRef(false)
  const requestVersion = useRef(0)

  const loadFiles = useCallback(async (signal) => {
    const version = ++requestVersion.current
    setRefreshing(true)
    try {
      const collected = []
      for (let skip = 0; ; skip += 100) {
        const page = await api(`/files?skip=${skip}&limit=100`, { signal })
        collected.push(...page)
        if (page.length < 100) break
      }
      const bin = []
      for (let skip = 0; ; skip += 100) {
        const page = await api(`/files?trashed=true&skip=${skip}&limit=100`, { signal })
        bin.push(...page)
        if (page.length < 100) break
      }
      const children = []
      for (let skip = 0; ; skip += 100) {
        const page = await api(`/folders?parent_id=${folderId || 'root'}&skip=${skip}&limit=100`, { signal })
        children.push(...page)
        if (page.length < 100) break
      }
      if (version === requestVersion.current) { setFiles(collected); setTrashed(bin); setFolders(children); setFailure('') }
    } catch (error) {
      if (!signal?.aborted && version === requestVersion.current) setFailure(`Could not load files. ${error.message}`)
    } finally {
      if (version === requestVersion.current) { setLoading(false); setRefreshing(false) }
    }
  }, [folderId])

  useEffect(() => {
    const controller = new AbortController()
    loadFiles(controller.signal)
    return () => controller.abort()
  }, [loadFiles])
  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(''), 5000)
    return () => clearTimeout(timer)
  }, [toast])

  const counts = useMemo(() => Object.fromEntries(categories.map((item) => [item.id, item.id === 'all' ? files.length : files.filter((file) => fileKind(file) === item.id).length])), [files])
  const totalBytes = files.reduce((sum, file) => sum + file.size_bytes, 0)
  const visible = useMemo(() => {
    let source = mode === 'trash' ? trashed : mode === 'recent' ? files.slice(0, 10) : files
    // Search spans all active folders. Browsing without a query shows this folder only.
    if (mode === 'browse' && !query) source = source.filter((file) => file.folder_id === folderId)
    return source.filter((file) => (category === 'all' || fileKind(file) === category) && file.name.toLowerCase().includes(query.toLowerCase()))
      .sort((a, b) => sort === 'name' ? a.name.localeCompare(b.name) : sort === 'size' ? b.size_bytes - a.size_bytes : new Date(b.created_at) - new Date(a.created_at))
  }, [files, trashed, category, query, sort, mode, folderId])

  async function restore(file) {
    setRestoring(file.id)
    try { await api(`/files/${file.id}/restore`, { method: 'POST' }); await loadFiles(); setToast('File restored to its original folder') }
    catch (error) { setFailure(error.message) }
    finally { setRestoring(null) }
  }
  function openFolder(folder) { setTrail([...trail, folder]); setQuery(''); setCategory('all') }
  function changeMode(next) { setMode(next); setQuery(''); setCategory('all') }
  function openPreview(file) { if (mode !== 'trash') setPreview(file) }

  async function uploadFiles(selected) {
    if (uploadLock.current || !selected.length) return
    uploadLock.current = true
    setFailure('')
    let complete = 0
    const errors = []
    for (const file of Array.from(selected)) {
      if (file.size > MAX_SIZE) { errors.push(`${file.name}: exceeds 25 MiB.`); continue }
      setUpload({ name: file.name, percent: 0 })
      try {
        await sendUpload(file, (percent) => setUpload({ name: file.name, percent }), folderId)
        complete++
      } catch (error) { errors.push(`${file.name}: ${error.message}`) }
    }
    setUpload(null)
    uploadLock.current = false
    if (input.current) input.current.value = ''
    await loadFiles()
    if (errors.length) setFailure(errors.join(' '))
    if (complete) setToast(`${complete} ${complete === 1 ? 'file' : 'files'} uploaded`)
  }

  function chooseFiles() { if (!uploadLock.current && mode !== 'trash') input.current.click() }
  const cloudFallback = <div className="static-cloud"><Hexagon size={160} strokeWidth={0.7} aria-hidden="true" /></div>

  const usage = categories.slice(1).map((item) => ({ ...item, bytes: files.filter((file) => fileKind(file) === item.id).reduce((sum, file) => sum + file.size_bytes, 0) }))
  const latest = files[0]
  const selectedLabel = categories.find((item) => item.id === category).label

  return (
    <MotionConfig reducedMotion="user" transition={{ type: 'spring', stiffness: 320, damping: 30 }}>
      <a className="skip-link" href="#files">Skip to files</a>
      <div className="dashboard-shell">
        <main id="main" className="workspace-main" tabIndex={-1}>
          <header className="topbar">
            <a className="brand" href="#overview"><Hexagon size={28} strokeWidth={1.4} aria-hidden="true" /><span>HOMESPHERE<small>Your personal cloud</small></span></a>
            <nav className="top-nav" aria-label="Workspace navigation"><a href="#overview">Overview</a><span>/</span><a href="#files">File manager</a><span>/</span><a href="#storage">Storage</a></nav>
            <div className="account-controls"><span className="account-name" title={owner.username}>{owner.username}</span><button className="account-logout" onClick={onLogout} disabled={loggingOut || Boolean(upload)}>{loggingOut ? 'Signing out…' : 'Sign out'}</button></div>
          </header>

          <div className="workspace-content">
            <div className="workspace-toolbar"><div className="workspace-location"><HardDrive size={15} aria-hidden="true" /><span>PERSONAL VOLUME</span><strong>01</strong></div><label className="search"><Search size={16} aria-hidden="true" /><span className="sr-only">Search files by name</span><input type="search" aria-label="Search files by name" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') document.getElementById('files').scrollIntoView({ behavior: reducedMotion ? 'instant' : 'smooth' }) }} placeholder="Search your cloud…" /><kbd aria-hidden="true">↵</kbd></label></div>

            <motion.section id="overview" className="overview" aria-labelledby="overview-title" initial={reducedMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }}>
              <div className="overview-topline"><span>YOUR SPACE. YOUR CONTROL.</span><span className="volume-number">HS / 001</span></div>
              <div className="sphere-stage"><SceneBoundary fallback={cloudFallback}><Suspense fallback={cloudFallback}><CloudScene rotation={rotation} paused={paused || reducedMotion} /></Suspense></SceneBoundary></div>
              <div className="hero-copy"><div className="eyebrow">INDEPENDENT BY DESIGN</div><h1 id="overview-title">Cloud<span>STORAGE</span></h1><p>A home for your files.<br />On your server. On your terms.</p><motion.button className="button primary" whileTap={{ scale: 0.97 }} onClick={chooseFiles} disabled={Boolean(upload) || mode === 'trash'}><CloudUpload size={17} aria-hidden="true" />{upload ? 'Uploading…' : 'Upload files'}<ArrowUpRight size={16} aria-hidden="true" /></motion.button><small className="hero-note">Any file type · Up to 25 MiB</small></div>
              <div className="sphere-label"><span>ONE PERSONAL CLOUD</span><p>Everything.<br />In your orbit.</p></div>
              <div className="volume-readout"><span className="readout-label"><Activity size={13} aria-hidden="true" />VOLUME READOUT</span><div><strong>{loading ? '—' : String(files.length).padStart(2, '0')}</strong><span>files in<br />your cloud</span></div><p>{loading ? 'Reading your volume…' : `${bytes(totalBytes)} stored locally`}</p></div>
              <div className="sphere-controls" aria-label="3D storage sphere controls"><button className="icon-button" aria-label="Rotate sphere left" onClick={() => setRotation((value) => value - 0.45)}><RotateCcw size={16} aria-hidden="true" /></button><button className="icon-button" aria-label={paused ? 'Resume sphere movement' : 'Pause sphere movement'} aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused ? <Play size={16} aria-hidden="true" /> : <Pause size={16} aria-hidden="true" />}</button><button className="icon-button" aria-label="Rotate sphere right" onClick={() => setRotation((value) => value + 0.45)}><RotateCw size={16} aria-hidden="true" /></button></div>
              <div className="overview-footer"><span><ShieldCheck size={14} aria-hidden="true" />Your own infrastructure</span><span>MOVE TO EXPLORE <span className="footer-cross">+</span></span></div>
            </motion.section>

            <section id="files" className="files-section" aria-labelledby="files-heading">
              <div className="section-heading"><div><span className="section-kicker">YOUR DIGITAL SPACE</span><h2 id="files-heading" tabIndex={-1}>File manager <span>{loading ? '—' : visible.length}</span></h2></div><div className="file-heading-actions"><button className="icon-button" onClick={() => loadFiles()} disabled={refreshing || Boolean(upload)} aria-label="Refresh files" title="Refresh files"><RefreshCw size={17} className={refreshing ? 'spin' : ''} aria-hidden="true" /></button><div className="view-switch" aria-label="File layout"><button className={view === 'grid' ? 'selected' : ''} aria-label="Grid view" aria-pressed={view === 'grid'} onClick={() => setView('grid')}><LayoutGrid size={17} aria-hidden="true" /></button><button className={view === 'list' ? 'selected' : ''} aria-label="List view" aria-pressed={view === 'list'} onClick={() => setView('list')}><List size={18} aria-hidden="true" /></button></div></div></div>
              <div className="cloud-navigation">
                <nav className="category-tabs" aria-label="Cloud views">
                  <button className={mode === 'browse' ? 'active' : ''} aria-pressed={mode === 'browse'} onClick={() => changeMode('browse')} disabled={Boolean(upload)}><FolderOpen size={16} aria-hidden="true" />Folders</button>
                  <button className={mode === 'recent' ? 'active' : ''} aria-pressed={mode === 'recent'} onClick={() => changeMode('recent')} disabled={Boolean(upload)}><Clock size={16} aria-hidden="true" />Recent uploads</button>
                  <button className={mode === 'trash' ? 'active' : ''} aria-pressed={mode === 'trash'} onClick={() => changeMode('trash')} disabled={Boolean(upload)}><Trash2 size={16} aria-hidden="true" />Recycle bin ({trashed.length})</button>
                </nav>
                {mode === 'browse' && <button className="button secondary" disabled={loading || refreshing || Boolean(upload)} onClick={() => setModal({ type: 'folder' })}><FolderPlus size={16} aria-hidden="true" />New folder</button>}
              </div>
              {mode === 'browse' && <nav className="folder-breadcrumbs" aria-label="Folder location"><button disabled={Boolean(upload)} onClick={() => { setTrail([]); setQuery('') }}>My files</button>{trail.map((folder, index) => <span key={folder.id}> / <button disabled={Boolean(upload)} aria-current={index === trail.length - 1 ? 'page' : undefined} onClick={() => { setTrail(trail.slice(0, index + 1)); setQuery('') }}>{folder.name}</button></span>)}</nav>}
              <p className="cloud-view-note">{mode === 'trash' ? 'Restore files to their original folder or delete them forever. Files in the bin still use storage.' : mode === 'recent' ? `Your ten most recent uploads across all folders. Uploads go to ${trail.at(-1)?.name || 'My files'}.` : query ? 'Searching all folders by file name.' : `Uploads go to ${trail.at(-1)?.name || 'My files'}.`}</p>
              {mode === 'browse' && !loading && !query && <div className="folder-grid">{folders.map((folder) => <button key={folder.id} className="folder-tile" disabled={Boolean(upload) || refreshing} onClick={() => openFolder(folder)}><FolderOpen size={22} aria-hidden="true" /><span>{folder.name}</span><ArrowUpRight size={15} aria-hidden="true" /></button>)}</div>}
              <div className="files-toolbar"><nav className="category-tabs" aria-label="Filter file types">{categories.map(({ id, label }) => <button key={id} aria-pressed={category === id} className={category === id ? 'active' : ''} onClick={() => setCategory(id)}>{label}{id === 'all' && <span>{loading ? '—' : counts.all}</span>}</button>)}</nav><label className="sort-select"><span className="sr-only">Sort files</span><select value={sort} onChange={(event) => setSort(event.target.value)}><option value="newest">Newest first</option><option value="name">Name A–Z</option><option value="size">Largest first</option></select><ChevronDown size={13} aria-hidden="true" /></label></div>
              {category !== 'all' && <p className="filter-note">Showing {selectedLabel.toLowerCase()}<button onClick={() => setCategory('all')}>Clear filter<X size={12} aria-hidden="true" /></button></p>}
              {failure && <div className="error-banner" role="alert"><span>{failure}</span><button className="icon-button" aria-label="Dismiss error" onClick={() => setFailure('')}><X size={18} aria-hidden="true" /></button></div>}
              <AnimatePresence>{upload && <motion.div className="upload-progress" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}><div><LoaderCircle className="spin" size={18} aria-hidden="true" /><strong>{upload.percent === 100 ? 'Saving' : 'Uploading'} {upload.name}</strong><span>{upload.percent}%</span></div><progress value={upload.percent} max={100} aria-label={`Uploading ${upload.name}`} /></motion.div>}</AnimatePresence>
              <div className={`drop-region ${dragging ? 'dragging' : ''}`} onDragOver={(event) => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); if (mode !== 'trash') setDragging(true) } }} onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setDragging(false) }} onDrop={(event) => { event.preventDefault(); setDragging(false); if (mode !== 'trash') uploadFiles(event.dataTransfer.files) }}>
                {dragging && <div className="drop-overlay"><CloudUpload size={40} aria-hidden="true" /><strong>Drop files into your cloud</strong><span>Up to 25 MiB per file</span></div>}
                {loading ? <div className="file-grid" aria-label="Loading files" aria-busy="true">{[1, 2, 3].map((item) => <div className="skeleton-card" key={item}><div /><span /><span /></div>)}</div> : visible.length ? <div className={view === 'grid' ? 'file-grid' : 'file-list'}><AnimatePresence initial={false}>{visible.map((file) => <motion.article key={file.id} layout={reducedMotion ? false : 'position'} className="file-card" onClick={(event) => { if (!event.target.closest('a, button')) openPreview(file) }} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.97 }} transition={{ duration: 0.18 }}><button type="button" className="file-preview file-open file-open-preview" disabled={mode === 'trash'} onClick={() => openPreview(file)} aria-label={`Preview ${file.name}`}><FileIcon file={file} large={view === 'grid'} /><span className="preview-affordance">{mode === 'trash' ? 'IN RECYCLE BIN' : 'OPEN PREVIEW'}<ArrowUpRight size={13} aria-hidden="true" /></span></button><div className="file-info"><h3><button type="button" className="file-open file-open-name" disabled={mode === 'trash'} title={file.name} onClick={() => openPreview(file)} aria-label={`Open ${file.name}`}>{file.name}</button></h3><p><span>{bytes(file.size_bytes)}</span><span className="file-date">{date(file.created_at)}</span></p></div><div className="file-actions">{mode === 'trash' ? <><button className="icon-button" disabled={Boolean(restoring)} onClick={() => restore(file)} aria-label={`Restore ${file.name}`} title="Restore"><RotateCcw size={16} aria-hidden="true" /></button><button className="icon-button delete-button" disabled={Boolean(restoring)} onClick={() => setModal({ type: 'permanent', file })} aria-label={`Permanently delete ${file.name}`} title="Delete forever"><Trash2 size={16} aria-hidden="true" /></button></> : <><a className="icon-button" href={`/files/${file.id}/download`} download={file.name} aria-label={`Download ${file.name}`} title="Download"><ArrowDownToLine size={16} aria-hidden="true" /></a><button className="icon-button" disabled={Boolean(upload)} onClick={() => setModal({ type: 'share', file })} aria-label={`Share ${file.name}`} title="Share"><Link2 size={15} aria-hidden="true" /></button><button className="icon-button" disabled={Boolean(upload)} onClick={() => setModal({ type: 'rename', file })} aria-label={`Rename ${file.name}`} title="Rename"><Pencil size={15} aria-hidden="true" /></button><button className="icon-button delete-button" disabled={Boolean(upload)} onClick={() => setModal({ type: 'delete', file })} aria-label={`Delete ${file.name}`} title="Move to recycle bin"><Trash2 size={15} aria-hidden="true" /></button></>}</div></motion.article>)}</AnimatePresence></div> : <div className="empty-state"><FolderOpen size={30} strokeWidth={1.3} aria-hidden="true" /><h3>{failure ? 'Your cloud is out of reach' : query ? 'No matching files' : mode === 'trash' ? 'Your recycle bin is empty' : mode === 'recent' ? 'No recent uploads' : category === 'all' ? 'Your space starts here.' : `No ${selectedLabel.toLowerCase()} yet`}</h3><p>{failure ? 'Check that the API is running, then refresh your files.' : query ? 'Try another file name or clear your search.' : mode === 'trash' ? 'Files you move to the bin will appear here until you restore or permanently delete them.' : 'Bring your documents, photos and ideas into your own cloud.'}</p>{query ? <button className="button secondary" onClick={() => setQuery('')}>Clear search</button> : failure ? <button className="button secondary" onClick={() => loadFiles()}>Try again</button> : mode !== 'trash' && <button className="button secondary" onClick={chooseFiles} disabled={Boolean(upload)}><CloudUpload size={16} aria-hidden="true" />Choose files<ArrowUpRight size={15} aria-hidden="true" /></button>}</div>}
                {mode !== 'trash' && !loading && visible.length > 0 && <button className="drop-hint" onClick={chooseFiles} disabled={Boolean(upload)}><CloudUpload size={18} aria-hidden="true" /><span>Drop files here or <strong>browse your device</strong></span><small>25 MiB / FILE</small></button>}
              </div>
              <footer className="files-footer"><span><ShieldCheck size={13} aria-hidden="true" />Stored on your own server</span><span>{loading ? 'Reading volume…' : `${files.length} active files · ${bytes(totalBytes)} + ${bytes(trashed.reduce((sum, file) => sum + file.size_bytes, 0))} in bin`}</span></footer>
            </section>
          </div>
        </main>

        <aside id="storage" className="insights-panel" aria-labelledby="storage-heading">
          <header className="insights-header"><Hexagon size={31} strokeWidth={1.5} aria-hidden="true" /><div><span>HOMESPHERE</span><small>Personal cloud storage</small></div><HardDrive size={17} aria-hidden="true" /></header>
          <div className="panel-section-label"><span>VOLUME OVERVIEW</span><span>01 / LOCAL</span></div>
          <section className="volume-card"><div className="volume-card-heading"><span className="volume-icon"><Database size={24} strokeWidth={1.2} aria-hidden="true" /></span><div><h2 id="storage-heading">Cloud<span>STORAGE</span></h2><p>Entirely your own.</p></div></div><div className="volume-total"><strong>{loading ? '—' : bytes(totalBytes)}</strong><span>FILE STORAGE</span></div><div className="type-shortcuts"><button onClick={() => { setCategory('images'); document.getElementById('files').scrollIntoView({ behavior: reducedMotion ? 'instant' : 'smooth' }) }}>Photos</button><button onClick={() => { setCategory('videos'); document.getElementById('files').scrollIntoView({ behavior: reducedMotion ? 'instant' : 'smooth' }) }}>Videos</button><button onClick={() => { setCategory('documents'); document.getElementById('files').scrollIntoView({ behavior: reducedMotion ? 'instant' : 'smooth' }) }}>Documents</button></div></section>
          <section className="file-count-card"><span className="file-count-icon"><FolderOpen size={24} strokeWidth={1.3} aria-hidden="true" /></span><div><span>IN YOUR CLOUD</span><strong>{loading ? '—' : files.length}<small>{files.length === 1 ? 'file' : 'files'}</small></strong></div><ArrowUpRight size={17} aria-hidden="true" /></section>
          <section className="details-section" aria-labelledby="details-heading"><div className="panel-heading"><h3 id="details-heading">Storage details</h3><span>BY FILE TYPE</span></div><div className="usage-list">{usage.map(({ id, label, icon: Icon, bytes: used }) => <button key={id} className={category === id ? 'usage-item active' : 'usage-item'} onClick={() => { setCategory(id); document.getElementById('files').scrollIntoView({ behavior: reducedMotion ? 'instant' : 'smooth' }) }}><span className="usage-item-label"><Icon size={15} aria-hidden="true" /><span>{label}</span><strong>{loading ? '—' : bytes(used)}</strong></span><progress max={totalBytes || 1} value={used} aria-label={`${label} share of stored bytes`} /></button>)}</div><p className="details-note">Based on the files in your cloud.</p></section>
          <section className="recent-section" aria-labelledby="latest-heading"><div className="panel-heading"><h3 id="latest-heading">Latest addition</h3><span>RECENT</span></div>{latest ? <button className="latest-file" onClick={() => setPreview(latest)} aria-label={`Preview latest file ${latest.name}`}><FileIcon file={latest} /><span><strong title={latest.name}>{latest.name}</strong><small>{date(latest.created_at)} · {bytes(latest.size_bytes)}</small></span><ArrowUpRight size={17} aria-hidden="true" /></button> : <p className="panel-empty">{loading ? 'Loading your files…' : 'Your first upload will appear here.'}</p>}</section>
          <div className="volume-bottom"><span>YOUR FILES, YOUR SPACE.</span><strong>{loading ? '—' : bytes(totalBytes)}</strong><p>Total file storage</p><div className="local-volume-status"><HardDrive size={14} aria-hidden="true" /><span>Personal volume</span><span>LOCAL</span></div></div>
        </aside>
      </div>
      <div className="outer-footer"><span>HOMESPHERE / PERSONAL CLOUD</span><span>Built to belong to you.</span></div>
      <input ref={input} type="file" multiple hidden onChange={(event) => uploadFiles(event.target.files)} />
      {preview && <FilePreview key={preview.id} file={preview} onClose={() => setPreview(null)} />}
      {modal?.type === 'folder' && <FolderDialog parentId={folderId} api={api} onClose={() => setModal(null)} onDone={(message) => { setModal(null); setToast(message); loadFiles() }} />}
      {modal?.type === 'share' && <ShareDialog file={modal.file} api={api} onClose={() => setModal(null)} />}
      {modal && !['folder', 'share'].includes(modal.type) && <ActionDialog key={`${modal.type}-${modal.file.id}`} modal={modal} onClose={() => setModal(null)} onDone={(message) => { setModal(null); setToast(message); loadFiles() }} />}
      <div className="toast-region" role="status" aria-live="polite" aria-atomic="true"><AnimatePresence>{toast && <motion.div className="toast" key={toast} initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}><CheckCircle2 size={18} aria-hidden="true" /><span>{toast}</span><button className="icon-button" onClick={() => setToast('')} aria-label="Dismiss notification"><X size={16} aria-hidden="true" /></button></motion.div>}</AnimatePresence></div>
    </MotionConfig>
  )
}
