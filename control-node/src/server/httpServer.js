import express from "express";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function clampLimit(value, fallback = 80, max = 250) {
  const parsed = Number(value || fallback);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  return Math.min(max, Math.round(parsed));
}

function readTailText(filePath, maxBytes = 120000) {
  if (!filePath || !fs.existsSync(filePath)) return "";

  /*
   * The log view is intended for the Pi screen during field/bench testing. Read
   * only the tail so a long-running control node does not load a huge log file
   * into memory just to render the latest entries.
   */
  const stat = fs.statSync(filePath);
  const start = Math.max(0, stat.size - maxBytes);
  const fd = fs.openSync(filePath, "r");
  try {
    const buffer = Buffer.alloc(stat.size - start);
    fs.readSync(fd, buffer, 0, buffer.length, start);
    return buffer.toString("utf8");
  } finally {
    fs.closeSync(fd);
  }
}

function readRecentJsonLines(filePath, limit) {
  /*
   * The structured event log is JSON-lines. A corrupt or half-written line is
   * ignored so the dashboard remains usable while the process is actively
   * appending to the same file.
   */
  return readTailText(filePath)
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch (_err) {
        return null;
      }
    })
    .filter(Boolean)
    .slice(-limit)
    .reverse();
}

function readRecentLogLines(filePath, limit) {
  return readTailText(filePath)
    .split(/\r?\n/)
    .filter(Boolean)
    .slice(-limit);
}


export function createHttpServer(nodeStore, logger, config, imageStore) {
  const app = express();

  app.use(express.json());
  app.use(express.static(path.join(__dirname, "../ui/public")));

  /*
   * Expose QSSTV's received-image inbox under a web-safe URL. The dashboard
   * stores only URLs for thumbnails; the original image files remain in the
   * local inbox directory configured in config/default.js or .env.
   */
  app.use(
    config.images.publicUrlBase,
    express.static(config.images.directory)
  );

  app.get("/api/health", (req, res) => {
    res.json({
      ok: true,
      simulate: config.js8call.simulate
    });
  });

  app.get("/api/config", (req, res) => {
    res.json({
      heartbeat: config.heartbeat,
      alerts: config.alerts
    });
  });

  app.get("/api/nodes", (req, res) => {
    res.json(nodeStore.getAll());
  });

  app.get("/api/images", (req, res) => {
    res.json(imageStore?.getAll() || []);
  });

  app.get("/api/history", (req, res) => {
    const limit = clampLimit(req.query.limit, 100, 250);
    res.json(readRecentJsonLines(logger.logFile, limit));
  });

  app.get("/api/logs", (req, res) => {
    const limit = clampLimit(req.query.lines, 160, 300);

    /*
     * This endpoint tails the live process log used by the systemd/desktop
     * launch arrangement. The JSON event history is served separately via
     * /api/history.
     */
    const liveLog = path.join(process.cwd(), "logs", "control-node-live.log");
    res.json({
      file: liveLog,
      lines: readRecentLogLines(liveLog, limit)
    });
  });

  app.get("/api/nodes/:id", (req, res) => {
    const node = nodeStore.get(req.params.id);
    if (!node) return res.status(404).json({ error: "Node not found" });
    res.json(node);
  });

  app.post("/api/nodes/:id/ack-alarm", (req, res) => {
    const node = nodeStore.acknowledgeAlarm(req.params.id);
    if (!node) return res.status(404).json({ error: "Node not found" });

    logger.write({
      event: "alarm_acknowledged_locally",
      node: req.params.id
    });

    res.json(nodeStore.get(req.params.id));
  });

  app.post("/api/nodes/:id/clear-alarm", (req, res) => {
    const node = nodeStore.clearAlarm(req.params.id);
    if (!node) return res.status(404).json({ error: "Node not found" });

    logger.write({
      event: "alarm_cleared_locally",
      node: req.params.id
    });

    res.json(nodeStore.get(req.params.id));
  });

  return app;
}
