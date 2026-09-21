// OTA responder + WebSocket TCP proxy for a device whose firmware hardcodes the
// old server host. The device talks only to this host; we answer OTA with a url
// on the same host and forward that port straight to the machine running the
// voice pipeline (a device that compares OTA host with ws host will refuse a
// cross-host OTA answer, so same-host proxying is the safe path).
//
//   XZ_PUBLIC_HOST  host the device should reach (default 192.168.31.20)
//   XZ_OTA_PORT     OTA port (default 18003)
//   XZ_WS_PORT      proxied websocket port (default 18000)
//   XZ_UPSTREAM     upstream host:port running xiaozhi server (default 192.168.31.68:8000)
const http = require("http");
const net = require("net");

const PUBLIC_HOST = process.env.XZ_PUBLIC_HOST || "192.168.31.20";
const OTA_PORT = Number(process.env.XZ_OTA_PORT || 18003);
const WS_PORT = Number(process.env.XZ_WS_PORT || 18000);
const [UP_HOST, UP_PORT] = (process.env.XZ_UPSTREAM || "192.168.31.68:8000").split(":");
const WS = `ws://${PUBLIC_HOST}:${WS_PORT}/xiaozhi/v1/`;

http
  .createServer((req, res) => {
    const ip = (req.socket.remoteAddress || "").toString();
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      console.log(new Date().toISOString(), "OTA", req.method, req.url, "from", ip, "body:", raw.slice(0, 2000));
      // Echo the device's own firmware version back: some firmwares treat a
      // lower version as "upgrade required" and never open the websocket.
      let ver = "1.4.7";
      try {
        ver = JSON.parse(raw).application.version || ver;
      } catch (e) {}
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          server_time: { timestamp: Date.now(), timezone_offset: 480 },
          firmware: { version: ver, url: "" },
          websocket: { url: WS, token: "" },
        })
      );
    });
  })
  .listen(OTA_PORT, "0.0.0.0", () => console.log("OTA on", OTA_PORT, "->", WS));

net
  .createServer((client) => {
    const up = net.connect(Number(UP_PORT), UP_HOST);
    console.log(new Date().toISOString(), "WS proxy", client.remoteAddress, "->", UP_HOST + ":" + UP_PORT);
    client.pipe(up);
    up.pipe(client);
    const bye = () => {
      client.destroy();
      up.destroy();
    };
    client.on("error", bye);
    up.on("error", bye);
  })
  .listen(WS_PORT, "0.0.0.0", () => console.log("WS TCP proxy on", WS_PORT, "->", UP_HOST + ":" + UP_PORT));
