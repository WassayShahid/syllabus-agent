import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { api, Syllabus } from "../api";

const BUSY = new Set(["PENDING_UPLOAD", "PROCESSING"]);
const LABEL: Record<string, string> = {
  PENDING_UPLOAD: "Uploading…",
  PROCESSING: "Reading outline…",
  READY: "Ready",
  FAILED: "Failed",
};

export default function Courses() {
  const [syllabi, setSyllabi] = useState<Syllabus[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [termStart, setTermStart] = useState("");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(() => api.listSyllabi().then((r) => setSyllabi(r.syllabi)), []);

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [refresh]);

  // Poll while anything is still processing (the pipeline takes ~30-90 s per outline).
  const busy = syllabi?.some((s) => BUSY.has(s.status));
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(() => refresh().catch(() => {}), 4000);
    return () => clearInterval(timer);
  }, [busy, refresh]);

  async function onUpload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      await api.upload(file, termStart || undefined);
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
    }
  }

  async function onDelete(s: Syllabus) {
    if (!confirm(`Delete ${s.courseCode ?? s.filename} and all its deadlines?`)) return;
    try {
      await api.deleteSyllabus(s.syllabusId);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section>
      <div className="page-head">
        <h1>Courses</h1>
      </div>

      <form className="card upload" onSubmit={onUpload}>
        <label>
          Course outline (PDF)
          <input ref={fileInput} type="file" accept="application/pdf,.pdf"
                 onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label>
          First day of term <small className="muted">(optional; turns “Week 7” into a real date)</small>
          <input type="date" value={termStart} onChange={(e) => setTermStart(e.target.value)} />
        </label>
        <button type="submit" disabled={!file || uploading}>{uploading ? "Uploading…" : "Upload"}</button>
      </form>

      {error && <p className="error">{error}</p>}
      {syllabi === null && !error && <p className="muted">Loading…</p>}
      {syllabi?.length === 0 && <p className="muted">No outlines yet. Upload your first one above.</p>}

      <ul className="courses">
        {syllabi?.map((s) => (
          <li key={s.syllabusId} className="card">
            <div className="course-head">
              <div>
                <strong>{s.courseCode ?? s.filename}</strong>
                {s.courseTitle && <span className="muted"> · {s.courseTitle}</span>}
                <div className="muted small">{s.filename}{s.termStart && ` · term starts ${s.termStart}`}</div>
              </div>
              <span className={`status status-${s.status}`}>{LABEL[s.status] ?? s.status}</span>
            </div>
            {s.status === "READY" && (
              <p className="small">{s.deadlineCount ?? 0} deadlines found across {s.pageCount} pages.</p>
            )}
            {s.error && <p className="error small">{s.error}</p>}
            {s.warnings && s.warnings.length > 0 && (
              <details className="small">
                <summary>{s.warnings.length} thing{s.warnings.length > 1 ? "s" : ""} to double-check</summary>
                <ul>{s.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              </details>
            )}
            <button className="link danger" onClick={() => onDelete(s)}>Delete</button>
          </li>
        ))}
      </ul>
    </section>
  );
}
