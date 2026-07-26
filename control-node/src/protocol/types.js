export const MESSAGE_TYPES = {
  // HB keeps the node fresh on the dashboard.
  HEARTBEAT: "HB",
  // TA is the primary reliable alarm message that triggers the ACK path.
  TRAP_ALARM: "TA",
  // LB warns that the trap battery should be replaced on the next visit.
  LOW_BATTERY: "LB",
  // SR is general telemetry without declaring an alarm condition.
  SENSOR_REPORT: "SR",
  // FT reports a remote-node fault code.
  FAULT: "FT"
};

export const KNOWN_TYPES = new Set(Object.values(MESSAGE_TYPES));
