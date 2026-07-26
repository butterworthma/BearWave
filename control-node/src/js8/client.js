// src/js8/client.js

import net from "net";

export class JS8Client {
  constructor({
    host,
    port,
    simulate = false,
    onMessage,
    onOpen,
    onError,
    logger
  }) {
    this.host = host;
    this.port = port;
    this.simulate = simulate;
    this.onMessage = onMessage;
    this.onOpen = onOpen;
    this.onError = onError;
    this.logger = logger;
    this.socket = null;
    this.simTimer = null;
    this.simCounter = 0;
    this.buffer = "";
  }

  connect() {
    if (this.simulate) {
      this.#startSimulator();
      return;
    }

    /*
     * JS8Call exposes a simple TCP API. Keeping this client thin makes it easy
     * to diagnose whether a fault is in JS8Call/radio routing or in BearWave's
     * own parser and ACK scheduling.
     */
    this.socket = net.createConnection(
      {
        host: this.host,
        port: this.port
      },
      () => {
        this.onOpen?.();
      }
    );

    this.socket.on("data", (chunk) => {
      this.buffer += chunk.toString();

      /*
       * JS8Call API messages are commonly newline-delimited JSON/text.
       * We keep a small buffer so that partial TCP chunks are reassembled
       * before being handed to the higher-level receive logic.
       */
      let newlineIndex;

      while ((newlineIndex = this.buffer.indexOf("\n")) >= 0) {
        const line = this.buffer.slice(0, newlineIndex).trim();
        this.buffer = this.buffer.slice(newlineIndex + 1);

        if (line) {
          this.onMessage?.(line);
        }
      }
    });

    this.socket.on("error", (err) => {
      this.onError?.(err);
    });

    this.socket.on("close", () => {
      /*
       * The control node is intended to run unattended on the Pi screen. If
       * JS8Call is restarted or briefly crashes, reconnect automatically rather
       * than requiring keyboard access.
       */
      setTimeout(() => this.connect(), 3000);
    });
  }

  send(text) {
    if (this.simulate) {
      this.logger?.write({
        event: "simulated_send",
        payload: text
      });

      console.log("[JS8 SIM TX TEXT]", text);

      return true;
    }

    if (this.socket && !this.socket.destroyed) {
      /*
       * TX.SEND_MESSAGE is the JS8Call API command that asks JS8Call to queue a
       * normal outgoing text message. The ACK payload is already formatted as a
       * directed JS8 message by ack.js.
       */
      const message = JSON.stringify({
        type: "TX.SEND_MESSAGE",
        value: text,
        params: {
          _ID: String(Date.now())
        }
      });

      console.log("[JS8 TX TEXT]", text);
      console.log("[JS8 TX JSON]", message);

      this.socket.write(`${message}\n`);

      return true;
    }

    console.log("[JS8 TX FAIL] Socket is not connected");

    return false;
  }

  #startSimulator() {
    this.onOpen?.();

    /*
     * Simulator messages now use NDxx node identifiers rather than callsigns.
     * This reflects the shared-callsign BearWave model:
     *
     *   G7PRW = JS8Call transport callsign
     *   ND01 = BearWave node identity
     */
    const demoMessages = [
      () => this.#msg("ND01", "HB", "A1", "0", "B72,V118"),
      () => this.#msg("ND02", "HB", "A2", "0", "B81,V121,T22,H63"),
      () => this.#msg("ND03", "SR", "A3", "0", "B67,T25,H59"),
      () => this.#msg("ND01", "TA", "A4", "T1", "B68,V117"),
      () => this.#msg("ND02", "LB", "A5", "L1", "B18,V109"),
      () => this.#msg("ND03", "FT", "A6", "0", "X03,B64")
    ];

    let step = 0;

    this.simTimer = setInterval(() => {
      const fn = demoMessages[step % demoMessages.length];
      const payload = fn();

      this.onMessage?.(payload);

      step += 1;
      this.simCounter += 1;
    }, 7000);
  }

  #msg(node, type, id, flags, data) {
    const payload = `BW1|${node}|${type}|${id}${this.simCounter}|${flags}|${data}`;
    return JSON.stringify({
      type: "RX.ACTIVITY",
      value: payload,
      params: {
        DIAL: 7078000,
        FREQ: 7079500,
        OFFSET: 1500,
        SNR: -6,
        SPEED: 1,
        TDRIFT: 0,
        UTC: Date.now(),
        _ID: -1
      }
    });
  }
}
