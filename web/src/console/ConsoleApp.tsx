import type { Session } from "../api";
import { initials } from "../ui";
import AuditPage from "./AuditPage";
import OrgPage from "./OrgPage";
import PacksPage from "./PacksPage";
import VersionPage from "./VersionPage";

type NavItem = { label: string; to?: string; key?: string; soon?: string; roles?: string[] };

// Pages arrive milestone by milestone; later ones are shown so the shape of the Console is visible.
const DEFINE: NavItem[] = [
  { label: "Organization", to: "/console/org", key: "org" },
  { label: "Domain packs", to: "/console/packs", key: "packs" },
  { label: "Seats", soon: "M1" },
  { label: "Workflows", soon: "M2" },
  { label: "Policies", soon: "M3" },
  { label: "Tools and connectors", soon: "M3" },
];
const OPERATE: NavItem[] = [
  { label: "Instances", soon: "M2" },
  { label: "Approvals", soon: "M3" },
  { label: "Observability", soon: "M4" },
  { label: "Audit", to: "/console/audit", key: "audit", roles: ["platform_admin", "risk"] },
];

type Props = { session: Session; route: string[]; signOut: () => void };

export default function ConsoleApp({ session, route, signOut }: Props) {
  const page = route[0] ?? "packs";
  const roles = session.person.roles;
  const canAudit = roles.some((r) => r === "platform_admin" || r === "risk");
  const canSync = roles.some((r) => ["platform_admin", "process_owner", "seat_owner"].includes(r));

  const link = (item: NavItem) => {
    if (item.soon || (item.roles && !item.roles.some((r) => roles.includes(r)))) {
      return (
        <span key={item.label} className="soon" title={item.soon ? `Arrives in ${item.soon}` : "Not available for your roles"}>
          {item.label} {item.soon && <small>{item.soon}</small>}
        </span>
      );
    }
    return (
      <a key={item.label} href={`#${item.to}`} aria-current={page === item.key ? "page" : undefined}>
        {item.label}
      </a>
    );
  };

  let body;
  if (page === "org") body = <OrgPage />;
  else if (page === "audit" && canAudit) body = <AuditPage />;
  else if (page === "versions" && route[1]) body = <VersionPage id={route[1]} />;
  else body = <PacksPage canSync={canSync} />;

  return (
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
            <span className="avatar console">{initials(session.person.name)}</span>
            <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
              <span style={{ color: "#fff", fontWeight: 500 }}>{session.person.name}</span>
              <span style={{ fontSize: 12, color: "var(--nav-mute)" }}>{roles.join(", ").replace(/_/g, " ")}</span>
            </div>
          </div>
          <a href="#/workspace">Open the Workspace</a>
          <button onClick={signOut}>Sign out</button>
        </div>
      </nav>
      <main>{body}</main>
    </div>
  );
}
