import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import PdfPreview from './PdfPreview';
import './style.css';

const labels = {
  personal_information: 'Personal information', full_name: 'Full name', emails: 'Email',
  phones: 'Phone', linkedin_url: 'LinkedIn', portfolio_url: 'Portfolio',
  work_experience: 'Work experience', field_of_study: 'Field of study',
  raw_name: 'Skill', is_current: 'Current position',
};
const label = key => labels[key] || key.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
const hidden = new Set(['schema_version', 'evidence', 'normalized_name', 'extraction_warnings']);
const finished = status => ['complete', 'failed'].includes(status);
const present = value => value !== null && value !== undefined && value !== '' &&
  (Array.isArray(value) ? value.some(present) : typeof value === 'object'
    ? Object.entries(value).some(([key, item]) => !hidden.has(key) && present(item))
    : value !== false);

async function responseJson(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'The request could not be completed.');
  return data;
}

function Fields({ value }) {
  if (Array.isArray(value)) {
    if (!value.length) return <p className="missing">Not provided</p>;
    if (value.every(item => item && typeof item === 'object' && item.raw_name)) {
      return <div className="chips">{value.map((item, index) => <span key={index}>{item.raw_name}</span>)}</div>;
    }
    if (value.every(item => typeof item !== 'object')) {
      return <div className="chips">{value.map((item, index) => <span key={index}>{String(item)}</span>)}</div>;
    }
    return <div className="records">{value.map((item, index) => <div className="record" key={index}><Fields value={item} /></div>)}</div>;
  }
  if (value && typeof value === 'object') {
    return <dl>{Object.entries(value).filter(([key, item]) => !hidden.has(key) && present(item)).map(([key, item]) =>
      <div className="field" key={key}><dt>{label(key)}</dt><dd><Fields value={item} /></dd></div>)}</dl>;
  }
  return <span>{typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value ?? 'Not provided')}</span>;
}

function Status({ value }) {
  return <span className={`status status-${value}`}><i />{label(value)}</span>;
}

function Results({ job, busy, onDownload }) {
  if (!job?.profile) {
    return <div className="empty">
      <div className={`spark-icon ${busy ? 'pulse' : ''}`}>✦</div>
      <h3>{busy ? 'Reading your CV…' : job?.status === 'failed' ? 'Extraction failed' : 'Structured results appear here'}</h3>
      <p>{job?.error || (busy ? 'The reader and extraction model are processing the document.' : 'Upload a CV or select a completed file from the sidebar.')}</p>
    </div>;
  }

  return <>
    <div className="result-actions"><Status value={job.status} /><button className="text-button" onClick={onDownload}>Export JSON ↓</button></div>
    {Object.entries(job.profile).filter(([key]) => !hidden.has(key)).map(([key, value]) =>
      <section className="result-section" key={key}>
        <h3>{label(key)}{Array.isArray(value) && <span className="count">{value.length}</span>}</h3>
        {present(value) ? <Fields value={value} /> : <p className="missing">Not provided / not extracted</p>}
      </section>)}
  </>;
}

function App() {
  const [view, setView] = useState('upload');
  const [file, setFile] = useState(null);
  const [text, setText] = useState('');
  const [job, setJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);
  const [connected, setConnected] = useState(false);
  const input = useRef();
  const busy = sending || (job && !finished(job.status));

  const loadJobs = useCallback(async () => {
    try {
      const items = await fetch('/api/extractions').then(responseJson);
      setJobs(items);
    } catch { /* Health state already communicates connection errors. */ }
  }, []);

  useEffect(() => {
    fetch('/api/health').then(responseJson).then(() => {
      setConnected(true);
      loadJobs();
    }).catch(() => setConnected(false));
  }, [loadJobs]);

  useEffect(() => {
    let active = true;
    setText('');
    if (file && !file.name.toLowerCase().endsWith('.pdf')) {
      file.text().then(value => { if (active) setText(value); });
    } else if (!file && job && !job.filename.toLowerCase().endsWith('.pdf')) {
      fetch(job.source_url).then(response => response.text()).then(value => { if (active) setText(value); }).catch(() => { });
    }
    return () => { active = false; };
  }, [file, job?.id]);

  useEffect(() => {
    if (!job || finished(job.status)) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const next = await fetch(`/api/extractions/${job.id}`, { signal: controller.signal }).then(responseJson);
        setJob(next);
        setJobs(current => [next, ...current.filter(item => item.id !== next.id)]);
        setError('');
      } catch (problem) {
        if (problem.name !== 'AbortError') setError(problem.message);
      }
    }, 1500);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [job]);

  function choose(selected) {
    if (!selected || busy) return;
    if (!/\.(pdf|txt|md)$/i.test(selected.name)) return setError('Choose a PDF, TXT or Markdown file.');
    if (!selected.size || selected.size > 25 * 1024 * 1024) return setError('Choose a non-empty file up to 25 MB.');
    setFile(selected);
    setJob(null);
    setError('');
    setView('upload');
  }

  function newExtraction() {
    setFile(null);
    setText('');
    setJob(null);
    setError('');
    setView('upload');
  }

  function openJob(selected) {
    setFile(null);
    setJob(selected);
    setError('');
    setView('upload');
  }

  async function extract() {
    setSending(true);
    setError('');
    setJob(null);
    try {
      const form = new FormData();
      form.append('file', file);
      const created = await fetch('/api/extractions', { method: 'POST', body: form }).then(responseJson);
      setJob(created);
      setJobs(current => [created, ...current.filter(item => item.id !== created.id)]);
      setConnected(true);
    } catch (problem) {
      setError(problem.message);
    } finally {
      setSending(false);
    }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(job.profile, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = job.filename.replace(/\.[^.]+$/, '') + '.json';
    link.click();
    URL.revokeObjectURL(url);
  }

  const previewName = file?.name || job?.filename;
  const previewSource = previewName?.toLowerCase().endsWith('.pdf')
    ? (file || job.source_url)
    : null;

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span>CV</span><strong>CV Management</strong></div>
      <nav aria-label="Main navigation">
        <button className={view === 'upload' ? 'active' : ''} onClick={newExtraction}><span>＋</span>New extraction</button>
        <button className={view === 'files' ? 'active' : ''} onClick={() => { setView('files'); loadJobs(); }}><span>▤</span>Files <b>{jobs.length}</b></button>
      </nav>
      <div className="recent">
        <p>RECENT FILES</p>
        {jobs.slice(0, 5).map(item => <button key={item.id} onClick={() => openJob(item)} title={item.filename}>
          <span className="file-mark">{item.filename.split('.').pop().toUpperCase()}</span>
          <span><strong>{item.filename}</strong><small>{label(item.status)}</small></span>
        </button>)}
        {!jobs.length && <small>No files yet</small>}
      </div>
      <div className="connection"><i className={connected ? 'online' : ''} />{connected ? 'API connected' : 'API unavailable'}</div>
    </aside>

    <main>
      {view === 'files' ? <section className="files-page">
        <div className="page-heading"><div><span className="eyebrow">DOCUMENT LIBRARY</span><h1>Files and results</h1><p>Open any stored CV to review its source and extracted information.</p></div><button onClick={newExtraction}>＋ Upload CV</button></div>
        <div className="file-list">
          <div className="file-list-head"><span>Name</span><span>Status</span><span>Duration</span><span /></div>
          {jobs.map(item => <button className="file-row" key={item.id} onClick={() => openJob(item)}>
            <span className="file-name"><i>{item.filename.split('.').pop().toUpperCase()}</i><strong>{item.filename}</strong></span>
            <Status value={item.status} />
            <span className="duration">{item.seconds ? `${item.seconds}s` : '—'}</span>
            <span className="open">Open →</span>
          </button>)}
          {!jobs.length && <div className="library-empty"><span>□</span><h2>No files yet</h2><p>Your uploaded CVs and extraction results will appear here.</p><button onClick={newExtraction}>Upload your first CV</button></div>}
        </div>
      </section> : <>
        <div className="page-heading"><div><span className="eyebrow">EXTRACTION WORKSPACE</span><h1>{job && !file ? job.filename : 'New extraction'}</h1><p>Upload a CV, compare the original, and review every extracted field.</p></div>{job && <Status value={job.status} />}</div>

        <section className="upload" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); choose(event.dataTransfer.files[0]); }}>
          <div className="upload-icon">↑</div>
          <div className="upload-copy"><strong>{file ? file.name : 'Drop a CV here'}</strong><span>{file ? `${(file.size / 1024).toFixed(0)} KB · Ready to extract` : 'PDF, TXT or Markdown · Up to 25 MB'}</span></div>
          <input ref={input} type="file" accept=".pdf,.txt,.md" hidden onChange={event => choose(event.target.files[0])} />
          <button className="secondary" disabled={!!busy} onClick={() => input.current.click()}>{file ? 'Change file' : 'Browse files'}</button>
          <button disabled={!file || !!busy} onClick={extract}>{busy ? 'Processing…' : 'Extract information'} <span>→</span></button>
        </section>

        {error && <div className="error" role="alert">{error}</div>}
        <div className="workspace">
          <section className="panel">
            <div className="panel-heading"><h2>Original document</h2>{(file || job) && <span className="badge">{(file?.name || job.filename).split('.').pop().toUpperCase()}</span>}</div>
            <div className="document">{previewSource ? <PdfPreview key={file ? file.name + file.lastModified : job.id} source={previewSource} /> : text ? <pre>{text}</pre> : <div className="empty"><div className="paper-icon">≡</div><h3>No document selected</h3><p>Choose a file above or open one from your file library.</p></div>}</div>
          </section>
          <section className="panel">
            <div className="panel-heading"><h2>Extracted information</h2></div>
            <div className="results"><Results job={job} busy={busy} onDownload={download} /></div>
          </section>
        </div>
      </>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
