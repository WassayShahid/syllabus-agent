import { useEffect, useState } from "react";
import { api, Settings as SettingsData } from "../api";

const DAYS = [1, 3, 7, 14];

export default function Settings() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getSettings().then(setSettings).catch((e) => setError(e.message));
  }, []);

  async function save(emailEnabled: boolean, daysAhead: number) {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const saved = await api.saveSettings(emailEnabled, daysAhead);
      setSettings(saved);
      if (saved.verificationSent) {
        setStatus(`AWS just emailed ${saved.email} a confirmation link. Click it once, and reminders will start arriving.`);
      } else {
        setStatus(emailEnabled ? "Reminders are on." : "Reminders are off.");
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const r = await api.sendTestEmail();
      setStatus(`Sent to ${r.sentTo} with ${r.deadlineCount} upcoming deadline${r.deadlineCount === 1 ? "" : "s"}.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (!settings) return <section><div className="page-head"><h1>Settings</h1></div>{error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>}</section>;

  return (
    <section>
      <div className="page-head">
        <h1>Settings</h1>
      </div>

      <div className="card settings">
        <h2>Email reminders</h2>
        {!settings.available ? (
          <p className="muted">Email reminders aren't set up on this deployment yet.</p>
        ) : (
          <>
            <label className="toggle">
              <input
                type="checkbox"
                checked={settings.emailEnabled}
                disabled={busy}
                onChange={(e) => save(e.target.checked, settings.daysAhead)}
              />
              Email me a morning summary when something is due soon
            </label>
            <label>
              Look ahead
              <select
                value={settings.daysAhead}
                disabled={busy || !settings.emailEnabled}
                onChange={(e) => save(settings.emailEnabled, Number(e.target.value))}
              >
                {DAYS.map((d) => <option key={d} value={d}>{d === 1 ? "1 day" : `${d} days`}</option>)}
              </select>
            </label>
            <p className="muted small">
              Sent to {settings.email} around 8 am, only on days when something is due within the window.
            </p>
            <button className="secondary" onClick={test} disabled={busy}>Send me a test email now</button>
          </>
        )}
        {status && <p className="ok small">{status}</p>}
        {error && <p className="error small">{error}</p>}
      </div>
    </section>
  );
}
