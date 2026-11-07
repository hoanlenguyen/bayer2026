# Reviewing team briefings

Open **Briefings** in the sidebar, or go directly to `/briefings`. The review uses the Pharmaceuticals workbook’s synthetic Nubeqa observations for Germany. October 2026 is the latest available month.

## Run a review with persistent data

From a fresh checkout of this branch, use Docker Compose with a separate project name and ports. These commands start a dedicated local MongoDB database, the API and the frontend. The review configuration uses offline agents.

```sh
touch backend/.env
FRONTEND_PORT=5174 BACKEND_PORT=8014 docker compose -p bayer-briefing-review -f docker-compose.yml -f compose.review.yaml up --build
```

Open [the briefing](http://localhost:5174/briefings). The footer shows the store in use. **Shared MongoDB storage** keeps selections, actions, revisions and evidence across restarts. The standard no-database setup keeps them in memory for the lifetime of the server.

## Try the handover

1. Switch between Commercial and Supply. Both reference the same shipment report. Commercial pairs it with sales and forecast. Supply pairs it with on-time, in-full delivery. Open **Choose reports**, pin a view for one team and reload.
2. Open **Meeting mode** for the room. On the employee screen, open **Nubeqa sales & shipments** to explore its monthly history and worksheet evidence. September and October shipments come from `Product_Market_Monthly` rows 10 and 11. The separate supply routing record is undated.
3. From that report, assign a follow-up to a named owner with a due date. Reopen it under **From our last briefing**. It retains the original filters, data, report revision and source references. Closing it records the outcome.
4. Open **BI report register**. Search for `AST-0079` to inspect its workbook owner, usage period and report/model scope conflict. Source ownership, creation date, modification date and latest active month have distinct meanings.
5. Open `BR-SHIPMENTS`, request a change, and use the assigned owner to prepare a change from chart to comparison table. Select an independent demo reviewer to approve it with a reason and supporting evidence. Return to the employee briefing and open the earlier follow-up to compare the current display with its original evidence.

The register includes 360 imported assets and three app-defined report views. Display approvals take effect inside this application. Imported records keep their original titles and can have a separate reviewed register alias. Named participant selection demonstrates review responsibilities on shared synthetic data. Corporate identity, Power BI Desktop validation and tenant publication are separate integrations.
