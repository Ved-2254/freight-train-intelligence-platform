import { NavLink, Outlet } from "react-router-dom";
import { GlobalBackground } from "./GlobalBackground";
import { ServiceStatus } from "./ServiceStatus";
import { TrainWindowTransition } from "./TrainWindowTransition";

export function Layout() {
  return (
    <>
      <GlobalBackground />
      <TrainWindowTransition />
      <header className="header" role="banner">
        <div className="header-inner">
          <NavLink to="/" className="brand">
            <svg
              className="brand-icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="4" y="3" width="16" height="16" rx="2" />
              <path d="M4 11h16" />
              <path d="M12 3v8" />
              <circle cx="8" cy="15" r="1" />
              <circle cx="16" cy="15" r="1" />
              <path d="M8 19l-2 2" />
              <path d="M16 19l2 2" />
            </svg>
            <span>Freight Train Intelligence Platform</span>
          </NavLink>
          <nav className="nav" aria-label="Main navigation">
            <NavLink to="/" end>
              Analyse video
            </NavLink>
            <NavLink to="/jobs">Jobs</NavLink>
          </nav>
          <div className="header-right">
            <ServiceStatus />
          </div>
        </div>
      </header>
      <main className="main" role="main">
        <Outlet />
      </main>
    </>
  );
}
