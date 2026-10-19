import { NavLink, Outlet } from "react-router";
import { ShellProvider } from "../components";
import { useSession } from "../app/session";
import { initials } from "../lib/ui";

type NavItem = { label: string; to?: string; end?: boolean; soon?: string; roles?: string[] };

const DEFINE: NavItem[] = [
  { label: "Organization", to: "/console/org", end: true },
  { label: "Domain packs", to: "/console/packs", end: true },
  { label: "Seats", soon: "M1" },
  { label: "Workflows", soon: "M2" },
  { label: "Policies", soon: "M3" },
  { label: "Tools and connectors", soon: "M3" },
];
const OPERATE: NavItem[] = [
  { label: "Instances", soon: "M2" },
  { label: "Approvals", soon: "M3" },
  { label: "Observability", soon: "M4" },
  { label: "Audit", to: "/console/audit", end: true, roles: ["platform_admin", "risk"] },
];

export default function ConsoleShell() {
  const { me, signOut } = useSession();
  if (!me) return null;
  const roles = me.roles;

  // UX hint only — kernel 403 on Console APIs is authoritative. Follow-up: kernel-provided per-page availability.
  const link = (item: NavItem) => {
    if (item.soon || (item.roles && !item.roles.some((r) => roles.includes(r)))) {
      return (
        <span key={item.label} className="soon" title={item.soon ? `Arrives in ${item.soon}` : "Not available for your roles"}>
          {item.label} {item.soon && <small>{item.soon}</small>}
        </span>
      );
    }
    return (
      <NavLink key={item.label} to={item.to!} end={item.end}>
        {item.label}
      </NavLink>
    );
  };

  const canSync = roles.some((r) => ["platform_admin", "process_owner", "seat_owner"].includes(r));

  return (
    <ShellProvider shell="console">
    <div className="shell">
      <nav className="console-nav" aria-label="Console">
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "0 8px" }}>
          <div className="logo">AOS</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span style={{ fontWeight: 600, color: "#fff" }}>Console</span>
            <span style={{ fontSize: 12, color: "var(--nav-mute)" }}>Sandbox environment</span>
          </div>
        </div>
        <div className="group">
          <span className="eyebrow">Define</span>
          {DEFINE.map(link)}
        </div>
        <div className="group">
          <span className="eyebrow">Operate</span>
          {OPERATE.map(link)}
        </div>
        <div className="foot">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="avatar console">{initials(me.name)}</span>
            <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
              <span style={{ color: "#fff", fontWeight: 500 }}>{me.name}</span>
              <span style={{ fontSize: 12, color: "var(--nav-mute)" }}>{roles.join(", ").replace(/_/g, " ")}</span>
            </div>
          </div>
          <NavLink to="/workspace">Open the Workspace</NavLink>
          <button type="button" onClick={signOut}>
            Sign out
          </button>
        </div>
      </nav>
      <main>
        <Outlet context={{ canSync }} />
      </main>
    </div>
    </ShellProvider>
  );
}
