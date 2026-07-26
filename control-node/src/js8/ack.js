// src/js8/ack.js

/*
 * Compact BearWave application-layer ACK payload.
 *
 * This was shortened from:
 *
 *   ACK|<node>|<message_id>|OK
 *
 * to:
 *
 *   A|<node>|<message_id>
 *
 * Reason:
 * The longer ACK was being fragmented on-air often enough that the remote
 * node sometimes received only the leading portion and rejected the ACK.
 * The shorter compact ACK reduces fragmentation risk on JS8 receive while
 * preserving the essential fields needed to validate the acknowledgement.
 */
export function buildAckPayload(nodeId, messageId) {
  return `A|${nodeId}|${messageId}`;
}

/*
 * JS8Call directed-message format.
 *
 * We keep proper transport-level addressing by sending the compact BearWave
 * ACK payload as a directed JS8Call message to the configured destination
 * callsign.
 *
 * In the shared-callsign deployment model, this may be:
 *
 *   G7PRW: A|ND01|JB
 *
 * Here:
 *
 *   G7PRW = licensed JS8Call transport callsign
 *   ND01  = BearWave application-layer node identity
 *   JB    = BearWave message identifier
 */
export function buildDirectedAckMessage(destinationCallsign, ackPayload) {
  return `${destinationCallsign}: ${ackPayload}`;
}