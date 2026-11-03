import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";

const DEFAULT_VERSION = "1.8.0.dev2";

export function VersionFooter() {
  const [version, setVersion] = useState(DEFAULT_VERSION);

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ version?: string }>("/health")
      .then((health) => {
        if (!cancelled && health.version) setVersion(health.version);
      })
      .catch(() => {
        if (!cancelled) setVersion(DEFAULT_VERSION);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <span className="truncate">Townlight Records v{version} &middot; AGPL-3.0</span>;
}
