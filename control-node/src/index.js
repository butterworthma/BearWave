// src/index.js

import "dotenv/config";

import config from "../config/default.js";
import { parseBearWaveMessage } from "./protocol/parser.js";
import { NodeStore } from "./state/nodeStore.js";
import { EventLogger } from "./logging/eventLogger.js";
import { JS8Client } from "./js8/client.js";
import { createHttpServer } from "./server/httpServer.js";
import { createSocketServer } from "./server/socketServer.js";
import { ActivityAssembler } from "./js8/activityAssembler.js";
import { AckScheduler } from "./js8/ackScheduler.js";
import { ImageStore } from "./images/imageStore.js";

const nodeStore = new NodeStore(config);
const logger = new EventLogger(config.logging.file);
const assembler = new ActivityAssembler();

/*
 * ImageStore watches the folder populated by QSSTV. This keeps the control
 * application independent of the SSTV decoder: QSSTV handles audio/image
 * decoding, while BearWave only displays and associates decoded files.
 */
const imageStore = new ImageStore({
  directory: config.images.directory,
  publicUrlBase: config.images.publicUrlBase,
  logger
});

const app = createHttpServer(nodeStore, logger, config, imageStore);
const { server, io } = createSocketServer(app);

const js8 = new JS8Client({
  host: config.js8call.host,
  port: config.js8call.port,
  simulate: config.js8call.simulate,
  logger,

  onOpen: () => {
    const modeMessage = config.js8call.simulate
      ? "Running in simulator mode"
      : "Connected to JS8Call";

    console.log(modeMessage);

    logger.write({
      event: config.js8call.simulate ? "simulator_started" : "js8_connected",
      eventUtc: new Date().toISOString()
    });
  },

  onError: (err) => {
    const message = err?.message || String(err);
    console.error("JS8Call error:", message);

    logger.write({
      event: "js8_error",
      eventUtc: new Date().toISOString(),
      error: message
    });
  },

  onMessage: (rawText) => {
    /*
     * Keep raw logging during bench testing so the full JS8 timeline can be
     * cross-correlated against the BearWave-specific structured events below.
     */
    console.log("RAW JS8 MESSAGE:", rawText);

    logger.write({
      event: "raw_js8_message",
      eventUtc: new Date().toISOString(),
      raw: rawText
    });

    const assembled = assembler.ingest(rawText);

    if (!assembled) {
      return;
    }

    /*
     * At this point ActivityAssembler has converted one or more JS8Call
     * RX.ACTIVITY fragments into a single BearWave payload. Everything below
     * works at the BearWave application layer rather than the JS8 text layer.
     */
    const assembledAt = new Date().toISOString();

    console.log("ASSEMBLED BEARWAVE PAYLOAD:", assembled.payload);

    logger.write({
      event: "BW_RX_ASSEMBLED",
      eventUtc: assembledAt,
      fullPayload: assembled.payload,
      js8Context: assembled.js8Context
    });

    const msg = parseBearWaveMessage(assembled.payload);

    if (!msg) {
      logger.write({
        event: "bearwave_parse_failed",
        eventUtc: new Date().toISOString(),
        payload: assembled.payload,
        js8Context: assembled.js8Context
      });
      return;
    }

    const validatedAt = new Date().toISOString();
    const node = nodeStore.updateFromMessage(msg);

    logger.write({
      event: "BW_RX_VALID",
      eventUtc: validatedAt,
      nodeId: msg.node,
      messageId: msg.id,
      messageType: msg.type,
      fullPayload: msg.raw,
      flags: msg.flags,
      telemetry: msg.telemetry,
      js8Context: assembled.js8Context
    });

    /*
     * Do not ACK immediately.
     *
     * The delayed ACK exists because the remote node may still be occupied
     * finishing its own JS8Call transmit sequence when we first decode the
     * BearWave frame. Scheduling the ACK slightly later improves the chance
     * that the ACK lands during the node's receive window.
     *
     * Logging note:
     * The structured UTC timestamps carried through this call are intended to
     * align the control-node and remote-node timelines during bench testing.
     */
    ackScheduler.scheduleAck({
      nodeId: msg.node,
      messageId: msg.id,
      messageType: msg.type,
      fullPayload: msg.raw,
      validatedAt,
      js8Context: assembled.js8Context
    });

    io.emit("node_update", nodeStore.get(msg.node));
    io.emit("event", {
      ts: new Date().toISOString(),
      text: `${msg.node} ${msg.type} ${msg.id} received; delayed ACK scheduled`
    });

    if (node.alarmActive) {
      io.emit("alarm", {
        nodeId: node.nodeId,
        messageType: msg.type,
        messageId: msg.id
      });
    }
  }
});

const ackScheduler = new AckScheduler({
  js8Client: js8,
  logger,
  config
});

imageStore.start({
  onImage: (image) => {
    /*
     * SSTV images are not guaranteed. When one does decode successfully, attach
     * it to the newest alarm that is waiting for a picture and then push the
     * update to any open dashboard screens.
     */
    const updatedNode = nodeStore.attachImageToRecentAlarm(image);

    io.emit("sstv_image", image);

    if (updatedNode) {
      logger.write({
        event: "sstv_image_linked",
        eventUtc: new Date().toISOString(),
        nodeId: updatedNode.nodeId,
        messageId: updatedNode.latestAlarmMessageId,
        image
      });

      io.emit("node_update", updatedNode);
      io.emit("event", {
        ts: new Date().toISOString(),
        text: `SSTV image linked to ${updatedNode.nodeId}`
      });
    } else {
      io.emit("event", {
        ts: new Date().toISOString(),
        text: `SSTV image received: ${image.filename}`
      });
    }
  }
});

js8.connect();

setInterval(() => {
  /*
   * Heartbeat health depends on wall-clock age, not only on new messages. This
   * periodic refresh lets a node move from healthy to missing on the screen even
   * when the RF channel is quiet.
   */
  nodeStore.refreshAllHealth();
  io.emit("nodes_snapshot", nodeStore.getAll());
}, 3000);

server.listen(config.web.port, () => {
  console.log(`BearWave control node UI running on http://localhost:${config.web.port}`);
});
