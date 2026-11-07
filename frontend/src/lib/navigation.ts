import type { MouseEvent } from "react";

/** Preserve mounted conversations when navigating within the workspace. */
export function navigate(event: MouseEvent<HTMLAnchorElement>) {
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const to = new URL(event.currentTarget.href);
  if (to.pathname === window.location.pathname) return;
  event.preventDefault();
  history.pushState(null, "", to.pathname + to.search + to.hash);
  window.scrollTo(0, 0);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
