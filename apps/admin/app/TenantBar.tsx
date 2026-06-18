"use client";

import { useEffect, useState } from "react";
import { getTenant, setTenant } from "@/lib/api";

// Dev-mode tenant switcher: the API trusts X-Tenant unless CORTEX_AUTH_REQUIRED.
export function TenantBar() {
  const [tenant, setLocal] = useState("demo");

  useEffect(() => {
    setLocal(getTenant());
  }, []);

  function apply(value: string) {
    setLocal(value);
    setTenant(value);
  }

  return (
    <div className="row">
      <span className="muted">tenant</span>
      <input
        aria-label="tenant"
        value={tenant}
        onChange={(e) => apply(e.target.value)}
        style={{ width: 160 }}
      />
    </div>
  );
}
