export default function PlanPanel() {
  return (
    <>
      <section className="panel-section">
        <h2 className="text-xl">Plan a Route</h2>
        <p className="mt-2 text-sm text-moss">
          Configure a route and let the planner tune for score, scenery, and
          flow. This panel will connect to POST /routes/suggest.
        </p>
      </section>

      <section className="panel-section">
        <div className="panel-grid">
          <div className="panel-field">
            <label className="panel-label" htmlFor="start">
              Start Location
            </label>
            <input
              className="panel-input"
              id="start"
              placeholder="Journal Square"
              type="text"
            />
          </div>
          <div className="panel-field">
            <label className="panel-label" htmlFor="mode">
              Route Mode
            </label>
            <select className="panel-input" id="mode">
              <option>Loop</option>
              <option>Point-to-Point</option>
              <option>Point-to-Destination</option>
            </select>
          </div>
          <div className="panel-field">
            <label className="panel-label" htmlFor="distance">
              Distance
            </label>
            <input
              className="panel-input"
              id="distance"
              placeholder="3.0 miles"
              type="text"
            />
          </div>
        </div>
      </section>

      <section className="panel-section">
        <h3 className="text-lg">Priorities</h3>
        <div className="chip-row mt-3">
          <span className="chip">Highest Rated</span>
          <span className="chip">Dining</span>
          <span className="chip">Residential</span>
          <span className="chip">Explore</span>
        </div>
        <button className="cta-button mt-4" type="button">
          Find Routes
        </button>
      </section>
    </>
  );
}
