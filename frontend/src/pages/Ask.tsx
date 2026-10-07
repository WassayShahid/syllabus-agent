import { FormEvent, useEffect, useRef, useState } from "react";
import { api, ChatTurn, Citation } from "../api";

interface Message extends ChatTurn {
  citations?: Citation[];
}

const SUGGESTIONS = [
  "What's due in the next two weeks and how much is it worth?",
  "When are my midterms?",
  "What's the late policy for each course?",
];

function CitationChip({ c }: { c: Citation }) {
  const label =
    c.kind === "deadline"
      ? `${c.courseCode ?? ""} ${c.title ?? ""}`.trim()
      : `${c.courseCode ?? c.filename ?? ""} p.${c.page}`;
  return (
    <details className="citation">
      <summary>[{c.id}] {label}</summary>
      {c.kind === "deadline" ? (
        <p>
          {c.title}: {c.dueDate ?? "no date"}
          {c.weightPercent != null && `, ${c.weightPercent}%`}
        </p>
      ) : (
        <blockquote>{c.text}</blockquote>
      )}
    </details>
  );
}

export default function Ask() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => bottom.current?.scrollIntoView({ behavior: "smooth" }), [messages, pending]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || pending) return;
    const history: ChatTurn[] = messages.map(({ role, content }) => ({ role, content }));
    setMessages((m) => [...m, { role: "user", content: q }]);
    setQuestion("");
    setPending(true);
    try {
      const r = await api.ask(q, history);
      setMessages((m) => [...m, { role: "assistant", content: r.answer, citations: r.citations }]);
    } catch (err) {
      setMessages((m) => [...m, { role: "assistant", content: `Something went wrong: ${(err as Error).message}` }]);
    } finally {
      setPending(false);
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    send(question);
  };

  return (
    <section className="chat">
      <div className="page-head">
        <h1>Ask</h1>
      </div>

      {messages.length === 0 && (
        <div className="suggestions">
          {SUGGESTIONS.map((s) => (
            <button key={s} className="chip" onClick={() => send(s)}>{s}</button>
          ))}
        </div>
      )}

      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}`}>
            <p>{m.content}</p>
            {m.citations && m.citations.length > 0 && (
              <div className="citations">{m.citations.map((c) => <CitationChip key={c.id} c={c} />)}</div>
            )}
          </div>
        ))}
        {pending && <div className="bubble assistant muted">Looking through your syllabi…</div>}
        <div ref={bottom} />
      </div>

      <form className="composer" onSubmit={onSubmit}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about deadlines, weights, policies…"
          maxLength={2000}
        />
        <button type="submit" disabled={!question.trim() || pending}>Send</button>
      </form>
    </section>
  );
}
