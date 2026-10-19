import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { client } from "../api/client";

export const workspaceKeys = {
  digitalWorkers: ["digitalWorkers"] as const,
  myInstances: (status?: string) => ["myInstances", status ?? "all"] as const,
  instance: (id: string) => ["instance", id] as const,
  artifact: (id: string) => ["artifact", id] as const,
  artifactVersion: (id: string, version: number) => ["artifactVersion", id, version] as const,
};

export function useDigitalWorkers() {
  return useQuery({
    queryKey: workspaceKeys.digitalWorkers,
    queryFn: async () => {
      const { data, error } = await client.GET("/workspace/digital-workers");
      if (error) throw error;
      return data!.items;
    },
    refetchOnWindowFocus: true,
  });
}

export function useMyInstances(status?: "active" | "closed") {
  return useQuery({
    queryKey: workspaceKeys.myInstances(status),
    queryFn: async () => {
      const { data, error } = await client.GET("/instances", {
        params: {
          query: {
            participant: "me",
            ...(status ? { status } : {}),
          },
        },
      });
      if (error) throw error;
      return data!.items;
    },
    refetchOnWindowFocus: true,
  });
}

export function invalidateWorkspaceLists(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: workspaceKeys.digitalWorkers });
  void queryClient.invalidateQueries({ queryKey: ["myInstances"] });
}

export function useRefetchWorkspaceOnFocus() {
  const queryClient = useQueryClient();
  useEffect(() => {
    const onFocus = () => {
      invalidateWorkspaceLists(queryClient);
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [queryClient]);
}
