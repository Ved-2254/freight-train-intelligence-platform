import { NavLink, Outlet } from "react-router-dom";
import { ServiceStatus } from "./ServiceStatus";
import { ThemeSwitcher } from "./ThemeSwitcher";

export function Layout() {
  return (
    <>
      <header className="header">
        <div className="header-inner">
          <NavLink to="/" className="brand">Freight Train Intelligence Platform</NavLink>
          <nav className="nav">
            <NavLink to="/" end>Analyse video</NavLink>
            <NavLink to="/jobs">Jobs</NavLink>
          </nav>
          <div className="header-right">
            <ServiceStatus />
            <ThemeSwitcher />
          </div>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </>
  );
}
