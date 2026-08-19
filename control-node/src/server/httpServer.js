import express from "express";
import { execFile } from "child_process";
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

function runCommand(command, args = [], options = {}) {
  return new Promise((resolve, reject) => {
    execFile(command, args, {
      timeout: options.timeout || 8000,
      env: {
        ...process.env,
        DISPLAY: process.env.DISPLAY || ":0",
        XAUTHORITY: process.env.XAUTHORITY || "/home/mark/.Xauthority"
      }
    }, (error, stdout, stderr) => {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

async function controlDashboardWindow(action) {
  /*
   * A web page cannot reliably minimise or close the Chromium kiosk window by
   * itself. The local server can ask the Pi window manager to do it, using only
   * these whitelisted actions.
   */
  const scripts = {
    minimize: "command -v wmctrl >/dev/null 2>&1 && wmctrl -r ':ACTIVE:' -b add,hidden || { command -v xdotool >/dev/null 2>&1 && xdotool getactivewindow windowminimize; }",
    maximize: "command -v wmctrl >/dev/null 2>&1 && wmctrl -r ':ACTIVE:' -b add,maximized_vert,maximized_horz || { command -v xdotool >/dev/null 2>&1 && xdotool getactivewindow windowsize 100% 100%; }",
    close: "command -v wmctrl >/dev/null 2>&1 && wmctrl -c 'BearWave Control Node' || { command -v xdotool >/dev/null 2>&1 && xdotool getactivewindow windowclose; }"
  };

  if (!scripts[action]) {
    const err = new Error("Unknown window action");
    err.statusCode = 400;
    throw err;
  }

  return runCommand("/bin/sh", ["-lc", scripts[action]], { timeout: 5000 });
}

async function readGpsUtcTime() {
  let stdout = "";
  try {
    const result = await runCommand("gpspipe", ["-w", "-n", "20"], { timeout: 10000 });
    stdout = result.stdout;
  } catch (err) {
    if (err.code === "ENOENT") throw err;
    return null;
  }

  for (const line of stdout.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const msg = JSON.parse(line);
      if (msg.class === "TPV" && msg.time && Number(msg.mode || 0) >= 2) {
        return msg.time;
      }
    } catch (_err) {
      /* gpspipe can emit non-JSON status text during startup; ignore it. */
    }
  }
  return null;
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
    const removed = nodeStore.removeNode(req.params.id);
    if (!removed) return res.status(404).json({ error: "Node not found" });

    logger.write({
      event: "node_cleared_from_dashboard",
      node: req.params.id
    });

    res.json({ ok: true, nodeId: req.params.id });
  });

  app.post("/api/window/:action", async (req, res) => {
    try {
      await controlDashboardWindow(req.params.action);
      logger.write({
        event: "dashboard_window_action",
        action: req.params.action,
        eventUtc: new Date().toISOString()
      });
      res.json({ ok: true, action: req.params.action });
    } catch (err) {
      const status = err.statusCode || (err.code === 127 ? 501 : 500);
      res.status(status).json({
        ok: false,
        action: req.params.action,
        error: err.stderr?.trim() || err.message || "Window action failed"
      });
    }
  });

  app.post("/api/time/resync", async (req, res) => {
    try {
      const gpsTime = await readGpsUtcTime();
      if (!gpsTime) {
        res.status(503).json({
          ok: false,
          error: "No valid GPS UTC fix is available."
        });
        return;
      }

      /*
       * Setting the system clock requires a sudoers rule for the dashboard
       * service user. Without it, the endpoint reports the failure instead of
       * pretending the clock was changed.
       */
      await runCommand("sudo", ["-n", "date", "-u", "-s", gpsTime], { timeout: 8000 });
      logger.write({
        event: "control_node_time_resynced_from_gps",
        eventUtc: new Date().toISOString(),
        gpsTime
      });
      res.json({ ok: true, gpsTime });
    } catch (err) {
      res.status(err.code === "ENOENT" ? 501 : 500).json({
        ok: false,
        error: err.code === "ENOENT"
          ? "gpspipe is not installed or not on PATH."
          : (err.stderr?.trim() || err.message || "GPS time resync failed.")
      });
    }
  });

  return app;
}
