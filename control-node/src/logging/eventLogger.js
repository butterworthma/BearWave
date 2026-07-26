import fs from "fs";
import path from "path";

export class EventLogger {
  constructor(logFile) {
    this.logFile = logFile;
    this.ensureDirectoryExists();
  }

  ensureDirectoryExists() {
    const dir = path.dirname(this.logFile);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
  }

  write(event) {
    /*
     * JSON-lines keeps the log both machine-readable and easy to tail on the Pi.
     * Each line is independent, so partial corruption does not invalidate the
     * whole file.
     */
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      ...event
    }) + "\n";

    fs.appendFileSync(this.logFile, line, "utf8");
  }
}
