import { useEffect, useState } from "react";

export type Route = { page: string; params: URLSearchParams };

function parse(): Route {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [path, query = ""] = raw.split("?");
  return { page: path || "library", params: new URLSearchParams(query) };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const onChange = () => setRoute(parse());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function href(page: string, params: Record<string, string | undefined> = {}): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) p.set(k, v);
  const s = p.toString();
  return `#/${page}${s ? `?${s}` : ""}`;
}

export function navigate(page: string, params: Record<string, string | undefined> = {}) {
  window.location.hash = href(page, params);
}
