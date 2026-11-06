import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { createServer } from "vite";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

// Uses the real offline backend, not hand-written approximations of SSE payloads.
const capture = spawnSync(
  process.env.WORKBENCH_PYTHON || "../backend/.venv/bin/python",
  ["tests/capture_pipeline.py"],
  { encoding: "utf8", maxBuffer: 8 * 1024 * 1024 },
);
assert.equal(capture.status, 0, capture.stderr || capture.error?.message);
const { catalog, runs } = JSON.parse(capture.stdout);
const server = await createServer({ optimizeDeps: { noDiscovery: true, include: [] },
  server: { middlewareMode: true },
  appType: "custom",
});
try {
  const { Workbench } = await server.ssrLoadModule(
    "/src/components/ask/Workbench.tsx",
  );
  const { StageDetail } = await server.ssrLoadModule(
    "/src/components/ask/StageDetail.tsx",
  );
  for (const run of runs) {
    await test(`renders real streaming payloads: ${run.preset}`, () => {
      const stages = {};
      let decision = null;
      for (const event of run.events) {
        if (event.type !== "stage") continue;
        stages[event.stage] = event;
        if (event.stage === "decision" && event.status === "done")
          decision = event.data.decision;
        const html = renderToStaticMarkup(
          createElement(Workbench, { stages, catalog, decision }),
        );
        assert.ok(!html.includes("NaN"), `${event.stage} has invalid scores`);
        assert.ok(html.includes("Evidence &amp; review"));
        if (event.data)
          assert.doesNotThrow(() =>
            renderToStaticMarkup(
              createElement(StageDetail, {
                stage: event.stage,
                data: event.data,
                catalog,
              }),
            ),
          );
        if (
          event.stage === "governance" &&
          event.status === "done" &&
          stages.discovery.data.candidates.length
        ) {
          assert.ok(
            html.includes("Compatibility view"),
            "Partial governance payload must not replace full candidate data",
          );
        }
      }
    });
  }
  await test("covers the backend decision paths", () => {
    const decisions = new Set(
      runs.flatMap((r) =>
        r.events
          .filter(
            (e) =>
              e.type === "stage" &&
              e.stage === "decision" &&
              e.status === "done",
          )
          .map((e) => e.data.decision),
      ),
    );
    for (const d of ["migrate", "new_build", "not_feasible", "repair", "reuse"])
      assert.ok(decisions.has(d), `missing decision path: ${d}`);
  });
} finally {
  await server.close();
}
