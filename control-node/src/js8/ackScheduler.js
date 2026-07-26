// src/js8/ackScheduler.js

import { buildAckPayload, buildDirectedAckMessage } from "./ack.js";

/*
 * Delayed ACK scheduler
 *
 * Why this exists:
 * The remote node may still be busy finishing its own JS8Call transmission
 * sequence when the control node first decodes the BearWave frame. If the
 * control node responds immediately, the remote node may miss the ACK.
 *
 * To improve reliability, we deliberately delay the ACK so it lands in the
 * remote node's receive window rather than during the tail end of its own
 * transmit activity.
 *
 * ACK payload note:
 * The BearWave ACK payload uses the compact form:
 *
 *   A|<node>|<message_id>
 *
 * Example:
 *
 *   A|ND01|7K
 *
 * Shared-callsign note:
 * ND01, ND02, ND03, etc. are BearWave node IDs. They are not JS8Call
 * callsigns. Therefore this scheduler must not fall back to using the node ID
 * as the JS8Call destination.
 *
 * Instead, the ACK is wrapped as a directed JS8Call message to the configured
 * transport callsign:
 *
 *   G7PRW: A|ND01|7K
 *
 * Bench-testing logging note:
 * The structured UTC log fields in this module exist so the control-node
 * timeline can be aligned precisely with the remote-node timeline during
 * bench testing. This is diagnostics only and does not change protocol logic.
 */
export class AckScheduler {
  constructor({ js8Client, logger, config }) {
    this.js8Client = js8Client;
    this.logger = logger;
    this.config = config;
    this.scheduledAcks = new Map();
    this.recentlyHandled = new Map();
  }

  scheduleAck({
    nodeId,
    messageId,
    messageType,
    fullPayload,
    validatedAt,
    js8Context
  }) {
    const key = this.#makeKey(nodeId, messageId);
    const now = Date.now();

    this.#cleanupOldEntries(now);

    if (this.scheduledAcks.has(key)) {
      const eventUtc = this.#utcNow();

      console.log(
        `[ACK] Suppressed duplicate schedule for ${nodeId}/${messageId} ` +
        `(already scheduled)`
      );

      this.logger.write({
        event: "BW_ACK_DUP_SUPPRESSED",
        eventUtc,
        reason: "already_scheduled",
        nodeId,
        messageId,
        messageType,
        fullPayload,
        js8Context,
        validatedAt
      });

      return {
        scheduled: false,
        reason: "already_scheduled"
      };
    }

    const recent = this.recentlyHandled.get(key);

    if (
      recent &&
      now - recent.handledAt < this.config.ack.duplicateSuppressionMs
    ) {
      const eventUtc = this.#utcNow();

      console.log(
        `[ACK] Suppressed duplicate schedule for ${nodeId}/${messageId} ` +
        `(within suppression window)`
      );

      this.logger.write({
        event: "BW_ACK_DUP_SUPPRESSED",
        eventUtc,
        reason: "within_duplicate_suppression_window",
        nodeId,
        messageId,
        messageType,
        fullPayload,
        js8Context,
        validatedAt,
        duplicateSuppressionMs: this.config.ack.duplicateSuppressionMs
      });

      return {
        scheduled: false,
        reason: "within_duplicate_suppression_window"
      };
    }

    const destinationCallsign = this.#getDestinationCallsign(nodeId);
    const ackPayload = buildAckPayload(nodeId, messageId);
    const directedMessage = buildDirectedAckMessage(
      destinationCallsign,
      ackPayload
    );

    const scheduledAtMs = now;
    const sendAtMs = scheduledAtMs + this.config.ack.delayMs;

    console.log(
      `[ACK] Scheduled ${nodeId}/${messageId} for ` +
      `${new Date(sendAtMs).toISOString()} ` +
      `(delay ${this.config.ack.delayMs} ms) -> ${directedMessage}`
    );

    const timer = setTimeout(() => {
      this.#sendScheduledAck({
        key,
        nodeId,
        messageId,
        messageType,
        fullPayload,
        validatedAt,
        scheduledAtMs,
        destinationCallsign,
        ackPayload,
        directedMessage,
        js8Context
      });
    }, this.config.ack.delayMs);

    this.scheduledAcks.set(key, {
      timer,
      scheduledAtMs
    });

    this.recentlyHandled.set(key, {
      handledAt: scheduledAtMs
    });

    this.logger.write({
      event: "BW_ACK_SCHEDULED",
      eventUtc: new Date(scheduledAtMs).toISOString(),
      validatedAt,
      nodeId,
      messageId,
      messageType,
      fullPayload,
      js8Context,
      ackDelayMs: this.config.ack.delayMs,
      duplicateSuppressionMs: this.config.ack.duplicateSuppressionMs,
      destinationCallsign,
      ackPayload,
      directedMessage,
      sendTargetAt: new Date(sendAtMs).toISOString()
    });

    return {
      scheduled: true,
      reason: "scheduled",
      destinationCallsign,
      ackPayload,
      directedMessage
    };
  }

  #sendScheduledAck({
    key,
    nodeId,
    messageId,
    messageType,
    fullPayload,
    validatedAt,
    scheduledAtMs,
    destinationCallsign,
    ackPayload,
    directedMessage,
    js8Context
  }) {
    this.scheduledAcks.delete(key);

    const sendAttemptAtMs = Date.now();
    const handoffUtc = new Date(sendAttemptAtMs).toISOString();

    console.log(
      `[ACK] Sending ${nodeId}/${messageId} at ${handoffUtc} ` +
      `-> ${directedMessage}`
    );

    let success = false;
    let errorMessage = null;

    try {
      success = this.js8Client.send(directedMessage);

      if (!success) {
        errorMessage = "js8_send_returned_false";
      }
    } catch (err) {
      success = false;
      errorMessage = err?.message || String(err);
    }

    this.recentlyHandled.set(key, {
      handledAt: sendAttemptAtMs
    });

    this.logger.write({
      event: "BW_ACK_TX_HANDOFF",
      eventUtc: handoffUtc,
      validatedAt,
      nodeId,
      messageId,
      messageType,
      fullPayload,
      js8Context,
      scheduledAt: new Date(scheduledAtMs).toISOString(),
      ackDelayMs: this.config.ack.delayMs,
      destinationCallsign,
      ackPayload,
      directedMessage,
      success,
      error: errorMessage
    });

    if (success) {
      console.log(`[ACK] JS8Call handoff succeeded for ${nodeId}/${messageId}`);

      this.logger.write({
        event: "BW_ACK_TX_OK",
        eventUtc: handoffUtc,
        nodeId,
        messageId,
        messageType,
        ackPayload,
        directedMessage
      });
    } else {
      console.log(
        `[ACK] JS8Call handoff FAILED for ${nodeId}/${messageId}: ` +
        `${errorMessage}`
      );

      this.logger.write({
        event: "BW_ACK_TX_FAIL",
        eventUtc: handoffUtc,
        nodeId,
        messageId,
        messageType,
        ackPayload,
        directedMessage,
        error: errorMessage
      });
    }
  }

  #getDestinationCallsign(nodeId) {
    /*
     * Do not fall back to the BearWave node ID as a JS8Call destination.
     *
     * In the shared-callsign model:
     *
     *   ND01 / ND02 / ND03 = BearWave application-layer node identities
     *   G7PRW              = JS8Call transport callsign
     *
     * Therefore the ACK destination must come from:
     *
     *   1. the optional per-node callsign map, or
     *   2. the configured shared default destination callsign.
     */
    return (
      this.config.ack.nodeCallsigns[nodeId] ||
      this.config.ack.defaultDestinationCallsign
    );
  }

  #makeKey(nodeId, messageId) {
    return `${nodeId}::${messageId}`;
  }

  #cleanupOldEntries(now) {
    for (const [key, value] of this.recentlyHandled.entries()) {
      if (now - value.handledAt > this.config.ack.duplicateSuppressionMs) {
        this.recentlyHandled.delete(key);
      }
    }
  }

  #utcNow() {
    return new Date().toISOString();
  }
}