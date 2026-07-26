export function buildAck(node, id) {
  return `ACK|${node}|${id}|OK`;
}