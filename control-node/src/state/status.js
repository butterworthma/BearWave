export function calculateNodeHealth(lastHeard, intervalMs, graceMs) {
  if (!lastHeard) return "red";

  const age = Date.now() - lastHeard;

  /*
   * Green: message arrived inside the expected heartbeat interval plus grace.
   * Yellow: late enough to warn the operator, but not yet considered lost.
   * Red: no recent contact or no message has ever been received.
   */
  if (age < intervalMs + graceMs) return "green";
  if (age < intervalMs * 2) return "yellow";
  return "red";
}

export function msToHuman(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "0s";

  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  const parts = [];
  if (hours) parts.push(`${hours}h`);
  if (minutes) parts.push(`${minutes}m`);
  if (seconds || parts.length === 0) parts.push(`${seconds}s`);
  return parts.join(" ");
}
