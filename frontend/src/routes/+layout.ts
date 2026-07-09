// SPA mode: the app talks to the FastAPI backend at runtime; nothing is
// prerendered at build time and there is no node server in production.
export const ssr = false;
export const prerender = false;
