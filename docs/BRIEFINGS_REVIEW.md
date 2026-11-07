# Reviewing team briefings

Open **Briefings** in the sidebar, or go directly to `/briefings`. The review uses the Pharmaceuticals workbook’s synthetic Nubeqa observations for Germany. October 2026 is the latest available month.

## Run a review with persistent data

From a fresh checkout of this branch, use Docker Compose with a separate project name and ports. These commands start a dedicated local MongoDB database, the API and the frontend. The review configuration uses offline agents.

```sh
touch backend/.env
FRONTEND_PORT=5174 BACKEND_PORT=8014 docker compose -p bayer-briefing-review -f docker-compose.yml -f compose.review.yaml up --build
```

Open [the briefing](http://localhost:5174/briefings). The footer shows the store in use. **Shared MongoDB storage** keeps selections, actions, revisions and evidence across restarts. The standard no-database setup keeps them in memory for the lifetime of the server.

## Start with an employee decision

Open **Ask** and try one of these questions with the same local workbook.

### Build a usable dashboard from a request

1. Type **I need a dashboard**. When asked for the measures and scope, enter **Net sales and units shipped**, then **Nubeqa in France**. Set the decision to **Decide where to allocate stock** and the period to **All available workbook months**. A fully specified request goes straight to the catalogue assessment.
2. Choose **Review and build dashboard** and read the brief. Select **Build dashboard** to open the result. Switch metrics, filter the displayed periods and open **Dashboard brief and sources**. October shows €37.58m in sales and 33,941 units shipped, both from workbook row 21.
3. Copy the dashboard link or find it under **Saved dashboards** on the Ask start screen. Repeat the same brief to reopen the existing dashboard. The Docker review configuration uses MongoDB so both the result and its source values survive a restart.

If an existing report fits, open that report or its verified workbook view. A review or repair stays with the responsible owner. When a new request mixes calculable KPIs with catalogue-only measures, the builder names the omissions and asks whether the employee wants the narrower dashboard. The dashboard runs in Analytics Manager using the synthetic workbook.

### Compare the catalogue decisions

| Employee request | What to verify |
| --- | --- |
| Monthly units shipped for Nubeqa in Germany. Needed today. | If prompted for the decision, enter “Decide where to act this month”. **Reuse** opens the shipment report `BR-SHIPMENTS`. It shows ten months of figures. Commercial and Supply also use this report in their briefings. |
| Show monthly inventory coverage and OTIF for Lynkuet in Spain. | Start a new question and select this example. The chart opens inside the answer. Switch between inventory coverage and OTIF, then tap a month or use the arrow keys to inspect the source row. October inventory coverage is 8.88 weeks and OTIF is 98.5%. |
| Use the Eylea/Japan starter question. | **Human review** shows why immediate reuse would be unsafe. The report `AST-0079` lists Eylea in `Analytics_Assets` row 80. Its linked model `SM-040` lists Nubeqa in `Semantic_Models` row 41. |

From the Eylea decision, assign review work, select an owner and set a due date. Reopen the conversation through **History**, record the outcome and inspect the assignment. The action retains the request and evidence that the owner received. Publishing to a Power BI tenant requires a separate integration.

For the Xarelto Tableau migration starter, choose a segment's recommendation beneath the migration chart to see the reports in that group and why each received that recommendation.

## Try the handover

1. Switch between Commercial and Supply. Both reference the same shipment report. Use the metric buttons on the briefing chart to switch between that team's pinned trends. Commercial starts with net sales and forecast. Supply starts with on-time, in-full delivery. Open **Choose reports**, pin a view for one team and reload. Approving a table presentation removes that view from the chart choices.
2. Open **Meeting mode** for the room. On the employee screen, open **Nubeqa sales & shipments** to explore its monthly history and worksheet evidence. September and October shipments come from `Product_Market_Monthly` rows 10 and 11. The separate supply routing record is undated.
3. From that report, assign a follow-up to a named owner with a due date. Reopen it under **From our last briefing**. It retains the original filters, data, report revision and source references. Closing it records the outcome.
4. Open **BI report register**. Search for `AST-0079` to inspect its workbook owner, usage period and report/model scope conflict. Source ownership, creation date, modification date and latest active month have distinct meanings.
5. Open `BR-SHIPMENTS`, request a change, and use the assigned owner to prepare a change from chart to comparison table. Select an independent demo reviewer to approve it with a reason and supporting evidence. Return to the employee briefing and open the earlier follow-up to compare the current display with its original evidence.

The register includes 360 imported assets and three app-defined report views. Display approvals take effect inside this application. Imported records keep their original titles and can have a separate reviewed register alias. Named participant selection demonstrates review responsibilities on shared synthetic data. Corporate identity, Power BI Desktop validation and tenant publication are separate integrations.
