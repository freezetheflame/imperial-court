// Layout — imperial court shell with sidebar navigation.
// Placeholder chrome; styling will be elevated by the kimi design pass.

import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

const NAV = [
  { to: "/", label: "奏折", end: true },
  { to: "/edicts", label: "上谕" },
  { to: "/censorate", label: "御史台" },
  { to: "/posts", label: "官职墙" },
];

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <aside style={{ width: 180, padding: "1rem", borderRight: "1px solid #ddd" }}>
        <h1 style={{ fontSize: "1.2rem", marginBottom: "1rem" }}>朝堂</h1>
        <nav style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              style={({ isActive }) => ({
                padding: "0.4rem 0.6rem",
                borderRadius: 4,
                textDecoration: "none",
                color: isActive ? "#fff" : "#333",
                background: isActive ? "#8b1a1a" : "transparent",
              })}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main style={{ flex: 1, padding: "1.5rem", maxWidth: 900 }}>{children}</main>
    </div>
  );
}
