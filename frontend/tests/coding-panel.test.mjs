import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import React from "react";
import { act, create } from "react-test-renderer";
import { createServer } from "vite";

let server;
let CodingPanel;

before(async () => {
  server = await createServer({
    server: { middlewareMode: true, hmr: false, watch: null },
    appType: "custom",
  });
  ({ default: CodingPanel } = await server.ssrLoadModule("/src/CodingPanel.tsx"));
});

after(async () => { await server?.close(); });

// Status shape returned by the backend before runtime/model management existed.
const legacyStatus = {
  installed: true,
  authenticated: true,
  version: "codex-cli 0.100.0",
  auth_mode: "profile",
  auth_message: "Logged in",
  tmux_available: true,
  ssh_available: true,
  password_ssh_available: true,
  browser_qa_available: true,
};

async function renderStatus(t, status) {
  t.mock.method(globalThis, "fetch", async (url) => {
    const responses = {
      "/api/coding/status": status,
      "/api/coding/auth/device": { active: false, status: "idle" },
      "/api/ssh/machines": { machines: [] },
      "/api/coding/sessions": { sessions: [] },
    };
    assert.ok(Object.hasOwn(responses, url), `Unexpected request: ${url}`);
    return new Response(JSON.stringify(responses[url]));
  });
  const previousStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true, value: { getItem: () => null },
  });
  let renderer;
  t.after(() => {
    if (renderer) act(() => renderer.unmount());
    if (previousStorage) Object.defineProperty(globalThis, "localStorage", previousStorage);
    else delete globalThis.localStorage;
  });
  await act(async () => { renderer = create(React.createElement(CodingPanel)); });
  return renderer;
}

test("old backend status keeps coding sessions usable without model controls", async (t) => {
  const renderer = await renderStatus(t, legacyStatus);
  const picker = renderer.root.findByType("select");
  assert.equal(picker.props.disabled, true);
  assert.equal(picker.props.value, "");
  const newSession = renderer.root.findAllByType("button").find((button) => button.children.includes("New session"));
  assert.equal(newSession.props.disabled, false);
  assert.match(JSON.stringify(renderer.toJSON()), /Update information unavailable/);
  assert.match(JSON.stringify(renderer.toJSON()), /Model selection is unavailable/);
  act(() => newSession.props.onClick());
  assert.match(JSON.stringify(renderer.toJSON()), /New persistent session/);
});

test("current backend status enables and populates model selection", async (t) => {
  const renderer = await renderStatus(t, {
    ...legacyStatus,
    current_version: "0.100.0",
    latest_version: "0.100.0",
    update_available: false,
    selected_model: "test-model",
    model_catalog: {
      available: true, reason: "",
      models: [{ id: "test-model", display_name: "Test model", is_default: true }],
    },
  });
  const picker = renderer.root.findByType("select");
  assert.equal(picker.props.disabled, false);
  assert.equal(picker.props.value, "test-model");
  assert.equal(picker.findAllByType("option").length, 2);
  assert.match(JSON.stringify(renderer.toJSON()), /Codex is up to date/);
});

test("model discovery failure displays the backend reason", async (t) => {
  const renderer = await renderStatus(t, {
    ...legacyStatus,
    model_catalog: { available: false, reason: "Model discovery timed out", models: [] },
  });
  assert.equal(renderer.root.findByType("select").props.disabled, true);
  assert.match(JSON.stringify(renderer.toJSON()), /Model discovery timed out/);
});
