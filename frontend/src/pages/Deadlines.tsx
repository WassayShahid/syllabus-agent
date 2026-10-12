import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, Deadline, DeadlineInput, localToday, Syllabus } from "../api";
import DeadlineForm from "../components/DeadlineForm";

type Range = "upcoming" | "all";

const parse = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
};
const fmtDay = (iso: string) =>
  parse(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
const keyOf = (d: Deadline) => `${d.syllabusId}-${d.deadlineId}`;

function weekStart(iso: string) {
  const d = parse(iso);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); // back to Monday
  return d;
}

function groupByWeek(items: Deadline[]) {
  const groups = new Map<string, Deadline[]>();
  for (const item of items) {
    const key = weekStart(item.dueDate!).toDateString();
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()];
}

interface RowProps {
  d: Deadline;
  editing: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: (input: DeadlineInput) => Promise<void>;
  onDelete: () => void;
}

function Row({ d, editing, onEdit, onCancel, onSave, onDelete }: RowProps) {
  if (editing) return <li><DeadlineForm initial={d} onSave={onSave} onCancel={onCancel} /></li>;
  return (
    <li className="deadline">
      <span className="when">
        {d.dueDate ? fmtDay(d.dueDate) : "No date"}
        {d.dueTime && <small> {d.dueTime}</small>}
        {d.dateApproximate && <small className="tag" title={`Week ${d.week}; exact day not stated`}>approx.</small>}
      </span>
      <span className="course">{d.courseCode}</span>
      <details className="what">
        <summary>
          {d.title} <span className={`type type-${d.type}`}>{d.type.replace("_", " ")}</span>
          {d.source && <small className="muted"> {d.source === "manual" ? "added by you" : "edited"}</small>}
        </summary>
        {d.sourceText && (
          <blockquote>
            “{d.sourceText}”{d.page ? <small> (p. {d.page})</small> : null}
          </blockquote>
        )}
        <div className="row-actions">
          <button className="link" onClick={onEdit}>Edit</button>
          <button className="link danger" onClick={onDelete}>Delete</button>
        </div>
      </details>
      <span className="weight">{d.weightPercent != null ? `${d.weightPercent}%` : ""}</span>
    </li>
  );
}

export default function Deadlines() {
  const [range, setRange] = useState<Range>("upcoming");
  const [items, setItems] = useState<Deadline[] | null>(null);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState<Syllabus[] | null>(null);   // courses to choose from while adding

  const load = useCallback(
    () => api.listDeadlines(range === "upcoming" ? 14 : undefined).then((r) => setItems(r.deadlines)),
    [range],
  );

  useEffect(() => {
    setItems(null);
    setError("");
    load().catch((e) => setError(e.message));
  }, [load]);

  const { dated, undated, total } = useMemo(() => {
    const all = items ?? [];
    const dated = all.filter((d) => d.dueDate).sort((a, b) => (a.dueDate! + (a.dueTime ?? "")).localeCompare(b.dueDate! + (b.dueTime ?? "")));
    const total = dated.reduce((sum, d) => sum + (d.weightPercent ?? 0), 0);
    return { dated, undated: all.filter((d) => !d.dueDate), total };
  }, [items]);

  async function startAdding() {
    setError("");
    try {
      const { syllabi } = await api.listSyllabi();
      const ready = syllabi.filter((s) => s.status === "READY");
      if (ready.length === 0) setError("Upload a course outline first; deadlines are added to a course.");
      else setAdding(ready);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function addDeadline(input: DeadlineInput, syllabusId?: string) {
    await api.addDeadline(syllabusId!, input);
    setAdding(null);
    await load();
  }

  async function saveEdit(d: Deadline, input: DeadlineInput) {
    await api.updateDeadline(d, input);
    setEditing(null);
    await load();
  }

  async function remove(d: Deadline) {
    if (!confirm(`Delete "${d.title}"?`)) return;
    try {
      await api.deleteDeadline(d);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const row = (d: Deadline) => (
    <Row key={keyOf(d)} d={d} editing={editing === keyOf(d)} onEdit={() => setEditing(keyOf(d))}
         onCancel={() => setEditing(null)} onSave={(input) => saveEdit(d, input)} onDelete={() => remove(d)} />
  );
  const today = localToday();

  return (
    <section>
      <div className="page-head">
        <h1>Deadlines</h1>
        <div className="head-actions">
          <button className="secondary" onClick={startAdding} disabled={!!adding}>+ Add deadline</button>
          <div className="segmented">
            <button className={range === "upcoming" ? "on" : ""} onClick={() => setRange("upcoming")}>Next 14 days</button>
            <button className={range === "all" ? "on" : ""} onClick={() => setRange("all")}>Whole term</button>
          </div>
        </div>
      </div>

      {adding && <DeadlineForm courses={adding} onSave={addDeadline} onCancel={() => setAdding(null)} />}
      {error && <p className="error">{error}</p>}
      {items === null && !error && <p className="muted">Loading…</p>}

      {items && items.length === 0 && !adding && (
        <div className="empty">
          <p>{range === "upcoming" ? "Nothing due in the next two weeks." : "No deadlines yet."}</p>
          <Link to="/courses">Upload a course outline →</Link>
        </div>
      )}

      {range === "upcoming" && dated.length > 0 && (
        <p className="muted">{dated.length} items worth {Math.round(total * 10) / 10}% of your grades in total.</p>
      )}

      {groupByWeek(dated).map(([week, list]) => (
        <div key={week} className="week">
          <h2>
            Week of {new Date(week).toLocaleDateString(undefined, { month: "long", day: "numeric" })}
            {list.some((d) => d.dueDate! < today) && <small className="muted"> (includes past)</small>}
          </h2>
          <ul>{list.map(row)}</ul>
        </div>
      ))}

      {range === "all" && undated.length > 0 && (
        <div className="week">
          <h2>Date not stated</h2>
          <ul>{undated.map(row)}</ul>
        </div>
      )}
    </section>
  );
}
