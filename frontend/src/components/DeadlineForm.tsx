import { FormEvent, useState } from "react";
import { Deadline, DEADLINE_TYPES, DeadlineInput, Syllabus } from "../api";

interface Props {
  initial?: Deadline;
  /** Shown only when adding: which course the new deadline belongs to. */
  courses?: Syllabus[];
  onSave: (input: DeadlineInput, syllabusId?: string) => Promise<void>;
  onCancel: () => void;
}

const toInput = (d?: Deadline): DeadlineInput => ({
  title: d?.title ?? "",
  type: d?.type ?? "assignment",
  dueDate: d?.dueDate ?? "",
  dueTime: d?.dueTime ?? "",
  weightPercent: d?.weightPercent != null ? String(d.weightPercent) : "",
});

export default function DeadlineForm({ initial, courses, onSave, onCancel }: Props) {
  const [input, setInput] = useState<DeadlineInput>(toInput(initial));
  const [syllabusId, setSyllabusId] = useState(courses?.[0]?.syllabusId ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const set = (key: keyof DeadlineInput) => (e: { target: { value: string } }) =>
    setInput((v) => ({ ...v, [key]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSave(input, courses ? syllabusId : undefined);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  }

  return (
    <form className="card deadline-form" onSubmit={submit}>
      {courses && (
        <label>
          Course
          <select value={syllabusId} onChange={(e) => setSyllabusId(e.target.value)} required>
            {courses.map((c) => (
              <option key={c.syllabusId} value={c.syllabusId}>{c.courseCode ?? c.filename}</option>
            ))}
          </select>
        </label>
      )}
      <label className="wide">
        Title
        <input value={input.title} onChange={set("title")} required maxLength={200} autoFocus />
      </label>
      <label>
        Type
        <select value={input.type} onChange={set("type")}>
          {DEADLINE_TYPES.map((t) => <option key={t} value={t}>{t.replace("_", " ")}</option>)}
        </select>
      </label>
      <label>
        Due date
        <input type="date" value={input.dueDate} onChange={set("dueDate")} />
      </label>
      <label>
        Time <small className="muted">(optional)</small>
        <input type="time" value={input.dueTime} onChange={set("dueTime")} />
      </label>
      <label>
        Weight %
        <input type="number" min={0} max={100} step="any" value={input.weightPercent} onChange={set("weightPercent")} />
      </label>
      {error && <p className="error wide">{error}</p>}
      <div className="actions wide">
        <button type="button" className="link" onClick={onCancel}>Cancel</button>
        <button type="submit" disabled={saving || (!!courses && !syllabusId)}>{saving ? "Saving…" : "Save"}</button>
      </div>
    </form>
  );
}
