import { useEffect, useState } from "react";
import { KnowledgeGraph } from "../components/KnowledgeGraph";
import { loadEstate, type GraphPayload } from "../lib/estate";

/** Full-screen 3D map of the live catalog, loaded from GET /api/graph. */
export function CalaGraphPage() {
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    document.title = "Knowledge graph · AnalytIQ intelligence";
    let current = true;
    loadEstate()
      .then((data) => { if (current) setGraph(data); })
      .catch(() => { if (current) setFailed(true); });
    return () => { current = false; };
  }, []);

  return (
    <main className="kg-page">
      <h1 className="sr-only">Knowledge graph</h1>
      {graph ? (
        <KnowledgeGraph entities={graph.entities} edges={graph.edges} />
      ) : (
        <p className="kg-status" role="status">
          {failed ? "The backend is not reachable. Start it, then reload this page." : "Loading the catalog"}
        </p>
      )}
    </main>
  );
}
