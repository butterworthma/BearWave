// config/default.js

/*
 * Bench-testing note:
 * Keep these timing values short while proving the ACK timing behaviour.
 * Once bench testing is complete, increase ACK_DELAY_MS as needed for the
 * remote node receive window you observe in practice.
 */
const HEARTBEAT_INTERVAL_MINUTES = 5;
const HEARTBEAT_GRACE_MINUTES = 1;

/*
 * This is the key tuning value requested for delayed acknowledgements.
 * The control node will wait this long after validating a BearWave frame
 * before handing the ACK to JS8Call for transmission.
 *
 * Initial test default:
 * 12000 ms = 12 seconds
 */
export const ACK_DELAY_MS = 12000;

/*
 * Suppress repeat ACK scheduling for the same BearWave message for a short
 * period so that repeated decodes or retries do not flood the channel.
 */
export const ACK_DUPLICATE_SUPPRESSION_MS = 120000;

export default {
  web: {
    port: Number(process.env.PORT || 3000)
  },

  js8call: {
    host: process.env.JS8CALL_HOST || "127.0.0.1",
    port: Number(process.env.JS8CALL_PORT || 2442),
    simulate: process.env.SIMULATE_JS8 === "1"
  },

  heartbeat: {
    intervalMs: HEARTBEAT_INTERVAL_MINUTES * 60 * 1000,
    graceMs: HEARTBEAT_GRACE_MINUTES * 60 * 1000
  },

  alerts: {
    soundEnabled: true
  },

  logging: {
    file: "./logs/events.log"
  },

  images: {
    directory: process.env.BEARWAVE_SSTV_IMAGE_DIR || "./sstv-images/inbox",
    publicUrlBase: "/sstv-images",
    associationWindowMs: Number(
      process.env.BEARWAVE_SSTV_ASSOCIATION_WINDOW_MS || 10 * 60 * 1000
    )
  },

  ack: {
    delayMs: ACK_DELAY_MS,
    duplicateSuppressionMs: ACK_DUPLICATE_SUPPRESSION_MS,

    /*
     * Callsign used for directed JS8Call ACKs when several BearWave nodes are
     * operating under the same licensed station callsign.
     *
     * The BearWave node identity is NOT taken from the JS8Call callsign. It is
     * taken from the application-layer payload field:
     *
     *   BW1|<nodeId>|<type>|<messageId>|<flags>|<data>
     *
     * Example remote-node transmission:
     *
     *   G7PRW: BW1|ND01|HB|7K|0|B72
     *
     * Example control-node ACK:
     *
     *   G7PRW: A|ND01|7K
     */
    defaultDestinationCallsign: process.env.BEARWAVE_REMOTE_CALLSIGN || "G7PRW",

    /*
     * Optional per-node override map.
     *
     * For the shared-callsign deployment model, every node can map to the same
     * transport callsign. The ACK remains node-specific because the compact ACK
     * includes the BearWave node ID and message ID.
     */
    nodeCallsigns: {
      ND01: process.env.BEARWAVE_ND01_CALLSIGN || "G7PRW",
      ND02: process.env.BEARWAVE_ND02_CALLSIGN || "G7PRW",
      ND03: process.env.BEARWAVE_ND03_CALLSIGN || "G7PRW"
    }
  }
};
