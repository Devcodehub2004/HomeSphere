import { useEffect, useRef, useState } from 'react'
import { FolderPlus, Link2, LoaderCircle } from 'lucide-react'
import { useDialog } from '../hooks/useDialog'

export function FolderDialog({ parentId, api, onClose, onDone }) {
  const dialog = useRef()
  const [name, setName] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  useDialog(dialog)
  async function submit(event) {
    event.preventDefault(); setPending(true); setError('')
    try {
      await api('/folders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, parent_id: parentId }) })
      onDone('Folder created')
    } catch (failure) { setError(failure.message) }
    finally { setPending(false) }
  }
  return <dialog ref={dialog} className="action-dialog" aria-labelledby="folder-title" onCancel={(event) => { event.preventDefault(); if (!pending) onClose() }}>
    <form onSubmit={submit}><div className="dialog-symbol"><FolderPlus aria-hidden="true" /></div><h2 id="folder-title">Create a folder</h2><p>Organize your files in this location.</p>
      <label htmlFor="folder-name">Folder name</label><input id="folder-name" autoFocus required value={name} disabled={pending} onChange={(event) => setName(event.target.value)} />
      {error && <p className="inline-error" role="alert">{error}</p>}
      <div className="dialog-actions"><button type="button" className="button secondary" disabled={pending} onClick={onClose}>Cancel</button><button className="button primary" disabled={pending || !name.trim()}>{pending ? 'Creating…' : 'Create folder'}</button></div>
    </form></dialog>
}

export function ShareDialog({ file, api, onClose }) {
  const dialog = useRef()
  const [hours, setHours] = useState('24')
  const [shares, setShares] = useState([])
  const [link, setLink] = useState('')
  const [pending, setPending] = useState(true)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [newId, setNewId] = useState(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  const base = `/files/${file.id}/shares`
  useDialog(dialog)
  useEffect(() => {
    const controller = new AbortController()
    api(base, { signal: controller.signal }).then(setShares).catch((failure) => { if (!controller.signal.aborted) setError(failure.message) }).finally(() => { if (!controller.signal.aborted) setPending(false) })
    return () => controller.abort()
  }, [api, base])
  async function perform(action) {
    setPending(true); setError('')
    try { await action(); setShares(await api(base)) }
    catch (failure) { setError(failure.message) }
    finally { setPending(false) }
  }
  return <dialog ref={dialog} className="action-dialog share-dialog" aria-labelledby="share-title" onCancel={(event) => { event.preventDefault(); if (!pending) onClose() }}>
    <form onSubmit={(event) => { event.preventDefault(); perform(async () => {
      const created = await api(base, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expires_in_hours: Number(hours) }) })
      setLink(new URL(created.path, window.location.origin).href); setNewId(created.id); setCopied(false)
    }) }}>
      <div className="dialog-symbol"><Link2 aria-hidden="true" /></div><h2 id="share-title">Share this file</h2><p className="share-filename">{file.name}</p><p>Anyone with the link can download this file until it expires or you revoke it. Copy a new link before closing. Links use this server’s address.</p>
      <label htmlFor="share-expiry">Link expires after</label><select id="share-expiry" value={hours} disabled={pending} onChange={(event) => setHours(event.target.value)}><option value="1">1 hour</option><option value="24">24 hours</option><option value="168">7 days</option></select>
      <button className="button primary" disabled={pending}>{pending ? <LoaderCircle className="spin" size={16} aria-hidden="true" /> : <Link2 size={16} aria-hidden="true" />}Create link</button>
      {link && <div className="share-created"><label htmlFor="share-url">New download link</label><input id="share-url" readOnly value={link} onFocus={(event) => event.target.select()} /><button type="button" className="button secondary" onClick={async () => { try { await navigator.clipboard.writeText(link); setCopied(true) } catch { setError('Select and copy the link above.') } }}>{copied ? 'Copied' : 'Copy link'}</button></div>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      <ul className="share-list" aria-label="Existing share links">{shares.map((share) => {
        const active = !share.revoked_at && new Date(share.expires_at).getTime() > now
        return <li key={share.id}><span>{share.revoked_at ? 'Revoked' : active ? 'Expires' : 'Expired'}<small>{new Date(share.expires_at).toLocaleString()}</small></span>{active && <button type="button" className="button secondary" disabled={pending} onClick={() => perform(async () => { await api(`${base}/${share.id}`, { method: 'DELETE' }); if (newId === share.id) setLink('') })}>Revoke</button>}</li>
      })}</ul>
      <div className="dialog-actions"><button type="button" className="button secondary" disabled={pending} onClick={onClose}>Close</button></div>
    </form></dialog>
}
