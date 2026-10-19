import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { client } from "../api/client";
import type { components } from "../api/schema";
import {
  DataTable,
  EmptyState,
  ErrorBanner,
  MeterBar,
  PageHeader,
  Panel,
  Skeleton,
  StatusPill,
} from "../components";
import { initials, teamLabel } from "../lib/ui";
import { useOrgPeople } from "./useOrgPeople";

type Seat = components["schemas"]["Seat"];

export default function SeatsPage() {
  const { personName } = useOrgPeople();
  // Same query as the Packs page; maps a Seat's pack_version id to "<pack> v<n>".
  const packs = useQuery({
    queryKey: ["packs"],
    queryFn: async () => {
      const { data: listing } = await client.GET("/console/packs");
      return listing!;
    },
  });
  const packVersionLabel = (id: string | undefined) => {
    if (!id) return "";
    for (const p of packs.data?.packs ?? []) {
      const v = p.versions?.find((x) => x.id === id);
      if (v) return `${p.name} v${v.version}`;
    }
    return id;
  };
  const { data, error, isPending } = useQuery({
    queryKey: ["seats"],
    queryFn: async () => {
      const { data: listing } = await client.GET("/console/seats");
      return listing!.items;
    },
  });

  if (error) return <ErrorBanner title="We couldn't load seats" detail={(error as Error).message} />;
  if (isPending || !data) return <Skeleton />;

  return (
    <>
      <PageHeader
        eyebrow="Define · Seats"
        title="Seats"
        subtitle="Seats come from published packs. A new pack version brings a new Seat version, which starts as DRAFT."
      />

      <DataTable<Seat>
        caption="Seat list"
        rows={data}
        getRowKey={(s) => `${s.name}@${s.version}`}
        empty={
          <EmptyState
            title="No seats yet"
            nextStep="Publish a pack version that defines a Seat. It will appear here as DRAFT."
          />
        }
        columns={[
          {
            id: "seat",
            header: "Seat",
            render: (s) => (
              <Link to={`/console/seats/${encodeURIComponent(s.name)}`} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span className="avatar" style={{ width: 28, height: 28, fontSize: 11 }}>
                  {initials(s.display_name)}
                </span>
                <span style={{ display: "flex", flexDirection: "column" }}>
                  <span style={{ fontWeight: 500 }}>{s.display_name}</span>
                  <span className="mono muted" style={{ fontSize: 12 }}>
                    {s.name}
                  </span>
                </span>
              </Link>
            ),
          },
          { id: "placement", header: "Placement", render: (s) => teamLabel(s.placement) },
          {
            id: "version",
            header: "Version",
            render: (s) => (
              <span className="mono">
                v{s.version} · {packVersionLabel(s.pack_version)}
              </span>
            ),
          },
          {
            id: "lifecycle",
            header: "Lifecycle",
            render: (s) => <StatusPill state={s.state} />,
          },
          {
            id: "availability",
            header: "Availability",
            render: (s) => <StatusPill state={s.availability} />,
          },
          {
            id: "running",
            header: "Running now",
            align: "right",
            render: (s) => `${s.running_attempts ?? 0} attempts`,
          },
          {
            id: "spend",
            header: "Today's spend",
            render: (s) => (
              <MeterBar
                label={`USD ${(s.spend_today_usd ?? 0).toFixed(2)} of ${(s.daily_limit_usd ?? 0).toFixed(2)}`}
                value={s.spend_today_usd ?? 0}
                limit={s.daily_limit_usd ?? 0}
              showValues={false} />
            ),
          },
          { id: "owner", header: "Owner", render: (s) => personName(s.owner) },
        ]}
      />

      <Panel title="Lifecycle a Seat goes through">
        <ol className="mono" style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexWrap: "wrap", gap: 6, fontSize: 12 }}>
          {["DRAFT", "CONFIGURED", "TESTING", "APPROVED", "ACTIVE"].map((s, i, arr) => (
            <li key={s} style={{ display: "contents" }}>
              <span className="pill">{s}</span>
              {i < arr.length - 1 && <span aria-hidden="true" className="muted">→</span>}
            </li>
          ))}
        </ol>
        <ul style={{ margin: "12px 0 0", paddingLeft: 18, color: "var(--muted)", fontSize: 13 }}>
          <li>Configured needs all six configuration checks; Testing needs both eval suites to pass.</li>
          <li>Only the Seat owner activates, and never the person who configured it.</li>
          <li>From Active: Paused (owner, reversible) or Killed (emergency). Retired ends the Seat.</li>
        </ul>
      </Panel>
    </>
  );
}
