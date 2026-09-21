// Minimal OTA responder for xiaozhi-esp32 devices whose firmware hardcodes the
// old server address. The device only ever asks this host for OTA, so we answer
// with the address of the machine that actually runs the voice pipeline.
//
//   XZ_WS_URL  websocket URL the device should connect to (default ws://<host>:18000/xiaozhi/v1/)
//   XZ_OTA_PORT listen port (default 18003)
const http = require("http");

const WS = process.env.XZ_WS_URL || "ws://192.168.31.20:18000/xiaozhi/v1/";
const PORT = Number(process.env.XZ_OTA_PORT || 18003);

const srv = http.createServer((req, res) => {
  const ip = (req.headers["x-forwarded-for"] || req.socket.remoteAddress || "").toString();
  console.log(new Date().toISOString(), req.method, req.url, "from", ip);
  if (req.method === "POST" && req.url.startsWith("/xiaozhi/ota")) {
    const body = JSON.stringify({
      server_time: { timestamp: Date.now(), timezone_offset: 480 },
      firmware: { version: "1.0.0", url: "" },
      websocket: { url: WS, token: "" },
    });
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(body);
    return;
  }
  res.writeHead(404);
  res.end();
});

srv.listen(PORT, "0.0.0.0", () => console.log("xz-ota listening on", PORT, "->", WS));
