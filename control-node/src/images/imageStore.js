import fs from "fs";
import path from "path";

const IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png", ".bmp", ".gif"]);

/*
 * Watches the folder where QSSTV saves decoded pictures.
 *
 * QSSTV is intentionally treated as the decoder of truth: this class does not
 * attempt to understand SSTV audio. It only notices complete image files,
 * exposes them through the web server, and tells NodeStore that a new picture
 * may belong to a recent alarm.
 */
export class ImageStore {
  constructor({ directory, publicUrlBase = "/sstv-images", logger }) {
    this.directory = directory;
    this.publicUrlBase = publicUrlBase.replace(/\/$/, "");
    this.logger = logger;
    this.images = new Map();
    this.watchHandle = null;
    this.scanTimer = null;
  }

  ensureDirectory() {
    fs.mkdirSync(this.directory, { recursive: true });
  }

  start({ onImage } = {}) {
    this.ensureDirectory();
    this.scan(onImage);

    /*
     * fs.watch is fast but not perfectly reliable across filesystems and
     * desktop environments. The periodic scan below is a simple belt-and-braces
     * check so a missed filesystem event does not hide a received image.
     */
    this.watchHandle = fs.watch(this.directory, () => {
      setTimeout(() => this.scan(onImage), 500);
    });

    this.scanTimer = setInterval(() => this.scan(onImage), 10000);
  }

  stop() {
    this.watchHandle?.close();
    this.watchHandle = null;

    if (this.scanTimer) {
      clearInterval(this.scanTimer);
      this.scanTimer = null;
    }
  }

  scan(onImage) {
    this.ensureDirectory();
    const entries = fs.readdirSync(this.directory, { withFileTypes: true });

    for (const entry of entries) {
      if (!entry.isFile()) continue;

      const ext = path.extname(entry.name).toLowerCase();
      if (!IMAGE_EXTENSIONS.has(ext)) continue;

      const fullPath = path.join(this.directory, entry.name);
      const stat = fs.statSync(fullPath);
      const id = entry.name;

      /*
       * The filename is the stable ID. QSSTV writes each received image as a new
       * file, and repeated scans must not re-emit the same image to the UI.
       */
      if (this.images.has(id)) continue;

      const image = {
        id,
        filename: entry.name,
        path: fullPath,
        url: `${this.publicUrlBase}/${encodeURIComponent(entry.name)}`,
        receivedAt: stat.mtimeMs,
        receivedAtIso: new Date(stat.mtimeMs).toISOString(),
        sizeBytes: stat.size
      };

      this.images.set(id, image);
      this.logger?.write({
        event: "sstv_image_detected",
        eventUtc: new Date().toISOString(),
        image
      });

      onImage?.(image);
    }
  }

  getAll() {
    return Array.from(this.images.values())
      .sort((a, b) => b.receivedAt - a.receivedAt);
  }

  getLatest() {
    return this.getAll()[0] || null;
  }
}
