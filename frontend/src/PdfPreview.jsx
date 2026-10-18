import React, { useEffect, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

GlobalWorkerOptions.workerSrc = `${workerUrl}?v=2`;

function Page({ pdf, number, width }) {
  const canvas = useRef();
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setVisible(true); observer.disconnect(); }
    }, { rootMargin: '400px' });
    observer.observe(canvas.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible || !width) return;
    let cancelled = false;
    let rendering;
    setError('');
    pdf.getPage(number).then(page => {
      if (cancelled) return;
      const scale = width / page.getViewport({ scale: 1 }).width;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = page.getViewport({ scale: scale * ratio });
      const element = canvas.current;
      element.width = Math.ceil(viewport.width);
      element.height = Math.ceil(viewport.height);
      element.style.height = `${viewport.height / ratio}px`;
      rendering = page.render({ canvasContext: element.getContext('2d'), viewport });
      return rendering.promise;
    }).catch(e => { if (!cancelled && e.name !== 'RenderingCancelledException') setError('This page could not be rendered.'); });
    return () => { cancelled = true; rendering?.cancel(); };
  }, [pdf, number, width, visible]);
  return <>{error && <p role="alert" className="error">{error}</p>}<canvas ref={canvas} className="pdf-page" role="img" aria-label={`CV page ${number}`} /></>;
}

export default function PdfPreview({ source }) {
  const container = useRef();
  const [pdf, setPdf] = useState(null);
  const [width, setWidth] = useState(0);
  const [error, setError] = useState('');
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let cancelled = false;
    let task;
    setPdf(null); setError('');
    Promise.resolve(
      typeof source === 'string' ? source : source.arrayBuffer()
    ).then(data => {
      if (cancelled) return;
      task = getDocument({
        ...(typeof data === 'string' ? { url: data } : { data }),
        isEvalSupported: false,
        useSystemFonts: true,
      });
      return task.promise;
    }).then(document => { if (!cancelled && document) setPdf(document); })
      .catch(problem => {
        if (cancelled) return;
        const messages = {
          PasswordException: 'This PDF is password protected. Remove the password and try again.',
          InvalidPDFException: 'This PDF has an invalid structure and cannot be previewed.',
          MissingPDFException: 'The PDF could not be found.',
          UnexpectedResponseException: 'The PDF could not be downloaded from the server.',
        };
        setError(messages[problem?.name] || `Cannot preview this PDF: ${problem?.message || 'unknown PDF error'}`);
      });
    return () => { cancelled = true; task?.destroy(); };
  }, [source]);
  return <div ref={container} className="pdf-preview">
    {error ? <p className="error" role="alert">{error}</p> : !pdf ? <p className="preview-loading" role="status">Loading document…</p> :
      Array.from({ length: pdf.numPages }, (_, i) => <Page key={i} pdf={pdf} number={i + 1} width={width} />)}
  </div>;
}
