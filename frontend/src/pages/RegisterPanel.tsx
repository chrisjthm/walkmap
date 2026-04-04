import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { getApiBase, useAuth } from "../components/auth";

type AuthSuccessPayload = {
  token: string;
  user: {
    id: string;
    email: string;
  };
};

const MIN_PASSWORD_LENGTH = 8;
const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type RegisterLocationState = {
  returnTo?: string;
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

export default function RegisterPanel() {
  const location = useLocation();
  const navigate = useNavigate();
  const { setSession } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setError("Enter your email to create an account.");
      return;
    }
    if (!EMAIL_REGEX.test(trimmedEmail)) {
      setError("Enter a valid email address.");
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError("Use at least 8 characters for your password.");
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const apiBase = getApiBase();
      const response = await fetch(apiBase ? `${apiBase}/auth/register` : "/auth/register", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email: trimmedEmail,
          password,
        }),
      });

      if (!response.ok) {
        throw new Error(await parseErrorMessage(response));
      }

      const payload = (await response.json()) as AuthSuccessPayload;
      setSession(payload.token, payload.user);
      const returnTo = (location.state as RegisterLocationState | null)?.returnTo ?? "/";
      navigate(returnTo);
    } catch (submitError) {
      setError(
        submitError instanceof Error
          ? submitError.message
          : "We couldn’t create your account right now.",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <section className="panel-section">
        <h2 className="text-xl">Create Account</h2>
        <p className="mt-2 text-sm text-moss">
          Join to save routes, verify segments, and tune the map for everyone.
        </p>
      </section>

      <section className="panel-section">
        <form className="panel-grid" noValidate onSubmit={onSubmit}>
          <div className="panel-field">
            <label className="panel-label" htmlFor="reg-email">
              Email
            </label>
            <input
              className="panel-input"
              id="reg-email"
              placeholder="you@walkmap.app"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>
          <div className="panel-field">
            <label className="panel-label" htmlFor="reg-password">
              Password
            </label>
            <input
              className="panel-input"
              id="reg-password"
              placeholder="Create a secure password"
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
            {loading ? "Creating Account..." : "Register"}
          </button>
          <p className="text-sm text-moss">
            Already have an account? <Link to="/login">Sign in</Link>.
          </p>
        </form>
      </section>
    </>
  );
}
