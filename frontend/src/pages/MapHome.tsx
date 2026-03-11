export default function MapHome() {
  return (
    <>
      <section className="panel-section">
        <h2 className="text-xl">Map Overview</h2>
        <p className="mt-2 text-sm text-moss">
          The map will surface segment scores, verified highlights, and curated
          trails. For now, choose a mode to open the planning console.
        </p>
        <div className="chip-row mt-4">
          <span className="chip">High-Score Corridors</span>
          <span className="chip">Waterfront</span>
          <span className="chip">Tree Canopy</span>
        </div>
      </section>

      <section className="panel-section">
        <h3 className="text-lg">Quick Start</h3>
        <div className="panel-grid mt-3">
          <button className="cta-button" type="button">
            Plan a Loop
          </button>
          <button className="cta-button" type="button">
            Explore Nearby
          </button>
        </div>
      </section>
    </>
  );
}
