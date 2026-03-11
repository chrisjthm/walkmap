export default function ExplorePanel() {
  return (
    <>
      <section className="panel-section">
        <h2 className="text-xl">Explore Mode</h2>
        <p className="mt-2 text-sm text-moss">
          Drift toward unverified segments with high potential. We will overlay
          the explore bias once the scoring engine is wired.
        </p>
      </section>

      <section className="panel-section">
        <div className="panel-grid">
          <div className="panel-field">
            <label className="panel-label" htmlFor="radius">
              Search Radius
            </label>
            <input
              className="panel-input"
              id="radius"
              placeholder="1.5 miles"
              type="text"
            />
          </div>
          <div className="panel-field">
            <label className="panel-label" htmlFor="tempo">
              Tempo
            </label>
            <select className="panel-input" id="tempo">
              <option>Walk</option>
              <option>Run</option>
            </select>
          </div>
        </div>
        <div className="chip-row mt-4">
          <span className="chip">Unverified First</span>
          <span className="chip">Score Floor 20</span>
          <span className="chip">Adjacency Boost</span>
        </div>
      </section>

      <section className="panel-section">
        <h3 className="text-lg">Suggested Drift</h3>
        <p className="mt-2 text-sm text-moss">
          4.1 mi loop · 68 avg score · 18 new segments
        </p>
        <button className="cta-button mt-4" type="button">
          Start Exploring
        </button>
      </section>
    </>
  );
}
