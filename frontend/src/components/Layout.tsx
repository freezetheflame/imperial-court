import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

const NAV = [
  { to: "/", label: "奏折", hint: "御览", mark: "▣", end: true },
  { to: "/edicts", label: "上谕", hint: "拟旨", mark: "✦" },
  { to: "/censorate", label: "御史台", hint: "案卷", mark: "⚖" },
  { to: "/posts", label: "官职墙", hint: "百官", mark: "◇" },
];

export function Layout({ children }: { children: ReactNode }) {
  return <div className="court-shell">
    <aside className="court-sidebar">
      <div className="brand"><h1>朝堂</h1><p>IMPERIAL COURT</p></div>
      <nav className="nav-list" aria-label="朝堂导航">
        {NAV.map((item) => <NavLink key={item.to} to={item.to} end={item.end} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
          <span className="nav-mark">{item.mark}</span><span>{item.label}<small style={{ display: "block", opacity: .58, fontSize: ".68rem", letterSpacing: ".08em" }}>{item.hint}</small></span>
        </NavLink>)}
      </nav>
      <div className="sidebar-seal">奉天承运 · 日理万机</div>
    </aside>
    <main className="court-main">{children}</main>
  </div>;
}
