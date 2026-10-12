import { useRef } from "react";
import { Authenticator, useAuthenticator } from "@aws-amplify/ui-react";

type AuthMode = "signIn" | "signUp";

// Static preview of the Deadlines page (sample data, not an API call).
const PREVIEW = [
  { when: "Fri, Oct 9", course: "COMPSCI 3GC3", title: "A1 transformation", weight: "6%" },
  { when: "Sun, Oct 11", course: "COMPSCI 4ML3", title: "Assignment 1", weight: "5%" },
  { when: "Tue, Oct 27", course: "COMPSCI 3GC3", title: "Midterm exam", weight: "26%", exam: true },
  { when: "Wed, Oct 28", course: "COMPSCI 4ML3", title: "Midterm exam", weight: "25%", exam: true },
];

const STEPS = [
  { n: "1", title: "Upload your outlines", body: "Drop in the PDF for each course. Add the first day of term so “Week 7” becomes a real date." },
  { n: "2", title: "Check the timeline", body: "Every assignment, test and exam lands on one list with its date and weight. Fix or add anything by hand." },
  { n: "3", title: "Stay ahead", body: "Ask what's due, or get a morning email when something is coming up." },
];

const FEATURES = [
  { title: "Answers with receipts", body: "Ask “what's the late policy in 3GC3?” and get an answer that cites the exact line and page of the outline." },
  { title: "Week numbers, solved", body: "Dates like “Thursday of week 5” are worked out from your term start, and flagged when the exact day isn't stated." },
  { title: "You stay in control", body: "Edit a date, change a weight, or add a quiz the outline forgot. Your changes are marked so you know what you touched." },
  { title: "Reminders you can turn off", body: "A short morning digest only on days something is due. One switch in Settings to stop it." },
];

export default function Landing() {
  const { toSignIn, toSignUp } = useAuthenticator(() => []);
  const authRef = useRef<HTMLDivElement>(null);

  const openAuth = (mode: AuthMode) => {
    if (mode === "signIn") toSignIn();
    else toSignUp();
    authRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  return (
    <div className="landing">
      <header className="landing-nav">
        <span className="brand">Syllabus Agent</span>
        <button className="link" onClick={() => openAuth("signIn")}>Sign in</button>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <h1>Every deadline from every course outline, in one place.</h1>
          <p className="lede">
            Upload your syllabi as PDFs. Syllabus Agent pulls out each assignment, test and exam with its date and
            weight, builds your term timeline, and answers questions about it.
          </p>
          <div className="hero-actions">
            <button onClick={() => openAuth("signUp")}>Get started, it's free</button>
            <button className="secondary" onClick={() => openAuth("signIn")}>I have an account</button>
          </div>
          <p className="proof">
            <strong>33 of 33</strong> deadlines extracted with the right date and weight on 5 real McMaster course outlines.
          </p>
        </div>

        <div className="hero-auth" ref={authRef}>
          <Authenticator initialState="signUp" signUpAttributes={["email"]} />
        </div>
      </section>

      <section className="preview" aria-label="Example of the deadlines page">
        <div className="preview-window">
          <div className="preview-bar"><span /><span /><span /></div>
          <div className="preview-body">
            <p className="preview-title">Next 14 days</p>
            <p className="muted small">4 items worth 62% of your grades in total.</p>
            <ul>
              {PREVIEW.map((d) => (
                <li key={d.course + d.title} className="deadline">
                  <span className="when">{d.when}</span>
                  <span className="course">{d.course}</span>
                  <span className="what">
                    {d.title} <span className={`type ${d.exam ? "type-midterm" : ""}`}>{d.exam ? "midterm" : "assignment"}</span>
                  </span>
                  <span className="weight">{d.weight}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="steps">
        <h2>How it works</h2>
        <ol>
          {STEPS.map((s) => (
            <li key={s.n}>
              <span className="step-n">{s.n}</span>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="features">
        {FEATURES.map((f) => (
          <div key={f.title} className="feature">
            <h3>{f.title}</h3>
            <p>{f.body}</p>
          </div>
        ))}
      </section>

      <section className="cta">
        <h2>Start your term organised.</h2>
        <button onClick={() => openAuth("signUp")}>Create a free account</button>
      </section>

      <footer className="landing-footer muted small">
        Built with Claude on Amazon Bedrock. Your outlines stay private to your account.
      </footer>
    </div>
  );
}
