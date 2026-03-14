import { vi } from "vitest";

if (!globalThis.URL) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).URL = {};
}

if (!("createObjectURL" in globalThis.URL)) {
  Object.defineProperty(globalThis.URL, "createObjectURL", {
    value: vi.fn(() => "blob:mock"),
    configurable: true,
  });
}
