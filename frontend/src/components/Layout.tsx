import type { ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";

const NAV = [
  { to: "/", label: "金銮殿", end: true },
  { to: "/courtroom", label: "朝房" },
  { to: "/censorate", label: "御史台" },
  { to: "/posts", label: "百官名册" },
  { to: "/edicts", label: "拟旨下谕" },
];

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <div className="world-shell">
    <header className="world-header">
      <NavLink to="/" className="world-brand"><span>朝堂</span><small>IMPERIAL COURT</small></NavLink>
      <nav className="world-nav" aria-label="宫廷场景">
        {NAV.map(item => <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => `jade-nav${isActive ? " active" : ""}`}>{item.label}</NavLink>)}
      </nav>
    </header>
    <main key={location.pathname} className={`scene-stage ${location.pathname === "/" ? "hall-route" : "side-route"}`}>{children}</main>
  </div>;
}
