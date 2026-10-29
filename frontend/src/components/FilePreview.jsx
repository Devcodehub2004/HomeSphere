import { useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { ArrowDownToLine, FileSearch, FileText, LoaderCircle, X } from 'lucide-react'
import './FilePreview.css'
import { authFetch } from '../authClient'

const TEXT_LIMIT = 1024 * 1024
const PREVIEW_LIMIT = 25 * 1024 * 1024
const TEXT_EXTENSIONS = /^(txt|md|csv|tsv|json|xml|svg|html?|css|scss|less|[cm]?js|jsx|ts|tsx|py|yaml|yml|sql|sh|bash|ini|conf|log|toml|env|rs|go|java|c|cpp|h|rb)$/
const MEDIA_TYPES = {
  mp3: 'audio/mpeg', wav: 'audio/wav', ogg: 'audio/ogg', oga: 'audio/ogg',
  m4a: 'audio/mp4', aac: 'audio/aac', flac: 'audio/flac',
  mp4: 'video/mp4', m4v: 'video/mp4', webm: 'video/webm', ogv: 'video/ogg', mov: 'video/quicktime',
}

function size(value) {
  return value >= 1024 * 1024 ? `${(value / 1024 / 1024).toFixed(1)} MiB` : value >= 1024 ? `${(value / 1024).toFixed(1)} KiB` : `${value} B`
}

export function detectPreview(header, file) {
  const ascii = (start, length) => String.fromCharCode(...header.slice(start, start + length))
  // Raster signatures and a fixed MIME type prevent HTML/SVG execution through image previews.
  if (header[0] === 0xff && header[1] === 0xd8 && header[2] === 0xff) return { kind: 'image', mime: 'image/jpeg' }
  if ([137, 80, 78, 71, 13, 10, 26, 10].every((byte, index) => header[index] === byte)) return { kind: 'image', mime: 'image/png' }
  if (/^GIF8[79]a$/.test(ascii(0, 6))) return { kind: 'image', mime: 'image/gif' }
  if (ascii(0, 4) === 'RIFF' && ascii(8, 4) === 'WEBP') return { kind: 'image', mime: 'image/webp' }
  if (ascii(4, 4) === 'ftyp' && ['avif', 'avis'].includes(ascii(8, 4))) return { kind: 'image', mime: 'image/avif' }
  if (ascii(0, 5) === '%PDF-') return { kind: 'pdf', mime: 'application/pdf' }
  const extension = file.name.includes('.') ? file.name.split('.').pop().toLowerCase() : ''
  const mime = MEDIA_TYPES[extension]
  if (mime) return { kind: mime.startsWith('audio/') ? 'audio' : 'video', mime }
  if (TEXT_EXTENSIONS.test(extension) || file.content_type.startsWith('text/')) return { kind: 'text', mime: 'text/plain' }
  return { kind: 'unsupported' }
}

export default function FilePreview({ file, onClose }) {
  const dialog = useRef()
  const [content, setContent] = useState({ kind: 'loading' })
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (!dialog.current.open) dialog.current.showModal()
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(new Error('Preview timed out. Try again or download the file.')), 30000)
    let disposed = false
    let objectURL
    async function load() {
      setContent({ kind: 'loading' })
      setError('')
      try {
        if (file.size_bytes > PREVIEW_LIMIT) { setContent({ kind: 'unsupported', large: true }); return }
        const response = await authFetch(`/files/${file.id}/download`, { signal: controller.signal })
        if (!response.ok) {
          let detail = `Preview unavailable (${response.status}).`
          try { const body = await response.json(); if (typeof body.detail === 'string') detail = body.detail } catch { /* Plain proxy errors. */ }
          throw new Error(detail)
        }
        const blob = await response.blob()
        if (disposed) return
        if (blob.size > PREVIEW_LIMIT) { setContent({ kind: 'unsupported', large: true }); return }
        const header = new Uint8Array(await blob.slice(0, 32).arrayBuffer())
        const type = detectPreview(header, file)
        if (type.kind === 'text') {
          const buffer = new Uint8Array(await blob.slice(0, TEXT_LIMIT).arrayBuffer())
          if (disposed) return
          if (buffer.includes(0)) { setContent({ kind: 'unsupported' }); return }
          let text
          try { text = new TextDecoder('utf-8', { fatal: true }).decode(buffer, { stream: blob.size > TEXT_LIMIT }) }
          catch { setContent({ kind: 'unsupported' }); return }
          setContent({ kind: 'text', text, truncated: blob.size > TEXT_LIMIT })
        } else if (type.kind === 'unsupported') {
          if (!disposed) setContent(type)
        } else {
          if (disposed) return
          // The download route stays attachment-only. Create a short-lived, typed local preview.
          objectURL = URL.createObjectURL(new Blob([blob], { type: type.mime }))
          setContent({ ...type, url: objectURL })
        }
      } catch (failure) {
        if (!disposed) setError(controller.signal.aborted ? 'Preview timed out. Try again or download the file.' : failure.message)
      } finally { clearTimeout(timeout) }
    }
    load()
    return () => { disposed = true; controller.abort(); clearTimeout(timeout); if (objectURL) URL.revokeObjectURL(objectURL) }
  }, [file, attempt])

  const mediaError = () => setError('Your browser could not display this format. Download the file to open it with another app.')
  return (
    <dialog ref={dialog} className="preview-dialog" aria-labelledby="preview-title" onCancel={(event) => { event.preventDefault(); onClose() }}>
      <motion.div className="preview-shell" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        <header className="preview-header">
          <span className="preview-heading-icon"><FileText size={23} aria-hidden="true" /></span>
          <div className="preview-heading"><h2 id="preview-title">{file.name}</h2><p>File preview <span>·</span> {size(file.size_bytes)}</p></div>
          <a className="button secondary preview-download" aria-label={`Download ${file.name}`} href={`/files/${file.id}/download`} download={file.name}><ArrowDownToLine size={17} aria-hidden="true" /><span>Download</span></a>
          <button className="icon-button preview-close" onClick={onClose} aria-label="Close file preview" autoFocus><X size={22} aria-hidden="true" /></button>
        </header>
        <div className={`preview-content preview-kind-${content.kind}`} aria-busy={content.kind === 'loading' && !error}>
          {error ? <div className="preview-message" role="alert"><FileSearch size={38} aria-hidden="true" /><h3>Could not open preview</h3><p>{error}</p><button className="button secondary" onClick={() => setAttempt((value) => value + 1)}>Try again</button></div>
            : content.kind === 'loading' ? <div className="preview-message" role="status"><LoaderCircle size={30} className="spin" aria-hidden="true" /><p>Opening your file…</p></div>
            : content.kind === 'image' ? <img className="preview-image" src={content.url} alt={file.name} onError={mediaError} />
            : content.kind === 'pdf' ? <iframe className="preview-pdf" src={content.url} title={`PDF preview of ${file.name}`} referrerPolicy="no-referrer" />
            : content.kind === 'text' ? <div className="preview-text-wrap">{content.truncated && <p className="preview-notice">Showing the first 1 MiB. Download to read the complete file.</p>}<pre className="preview-text" tabIndex={0} aria-label={`Text contents of ${file.name}`}>{content.text || '(Empty file)'}</pre></div>
            : content.kind === 'audio' ? <div className="preview-media-wrap"><div className="audio-art"><FileText size={55} aria-hidden="true" /></div><p>{file.name}</p><audio controls preload="metadata" src={content.url} aria-label={`Play ${file.name}`} onError={mediaError}>Your browser does not support audio playback.</audio></div>
            : content.kind === 'video' ? <video className="preview-video" controls playsInline preload="metadata" src={content.url} aria-label={`Play ${file.name}`} onError={mediaError}>Your browser does not support video playback.</video>
            : <div className="preview-message"><FileSearch size={42} aria-hidden="true" /><h3>{content.large ? 'This file is too large to preview' : 'No preview for this format yet'}</h3><p>{content.large ? 'Previews support files up to 25 MiB.' : 'You can preview images, PDFs, UTF-8 text, and browser-supported audio and video. Office files and archives can be downloaded.'}</p><a className="button primary" href={`/files/${file.id}/download`} download={file.name}><ArrowDownToLine size={17} aria-hidden="true" />Download file</a></div>}
        </div>
        <footer className="preview-footer"><span>Uploaded {new Date(file.created_at).toLocaleString()}</span><span>Esc to close</span></footer>
      </motion.div>
    </dialog>
  )
}
