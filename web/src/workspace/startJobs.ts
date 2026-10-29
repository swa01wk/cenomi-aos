import type { QueryClient } from "@tanstack/react-query";
import { client } from "../api/client";
import type { components } from "../api/schema";
import { coordinationWorkflow } from "./workspaceEntry";
import { invalidateWorkspaceLists, workspaceKeys } from "./useWorkspaceQueries";

type Worker = components["schemas"]["DigitalWorker"];
type Snapshot = components["schemas"]["InstanceSnapshot"];

export async function startCoordinatorThread(
  entry: Worker,
  message: string,
  idempotencyKey: string,
  queryClient: QueryClient,
): Promise<Snapshot> {
  const wf = coordinationWorkflow(entry);
  if (!wf?.name) throw new Error("No coordination workflow for entry colleague");
  const { data, error } = await client.POST("/instances", {
    params: { header: { "Idempotency-Key": idempotencyKey } },
    body: { seat: entry.seat, workflow: wf.name, first_message: message },
  });
  if (error) throw error;
  if (!data) throw new Error("No snapshot returned");
  queryClient.setQueryData(workspaceKeys.instance(data.instance_id), data);
  invalidateWorkspaceLists(queryClient);
  return data;
}

export async function startSpecialistFromIntake(
  message: string,
  idempotencyKey: string,
  queryClient: QueryClient,
  extra?: { repeat_from_instance_id?: string; seat?: string },
): Promise<Snapshot> {
  const { data, error } = await client.POST("/workspace/intake", {
    params: { header: { "Idempotency-Key": idempotencyKey } },
    body: { message, ...(extra?.seat ? { seat: extra.seat } : {}), ...(extra?.repeat_from_instance_id ? { repeat_from_instance_id: extra.repeat_from_instance_id } : {}) },
  });
  if (error) throw error;
  if (!data) throw new Error("No snapshot returned");
  queryClient.setQueryData(workspaceKeys.instance(data.instance_id), data);
  invalidateWorkspaceLists(queryClient);
  return data;
}
