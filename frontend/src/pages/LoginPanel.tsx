import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getApiBase, useAuth } from "../components/auth";

type AuthSuccessPayload = {
  token: string;
  user: {
    id: string;
    email: string;
  };
};

const normalizeErrorDetail = (detail: unknown): string | null => {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const firstMessage = detail
      .map((item) => normalizeErrorDetail(item))
      .find((message): message is string => Boolean(message));
    return firstMessage ?? null;
  }
  if (detail && typeof detail === "object") {
    const record = detail as Record<string, unknown>;
    if (typeof record.msg === "string" && record.msg.trim()) {
      return record.msg;
    }
    if (typeof record.message === "string" && record.message.trim()) {
      return record.message;
    }
  }
  return null;
};

const parseErrorMessage = async (response: Response) => {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return normalizeErrorDetail(payload.detail) ?? "Something went wrong. Please try again.";
  } catch {
    return "Something went wrong. Please try again.";
  }
};

export default function LoginPanel() {
  const navigate = useNavigate();
  const { setSession } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    if (!email.trim() || !password) {
      setError("Enter both your email and password.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const apiBase = getApiBase();
      const response = await fetch(apiBase ? `${apiBase}/auth/login` : "/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email: email.trim(),
          password,
        }),
      });

      if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
      }

      const payload = (await response.json()) as AuthSuccessPayload;
      setSession(payload.token, payload.user);
      navigate("/");
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "We couldn’t sign you in right now.",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <section className="panel-section">
        <h2 className="text-xl">Welcome Back</h2>
        <p className="mt-2 text-sm text-moss">
          Sign in to rate segments and save your favorite loops.
        </p>
      </section>

      <section className="panel-section">
        <form className="panel-grid" onSubmit={onSubmit}>
          <div className="panel-field">
            <label className="panel-label" htmlFor="email">
              Email
            </label>
            <input
              className="panel-input"
              id="email"
              placeholder="you@walkmap.app"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div className="panel-field">
            <label className="panel-label" htmlFor="password">
              Password
            </label>
            <input
              className="panel-input"
              id="password"
              placeholder="••••••••"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          {error ? (
            <p className="text-sm text-red-700" role="alert">
              {error}
            </p>
          ) : null}
          <button className="cta-button" type="submit" disabled={loading}>
            {loading ? "Signing In..." : "Sign In"}
          </button>
          <p className="text-sm text-moss">
            Need an account? <Link to="/register">Create one</Link>.
          </p>
        </form>
      </section>
    </>
  );
}
