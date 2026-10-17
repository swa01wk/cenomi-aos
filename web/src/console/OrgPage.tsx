import { api } from "../api";
import { ErrorNote, Loading, useLoad } from "../ui";

export default function OrgPage() {
  const { data: org, error } = useLoad(api.org);
  if (error) return <ErrorNote message={error} />;
  if (!org) return <Loading what="the organization" />;
  const name = (id: string) => org.people.find((p) => p.id === id)?.name ?? id;

  return (
    <>
      <header style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span className="eyebrow">Define · Organization</span>
        <h1>{org.organization.name}</h1>
        <span className="sub">
          <span className="mono">{org.organization.id}</span> · data residency {org.organization.data_residency} · seeded
          from <span className="mono">seed/org.yaml</span> (identity provider sync arrives after the POC)
        </span>
      </header>

      <section aria-label="Departments" className="cards">
        {org.departments.map((d) => (
          <div key={d.id} className="panel">
            <div className="panel-head">
              <h2>{d.name}</h2>
              <span className="muted">Head: {name(d.head)}</span>
            </div>
            <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {d.teams.map((t) => (
                <div key={t.id} style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <span>{t.name}</span>
                  <span className="muted">{name(t.owner)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>

      <section aria-label="People" className="panel">
        <div className="panel-head">
          <h2>People</h2>
          <span className="muted">{org.people.length} people · roles decide what each one can see and approve</span>
        </div>
        <div className="scroll-x">
          <table className="grid">
            <thead>
              <tr>
                <th>Person</th>
                <th>Department · team</th>
                <th>Roles</th>
                <th>Console</th>
              </tr>
            </thead>
            <tbody>
              {org.people.map((p) => (
                <tr key={p.id}>
                  <td>
                    <div>{p.name}</div>
                    <div className="mono muted">{p.id}</div>
                  </td>
                  <td>
                    {p.department} · {p.team}
                  </td>
                  <td>
                    <div className="chips">
                      {p.roles.map((r) => (
                        <span key={r} className="pill">
                          {r.replace(/_/g, " ")}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td>{p.console ? <span className="pill info">yes</span> : <span className="muted">no</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
