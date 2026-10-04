import { useState } from "react";
import type { ReactNode } from "react";

export function ActivatedPanel({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [activated, setActivated] = useState(false);
  const toggle = () => {
    setActivated(true);
    setOpen(value => !value);
  };
  // Closing a panel hides its mounted children, preserving their local drafts.
  return <div>
    <button type="button" aria-expanded={open} onClick={toggle}>{open ? "收起" : "打开"}{label}</button>
    {activated && <div hidden={!open}>{children}</div>}
  </div>;
}
