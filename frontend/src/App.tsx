import { useAuthenticator } from "@aws-amplify/ui-react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Ask from "./pages/Ask";
import Courses from "./pages/Courses";
import Deadlines from "./pages/Deadlines";
import Landing from "./pages/Landing";
import Settings from "./pages/Settings";

function Shell() {
  const { user, signOut } = useAuthenticator((ctx) => [ctx.user]);
  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">Syllabus Agent</span>
        <nav>
          <NavLink to="/" end>Deadlines</NavLink>
          <NavLink to="/courses">Courses</NavLink>
          <NavLink to="/ask">Ask</NavLink>
          <NavLink to="/settings">Settings</NavLink>
        </nav>
        <span className="who">
          {user?.signInDetails?.loginId}
          <button className="link" onClick={signOut}>Sign out</button>
        </span>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Deadlines />} />
          <Route path="/courses" element={<Courses />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const { authStatus } = useAuthenticator((ctx) => [ctx.authStatus]);
  return authStatus === "authenticated" ? <Shell /> : <Landing />;
}
