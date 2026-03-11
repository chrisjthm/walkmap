export default function RegisterPanel() {
  return (
    <>
      <section className="panel-section">
        <h2 className="text-xl">Create Account</h2>
        <p className="mt-2 text-sm text-moss">
          Join to save routes, verify segments, and tune the map for everyone.
        </p>
      </section>

      <section className="panel-section">
        <div className="panel-grid">
          <div className="panel-field">
            <label className="panel-label" htmlFor="name">
              Name
            </label>
            <input
              className="panel-input"
              id="name"
              placeholder="Ava Park"
              type="text"
            />
          </div>
          <div className="panel-field">
            <label className="panel-label" htmlFor="reg-email">
              Email
            </label>
            <input
              className="panel-input"
              id="reg-email"
              placeholder="you@walkmap.app"
              type="email"
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
            />
          </div>
          <button className="cta-button" type="button">
            Register
          </button>
        </div>
      </section>
    </>
  );
}
