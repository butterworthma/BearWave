import { KNOWN_TYPES } from "./types.js";

export function parseBearWaveMessage(raw) {
  if (!raw || typeof raw !== "string") return null;

  const text = raw.trim();

  // Accept only BearWave payloads
  if (!text.startsWith("BW1|")) return null;

  const parts = text.split("|");
  if (parts.length < 6) return null;

  const [version, node, type, id, flags, ...rest] = parts;
  const data = rest.join("|"); // defensive, in case future payloads contain extra separators

  if (version !== "BW1") return null;
  if (!node || !type || !id) return null;
  if (!KNOWN_TYPES.has(type)) return null;

  return {
    version,
    node,
    type,
    id,
    flags: flags || "0",
    data: data || "0",
    telemetry: parseTelemetry(data || "0"),
    receivedAt: Date.now(),
    raw: text
  };
}

export function parseTelemetry(dataField) {
  if (!dataField || dataField === "0") return {};

  /*
   * Telemetry values are compact to keep JS8 messages short. Each item is a
   * single-letter key followed by its value, for example B72 for 72% battery or
   * V118 for 11.8 V. Unknown keys are preserved as raw_* fields so experiments
   * on the remote node do not require an immediate dashboard update.
   */
  const items = dataField.split(",");
  const telemetry = {};

  for (const item of items) {
    if (!item) continue;

    const key = item.charAt(0);
    const value = item.slice(1);

    switch (key) {
      case "B":
        telemetry.batteryPercent = safeNum(value);
        break;
      case "V":
        telemetry.batteryVoltage = safeNum(value) / 10;
        break;
      case "T":
        telemetry.temperatureC = safeNum(value);
        break;
      case "H":
        telemetry.humidity = safeNum(value);
        break;
      case "P":
        telemetry.pir = value === "1";
        break;
      case "R":
        telemetry.reed = value === "1";
        break;
      case "L":
        telemetry.light = safeNum(value);
        break;
      case "X":
        telemetry.faultCode = value;
        break;
      default:
        telemetry[`raw_${key}`] = value;
        break;
    }
  }

  return telemetry;
}

function safeNum(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}
