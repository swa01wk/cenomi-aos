import type { InstanceSnapshot } from "./jobStreamReducer";

export type RfqSupplierTab = { supplierId: string; label: string };

export function rfqSupplierTabs(snapshot: InstanceSnapshot): RfqSupplierTab[] {
  return snapshot.artifacts
    .filter((a) => a.artifact_type === "rfq_email" || a.artifact_type === "rfp_invitation")
    .map((a) => ({
      supplierId: a.key || a.artifact_id,
      label: a.name?.trim() || a.key || "Supplier",
    }));
}

export function showResendRfqsBar(snapshot: InstanceSnapshot): boolean {
  if (!snapshot.my_roles.includes("buyer")) return false;
  if (snapshot.state !== "awaiting_quotes" && snapshot.state !== "awaiting_proposals") return false;
  return rfqSupplierTabs(snapshot).length > 0;
}
