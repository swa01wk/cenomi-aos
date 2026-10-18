import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router";

/** M0 used hash routes (#/console/packs). Send people to the real path once. */
export function hashRouteTarget(hash: string): string | null {
  const m = hash.match(/^#\/?(.*)$/);
  if (!m?.[1]) return null;
  return "/" + m[1].replace(/^\/+/, "");
}

export default function HashRedirect() {
  const { hash } = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const target = hashRouteTarget(hash);
    if (target) navigate(target, { replace: true });
  }, [hash, navigate]);

  return null;
}
