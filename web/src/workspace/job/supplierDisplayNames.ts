/** Demo / ERP segment ids → short labels for tabs (POC procurement pack). */
const SUPPLIER_SHORT: Record<string, string> = {
  "SUP-11564": "Rawabi",
  "SUP-11836": "Tamkeen",
  "SUP-12448": "Peninsula",
};

export function supplierShortName(supplierId: string | undefined | null): string | null {
  if (!supplierId?.trim()) return null;
  return SUPPLIER_SHORT[supplierId.trim()] ?? null;
}
