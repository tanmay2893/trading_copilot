/**
 * Standalone reverse proxy for exposing the app via ngrok.
 * Proxies HTTP to Next.js dev server and WebSocket to the backend.
 *
 * Default: proxy on 3080, Next on 3070 — so both can run without conflict.
 * Usage:  node proxy.js   then open http://localhost:3080 or ngrok http 3080
 */
const http = require("http");
const httpProxy = require("http-proxy");

const PROXY_PORT = parseInt(process.env.PROXY_PORT || "3080", 10);
const NEXT_URL = process.env.NEXT_URL || "http://localhost:3070";
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:6700";

const nextProxy = httpProxy.createProxyServer({
  target: NEXT_URL,
  ws: true,
  xfwd: true,
});
const backendProxy = httpProxy.createProxyServer({
  target: BACKEND_URL,
  ws: true,
  xfwd: true,
});

nextProxy.on("error", (err) => console.error("[next proxy]", err.message));
backendProxy.on("error", (err) => console.error("[backend proxy]", err.message));

const server = http.createServer((req, res) => {
  if (req.url && req.url.startsWith("/api/")) {
    backendProxy.web(req, res);
  } else {
    nextProxy.web(req, res);
  }
});

server.on("upgrade", (req, socket, head) => {
  if (req.url && req.url.startsWith("/ws/")) {
    backendProxy.ws(req, socket, head);
  } else {
    nextProxy.ws(req, socket, head);
  }
});

server.listen(PROXY_PORT, "0.0.0.0", () => {
  console.log(`Reverse proxy listening on http://localhost:${PROXY_PORT}`);
  console.log(`  HTTP  /api/* → ${BACKEND_URL}`);
  console.log(`  WS    /ws/*  → ${BACKEND_URL}`);
  console.log(`  All else     → ${NEXT_URL}`);
  console.log(`\nRun: ngrok http ${PROXY_PORT}`);
});
