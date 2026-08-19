import { calculateNodeHealth } from "./status.js";

/*
 * NodeStore is the in-memory model behind the dashboard.
 *
 * It deliberately does not persist state to disk. BearWave nodes wake, report,
 * and sleep, so the freshest JS8Call messages and recently decoded SSTV images
 * are the useful operator view. The JSON event log remains the audit trail.
 */
export class NodeStore {
  constructor(config) {
    this.config = config;
    this.nodes = new Map();
  }

  updateFromMessage(msg) {
    const existing = this.nodes.get(msg.node) || this.#createNode(msg.node);

    /*
     * Every valid BearWave frame refreshes the node's heartbeat age, even if
     * the frame is not explicitly an HB message. Alarm and fault messages still
     * prove that the node was alive at this UTC receive time.
     */
    existing.lastHeard = msg.receivedAt;
    existing.lastMessageId = msg.id;
    existing.lastType = msg.type;
    existing.flags = msg.flags;
    existing.raw = msg.raw;
    existing.telemetry = { ...existing.telemetry, ...msg.telemetry };
    existing.lastUpdatedAt = Date.now();

    if (msg.type === "TA" || msg.flags.includes("T1")) {
      /*
       * SSTV is best-effort and arrives after the JS8 alarm. We therefore mark
       * the node as "waiting" and allow the image watcher a short association
       * window to link the next decoded image back to this alarm.
       */
      existing.alarmActive = true;
      existing.alarmAcknowledged = false;
      existing.latestAlarmMessageId = msg.id;
      existing.latestAlarmAt = msg.receivedAt;
      existing.sstvImageStatus = "waiting";
      existing.sstvImageExpectedAt = Date.now();
      existing.sstvImageWindowUntil =
        Date.now() + (this.config.images?.associationWindowMs || 10 * 60 * 1000);
    }

    if (msg.type === "LB" || msg.flags.includes("L1")) {
      existing.lowBattery = true;
    }

    if (msg.type === "FT") {
      existing.faultActive = true;
    }

    existing.health = this.#calculate(existing);
    this.nodes.set(msg.node, existing);
    return existing;
  }

  refreshAllHealth() {
    for (const node of this.nodes.values()) {
      node.health = this.#calculate(node);
      node.ageMs = Date.now() - (node.lastHeard || 0);
      this.#refreshImageStatus(node);
    }
  }

  attachImageToRecentAlarm(image) {
    const now = Date.now();

    /*
     * Images decoded by QSSTV do not contain the BearWave message ID, so the
     * safest automatic association is temporal: link the newest decoded image
     * to the most recent active alarm that is still waiting for a picture.
     */
    const candidates = Array.from(this.nodes.values())
      .filter((node) => node.alarmActive)
      .filter((node) => node.sstvImageStatus === "waiting")
      .filter((node) => (node.sstvImageWindowUntil || 0) >= now)
      .sort((a, b) => (b.latestAlarmAt || 0) - (a.latestAlarmAt || 0));

    const node = candidates[0];
    if (!node) return null;

    node.latestImage = {
      ...image,
      linkedNodeId: node.nodeId,
      linkedMessageId: node.latestAlarmMessageId || null,
      linkedAt: new Date().toISOString()
    };
    node.sstvImageStatus = "received";
    node.sstvImageReceivedAt = image.receivedAt;
    node.lastUpdatedAt = Date.now();

    return this.get(node.nodeId);
  }

  acknowledgeAlarm(nodeId) {
    const node = this.nodes.get(nodeId);
    if (!node) return null;
    node.alarmAcknowledged = true;
    node.lastUpdatedAt = Date.now();
    return node;
  }

  clearAlarm(nodeId) {
    const node = this.nodes.get(nodeId);
    if (!node) return null;
    node.alarmActive = false;
    node.alarmAcknowledged = false;
    node.sstvImageStatus = "idle";
    node.sstvImageExpectedAt = null;
    node.sstvImageWindowUntil = null;
    node.lastUpdatedAt = Date.now();
    return node;
  }

  removeNode(nodeId) {
    return this.nodes.delete(nodeId);
  }

  clearLowBattery(nodeId) {
    const node = this.nodes.get(nodeId);
    if (!node) return null;
    node.lowBattery = false;
    return node;
  }

  getAll() {
    return Array.from(this.nodes.values())
      .map((node) => {
        this.#refreshImageStatus(node);
        return {
          ...node,
          ageMs: Date.now() - (node.lastHeard || 0),
          health: this.#calculate(node)
        };
      })
      .sort((a, b) => a.nodeId.localeCompare(b.nodeId));
  }

  get(nodeId) {
    const node = this.nodes.get(nodeId);
    if (!node) return null;
    this.#refreshImageStatus(node);

    return {
      ...node,
      ageMs: Date.now() - (node.lastHeard || 0),
      health: this.#calculate(node)
    };
  }

  #calculate(node) {
    return calculateNodeHealth(
      node.lastHeard,
      this.config.heartbeat.intervalMs,
      this.config.heartbeat.graceMs
    );
  }

  #createNode(nodeId) {
    return {
      nodeId,
      createdAt: Date.now(),
      lastHeard: null,
      lastMessageId: null,
      lastType: null,
      flags: "0",
      raw: null,
      telemetry: {},
      health: "red",
      alarmActive: false,
      alarmAcknowledged: false,
      lowBattery: false,
      faultActive: false,
      latestAlarmMessageId: null,
      latestAlarmAt: null,
      sstvImageStatus: "idle",
      sstvImageExpectedAt: null,
      sstvImageWindowUntil: null,
      sstvImageReceivedAt: null,
      latestImage: null,
      lastUpdatedAt: null
    };
  }

  #refreshImageStatus(node) {
    if (
      node.sstvImageStatus === "waiting" &&
      node.sstvImageWindowUntil &&
      Date.now() > node.sstvImageWindowUntil
    ) {
      /*
       * Missing does not mean the remote node failed to transmit. It only means
       * the control node did not decode a valid image inside the expected
       * window, which is normal for a best-effort SSTV path.
       */
      node.sstvImageStatus = "missing";
    }
  }
}
