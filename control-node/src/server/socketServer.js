import { Server } from "socket.io";
import http from "http";

/*
 * Socket.IO carries live node updates to the kiosk dashboard so the Pi display
 * changes immediately when JS8Call receives an alarm, heartbeat, ACK event, or
 * decoded SSTV image.
 */
export function createSocketServer(app) {
  const server = http.createServer(app);
  const io = new Server(server);

  return { server, io };
}
