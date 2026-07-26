// src/js8/activityAssembler.js

/*
 * Activity assembler
 *
 * JS8Call often delivers one on-air BearWave message as several RX.ACTIVITY
 * fragments. Real RF timing can place those fragments tens of seconds apart,
 * so this helper keeps a short-lived receive buffer and extracts the first
 * complete BearWave payload once all fields are present.
 */
export class ActivityAssembler {
  constructor({ maxAgeMs = 60000 } = {}) {
    this.maxAgeMs = maxAgeMs;
    this.buffer = "";
    this.lastUpdate = 0;
    this.lastContext = null;
  }

  ingest(rawLine) {
    let packet;

    try {
      packet = typeof rawLine === "string" ? JSON.parse(rawLine) : rawLine;
    } catch {
      return null;
    }

    if (!packet || packet.type !== "RX.ACTIVITY") {
      return null;
    }

    let text = typeof packet.value === "string" ? packet.value : "";
    if (!text) return null;

    const now = Date.now();

    if (now - this.lastUpdate > this.maxAgeMs) {
      this.buffer = "";
      this.lastContext = null;
    }

    this.lastUpdate = now;

    this.lastContext = {
      js8Type: packet.type || null,
      dial: packet?.params?.DIAL ?? null,
      freq: packet?.params?.FREQ ?? null,
      offset: packet?.params?.OFFSET ?? null,
      snr: packet?.params?.SNR ?? null,
      speed: packet?.params?.SPEED ?? null,
      tdrift: packet?.params?.TDRIFT ?? null,
      js8Utc: packet?.params?.UTC ?? null
    };

    text = text
      .replace(/[.????]/g, "")
      .replace(/^[A-Z0-9/]+:\s*/i, "")
      .replace(/\s+/g, " ")
      .trim();

    if (!text) return null;

    this.buffer += text;

    const bwIndex = this.buffer.indexOf("BW1|");
    if (bwIndex >= 0) {
      this.buffer = this.buffer.slice(bwIndex);
    } else if (this.buffer.length > 250) {
      this.buffer = this.buffer.slice(-120);
      return null;
    } else {
      return null;
    }

    const extracted = this.#extractBearWave(this.buffer);
    if (extracted) {
      const result = {
        payload: extracted,
        js8Context: this.lastContext
      };

      this.buffer = "";
      this.lastContext = null;

      return result;
    }

    return null;
  }

  #extractBearWave(text) {
    const match = text.match(
      /BW1\|([A-Za-z0-9]+)\|(HB|TA|LB|SR|FT)\|([A-Za-z0-9]+)\|([^|]+)\|((?:[A-Z][A-Za-z0-9.\-]+)(?:,[A-Z][A-Za-z0-9.\-]+)*)/
    );

    if (!match) return null;

    const [, node, type, id, flags, data] = match;
    return `BW1|${node}|${type}|${id}|${flags}|${data}`;
  }
}
