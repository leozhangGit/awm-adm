import test from "node:test";
import assert from "node:assert/strict";
import { chatScroll } from "../src/chat-scroll.ts";

function reader(height = 1200) {
  let position = 0;
  const port = {
    get scrollTop() {
      return position;
    },
    set scrollTop(value: number) {
      position = Math.max(
        0,
        Math.min(value, this.scrollHeight - this.clientHeight),
      );
    },
    scrollHeight: height,
    clientHeight: 400,
  };
  let jumpVisible = false;
  const scroll = chatScroll(port, (visible) => {
    jumpVisible = visible;
  });
  return {
    port,
    scroll,
    jumpVisible: () => jumpVisible,
    elasticScroll: (value: number) => {
      position = value;
      scroll.onScroll();
    },
  };
}

test("opening history and arriving replies follow the latest within the history only", () => {
  const { port, scroll, jumpVisible } = reader();
  scroll.changed();
  assert.equal(port.scrollTop, 800);
  assert.equal(jumpVisible(), false);
  port.scrollHeight = 1700;
  scroll.changed();
  assert.equal(port.scrollTop, 1300);
});

test("reading older messages survives unchanged refresh, appended messages and reply growth", () => {
  const { port, scroll, jumpVisible } = reader();
  scroll.changed();
  port.scrollTop = 300;
  scroll.onScroll();
  assert.equal(jumpVisible(), true);
  scroll.changed();
  assert.equal(port.scrollTop, 300);
  port.scrollHeight = 1900;
  scroll.changed();
  assert.equal(port.scrollTop, 300);
  assert.equal(jumpVisible(), true);
  scroll.jump();
  assert.equal(port.scrollTop, 1500);
  assert.equal(jumpVisible(), false);
  port.scrollHeight = 2200;
  scroll.changed();
  assert.equal(port.scrollTop, 1800);
});

test("near-bottom scrolling resumes follow without trapping native overscroll", () => {
  const { port, scroll, jumpVisible, elasticScroll } = reader();
  port.scrollTop = 719;
  scroll.onScroll();
  assert.equal(jumpVisible(), true);
  port.scrollTop = 720;
  scroll.onScroll();
  port.scrollHeight = 1500;
  scroll.changed();
  assert.equal(port.scrollTop, 1100);
  elasticScroll(1130);
  assert.equal(port.scrollTop, 1130);
  assert.equal(jumpVisible(), false);
  elasticScroll(-30);
  assert.equal(port.scrollTop, -30);
  assert.equal(jumpVisible(), true);
});

test("following and jumping reach the true browser end despite rounded geometry", () => {
  let position = 0;
  const port = {
    scrollHeight: 1000,
    clientHeight: 400,
    get scrollTop() {
      return position;
    },
    set scrollTop(value: number) {
      position = Math.min(value, 600.5);
    },
  };
  const scroll = chatScroll(port, () => {});
  scroll.changed();
  assert.equal(port.scrollTop, 600.5);
  port.scrollTop = 200;
  scroll.onScroll();
  scroll.jump();
  assert.equal(port.scrollTop, 600.5);
});

test("viewport resizing preserves a reader but keeps a following reader at the end", () => {
  const { port, scroll } = reader();
  scroll.changed();
  port.clientHeight = 250;
  scroll.changed();
  assert.equal(port.scrollTop, 950);
  port.scrollTop = 100;
  scroll.onScroll();
  port.clientHeight = 450;
  scroll.changed();
  assert.equal(port.scrollTop, 100);
});

test("empty or short history needs no jump control and follows the first loaded history", () => {
  const { port, scroll, jumpVisible } = reader(100);
  scroll.changed();
  assert.equal(port.scrollTop, 0);
  assert.equal(jumpVisible(), false);
  port.scrollHeight = 2000;
  scroll.changed();
  assert.equal(port.scrollTop, 1600);
  const otherChannel = reader(1800);
  otherChannel.scroll.changed();
  assert.equal(otherChannel.port.scrollTop, 1400);
});
test("prepending history preserves the visible exchange even when a new reply also grows", () => {
  const { port, scroll, jumpVisible } = reader();
  scroll.changed();
  port.scrollTop = 120;
  scroll.onScroll();
  let messageTop = 240;
  scroll.preserve(() => messageTop - port.scrollTop);
  messageTop += 1500;
  port.scrollHeight += 1800; // 1500 above the anchor, 300 appended below it.
  scroll.changed();
  assert.equal(port.scrollTop, 1620);
  assert.equal(messageTop - port.scrollTop, 120);
  assert.equal(jumpVisible(), true);
  scroll.changed();
  assert.equal(port.scrollTop, 1620); // ResizeObserver must not apply the shift twice.
});
