import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "../components/auth";
import LoginPanel from "./LoginPanel";
import RegisterPanel from "./RegisterPanel";

function AuthSummary() {
  const { user } = useAuth();
  return <div>{user ? `Signed in as ${user.email}` : "Map Home"}</div>;
}

const renderAuthRoute = (initialPath: "/login" | "/register") =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <MemoryRouter initialEntries={[initialPath]}>
          <Routes>
            <Route path="/login" element={<LoginPanel />} />
            <Route path="/register" element={<RegisterPanel />} />
            <Route path="/" element={<AuthSummary />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );

const renderLoginWithReturnTo = () =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider>
        <MemoryRouter initialEntries={[{ pathname: "/login", state: { returnTo: "/plan" } }]}>
          <Routes>
            <Route path="/login" element={<LoginPanel />} />
            <Route path="/plan" element={<div>Plan Page</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );

describe("auth panels", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("submits register and navigates home on success", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          token: "token-123",
          user: { id: "user-1", email: "user@example.com" },
        }),
        {
          status: 201,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderAuthRoute("/register");

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "password123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /register/i }));

    await waitFor(() => {
      expect(String(vi.mocked(fetch).mock.calls[0]?.[0])).toContain("/auth/register");
    });
    expect(vi.mocked(fetch).mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
    });
    expect(await screen.findByText(/signed in as user@example.com/i)).toBeTruthy();
  });

  it("shows register validation error before submitting", async () => {
    renderAuthRoute("/register");

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "user@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: /register/i }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/at least 8 characters/i);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows email validation before register submit", async () => {
    renderAuthRoute("/register");

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "not-an-email" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "password123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /register/i }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/valid email/i);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("submits login and navigates home on success", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          token: "token-123",
          user: { id: "user-1", email: "user@example.com" },
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderAuthRoute("/login");

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "password123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(String(vi.mocked(fetch).mock.calls[0]?.[0])).toContain("/auth/login");
    });
    expect(vi.mocked(fetch).mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
    });
    expect(await screen.findByText(/signed in as user@example.com/i)).toBeTruthy();
  });

  it("returns to the protected route after successful login", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          token: "token-123",
          user: { id: "user-1", email: "user@example.com" },
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderLoginWithReturnTo();

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "password123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByText("Plan Page")).toBeTruthy();
  });

  it("shows backend login errors", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: "Invalid email or password" }),
        {
          status: 401,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderAuthRoute("/login");

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "wrongpass123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/invalid email or password/i);
  });

  it("renders structured backend login errors as readable text", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: { message: "Invalid email or password" } }),
        {
          status: 401,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderAuthRoute("/login");

    fireEvent.change(screen.getByLabelText(/email/i), {
      target: { value: "user@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/password/i), {
      target: { value: "wrongpass123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/invalid email or password/i);
  });
});
