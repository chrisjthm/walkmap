export default function LoginPanel() {
  return (
    <>
      <section className="panel-section">
        <h2 className="text-xl">Welcome Back</h2>
        <p className="mt-2 text-sm text-moss">
          Sign in to rate segments and save your favorite loops.
        </p>
      </section>

      <section className="panel-section">
        <div className="panel-grid">
          <div className="panel-field">
            <label className="panel-label" htmlFor="email">
              Email
            </label>
            <input
              className="panel-input"
              id="email"
              placeholder="you@walkmap.app"
              type="email"
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
            />
          </div>
          <button className="cta-button" type="button">
            Sign In
          </button>
        </div>
      </section>
    </>
  );
}
