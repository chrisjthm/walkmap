import { describe, expect, it } from "vitest";
import App from "./App.jsx";

describe("App", () => {
  it("exports a component", () => {
    expect(typeof App).toBe("function");
  });
});
