import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import { client } from "../api/client";

export function useOrgPeople() {
  const { data: org } = useQuery({
    queryKey: ["org"],
    queryFn: async () => {
      const { data } = await client.GET("/org");
      return data!;
    },
    staleTime: 60_000,
  });

  const personName = useCallback(
    (personId: string | null | undefined) => {
      if (!personId) return "";
      return org?.people.find((p) => p.id === personId)?.name ?? personId;
    },
    [org],
  );

  return { org, personName };
}
