import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, Deadline, localToday } from "../api";

type Range = "upcoming" | "all";

const parse = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
};
const fmtDay = (iso: string) =>
  parse(iso).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });

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

function Row({ d }: { d: Deadline }) {
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
        </summary>
        {d.sourceText && (
          <blockquote>
            “{d.sourceText}”{d.page ? <small> (p. {d.page})</small> : null}
          </blockquote>
        )}
      </details>
      <span className="weight">{d.weightPercent != null ? `${d.weightPercent}%` : ""}</span>
    </li>
  );
}

export default function Deadlines() {
  const [range, setRange] = useState<Range>("upcoming");
  const [items, setItems] = useState<Deadline[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setItems(null);
    setError("");
    api
      .listDeadlines(range === "upcoming" ? 14 : undefined)
      .then((r) => setItems(r.deadlines))
      .catch((e) => setError(e.message));
  }, [range]);

  const { dated, undated, total } = useMemo(() => {
    const all = items ?? [];
    const dated = all.filter((d) => d.dueDate).sort((a, b) => (a.dueDate! + (a.dueTime ?? "")).localeCompare(b.dueDate! + (b.dueTime ?? "")));
    const total = dated.reduce((sum, d) => sum + (d.weightPercent ?? 0), 0);
    return { dated, undated: all.filter((d) => !d.dueDate), total };
  }, [items]);

  const today = localToday();

  return (
    <section>
      <div className="page-head">
        <h1>Deadlines</h1>
        <div className="segmented">
          <button className={range === "upcoming" ? "on" : ""} onClick={() => setRange("upcoming")}>Next 14 days</button>
          <button className={range === "all" ? "on" : ""} onClick={() => setRange("all")}>Whole term</button>
        </div>
      </div>

      {error && <p className="error">{error}</p>}
      {items === null && !error && <p className="muted">Loading…</p>}

      {items && items.length === 0 && (
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
          <ul>{list.map((d, i) => <Row key={`${d.syllabusId}-${d.title}-${i}`} d={d} />)}</ul>
        </div>
      ))}

      {range === "all" && undated.length > 0 && (
        <div className="week">
          <h2>Date not stated</h2>
          <ul>{undated.map((d, i) => <Row key={`${d.syllabusId}-${d.title}-${i}`} d={d} />)}</ul>
        </div>
      )}
    </section>
  );
}
