/** Follow the latest content only while the reader stays near its end. */
export type ScrollPort = {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
};

export function chatScroll(
  port: ScrollPort,
  showJump: (visible: boolean) => void,
) {
  let following = true;
  let anchor: { read: () => number; position: number } | null = null;
  const end = () => Math.max(0, port.scrollHeight - port.clientHeight);
  const read = () => {
    // Clamp elastic overscroll without changing the browser's native scrolling.
    const top = Math.max(0, Math.min(port.scrollTop, end()));
    following = end() - top <= 80;
    showJump(!following);
  };
  const jump = () => {
    following = true;
    // Let the browser clamp to its exact end, including fractional CSS pixels.
    port.scrollTop = port.scrollHeight;
    read();
  };
  return {
    onScroll: read,
    preserve: (position: () => number) => {
      anchor = { read: position, position: position() };
    },
    changed: () => {
      if (anchor) {
        port.scrollTop += anchor.read() - anchor.position;
        anchor = null;
        read();
        return;
      }
      // Use the position recorded before content/viewport size changed.
      if (following) port.scrollTop = port.scrollHeight;
      read();
    },
    jump,
  };
}
