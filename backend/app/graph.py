"""Molecular view: directed source lineage, ID joins and unapproved candidates.

Uses the same workbook and live catalogue as the investigation pipeline.
Imported facts, runtime changes and application scores stay distinguishable.
"""
from collections import defaultdict
from . import catalog as cat
from .decision import governance
from .workbook_source import records, indexed, metadata, source


def build_graph(actions=None, requests=None):
    C=cat.CATALOG
    meta=metadata()
    nodes, links={}, {}
    def node(id, kind, name, status="active", summary="", props=None, refs=None, flags=None, runtime=False):
        nodes[id]={"id":id,"uid":id,"type":kind,"name":name,"status":status,"trust":None,
            "updated":"Runtime record" if runtime else "Workbook snapshot v"+str(meta["version"]),
            "summary":summary,"props":{"Record ID":id,**(props or {}),"Evidence scope":"Application record" if runtime else "Bayer challenge · synthetic snapshot"},
            "sources":refs or [],"flags":flags or []}
    def edge(s,rel,t,basis,ref=None,label=None):
        if s not in nodes or t not in nodes: return
        key=(s,rel,t,basis)
        if key not in links: links[key]={"s":s,"rel":rel,"t":t,"basis":basis,"label":label or rel.replace("_"," "),"sources":[]}
        if ref and ref not in links[key]["sources"]: links[key]["sources"].append(ref)
    def props(r):
        return {k.replace("_"," ").capitalize():str(v) for k,v in r.items() if not k.startswith("_") and k not in ("email","synthetic_record") and v is not None}
    node("BAYER","domain","Bayer Pharmaceuticals",summary="Find existing analytics and inspect their dependencies, ownership and source evidence.",props={"Sheets":str(meta["sheet_count"]),"Snapshot":meta["sha256"]})
    for sheet,info in meta["sheets"].items():
        node("sheet:"+sheet,"source",sheet,summary=f"{info['records']} source rows. The Workbook page contains every row.",props={"Rows":str(info["records"])},refs=[source(sheet,1)])
        edge("sheet:"+sheet,"belongs_to","BAYER","join",source(sheet,1),"worksheet in workbook")
    for r in records("Owners"):
        oid=r["owner_id"]; o=C["owners"].get(oid,r)
        node(oid,"person",o["owner_name"],"active" if o["status"]=="active" else "inactive",o["role"]+" · "+o["scope"],props(r),[r["_source"]])
        nodes[oid]["initials"]="".join(p[0] for p in o["owner_name"].split()[:2])
    for r in records("Workspaces"):
        node(r["workspace_id"],"workspace",r["workspace_name"],summary=r["platform"]+" · "+r["governance_mode"],props=props(r),refs=[r["_source"]])
    for r in records("Semantic_Models"):
        current=C["models"].get(r["model_id"],r)
        flags=[]
        if current["refresh_status"]!="healthy": flags.append({"sev":"warn","title":"Refresh "+current["refresh_status"],"text":"Imported status; exact refresh timestamp is not supplied."})
        node(r["model_id"],"model",current.get("name",r["model_name"]),"stale" if current["refresh_status"]=="failed" else "certified" if current["endorsement"]=="certified" else "uncertified",r["model_type"]+" · "+r["product_scope"]+" · "+r["region_scope"],props(r),[r["_source"]],flags)
    for r in records("KPI_Catalog"):
        family="family:"+r["canonical_metric"]; domain="domain:"+r["domain"]
        if family not in nodes: node(family,"glossary",r["canonical_metric"],summary="Metric family. Shared family membership does not establish equivalent definitions.")
        if domain not in nodes: node(domain,"domain",r["domain"],summary="Domain supplied in the KPI catalogue.")
        status="conflict" if r["definition_status"]=="definition_conflict" else "certified" if r["approval_status"]=="approved" else "draft"
        node(r["kpi_id"],"metric",r["kpi_name"],status,r["description"],props(r),[r["_source"]])
        edge(r["kpi_id"],"variant_of",family,"join",r["_source"],"same canonical metric family; not an equivalence claim")
        edge(r["kpi_id"],"belongs_to",domain,"join",r["_source"],"KPI domain")
        edge(r["owner_id"],"owns",r["kpi_id"],"join",r["_source"],"KPI owner_id")
    for r in records("Products"):
        node(r["product_id"],"product",r["product_name"],summary=r["therapeutic_area"],props=props(r),refs=[r["_source"]])
    for r in records("Markets"):
        node("market:"+r["market_id"],"market",r["market_name"],summary=r["region"],props=props(r),refs=[r["_source"]])
    raw_assets=indexed("Analytics_Assets","asset_id")
    usage,signals=defaultdict(list),defaultdict(list)
    for r in records("Asset_Usage"): usage[r["asset_id"]].append(r)
    for r in records("Governance_Signals"): signals[r["asset_id"]].append(r)
    for a in C["assets"]:
        r=raw_assets.get(a["id"])
        flags=[{"sev":"bad","title":"Conflicting KPI definition","text":why} for why in a.get("conflicts",{}).values()]
        flags += [{"sev":"warn","title":"Unapproved KPI variant","text":why} for why in a.get("variants",{}).values()]
        flags += [{"sev":"bad" if x["severity"]=="high" else "warn","title":x["code"].replace("_"," "),"text":x["status"]} for x in a.get("signals",[]) if x["status"]!="resolved"]
        if a.get("owner_status")!="active": flags.append({"sev":"warn","title":"Owner needs review","text":"No active owner is established for this asset."})
        status="draft" if a.get("artifact_state") == "validation_pending" else "conflict" if a.get("conflicts") else "orphaned" if a.get("owner_status")!="active" else "stale" if a.get("lifecycle") in ("candidate_retire","legacy") else "certified" if a.get("endorsement")=="certified" else "uncertified"
        monthly=sorted(usage[a["id"]],key=lambda x:x["month"])
        p={**(props(r) if r else {}),"Current owner ID":a.get("owner_id") or "Not established","Current model ID":a.get("model_id") or "Not supplied","Current lifecycle":a.get("lifecycle","unknown"),"Access":"Not established by workbook","Freshness":"Exact data age not supplied"}
        if monthly: p.update({"Views (Jan–Oct 2026)":str(sum(x["views"] or 0 for x in monthly)),"Latest monthly unique users":str(monthly[-1]["unique_users"])})
        if a.get("created_from_spec"):
            p.update({"Artifact state": a.get("artifact_state"), "Specification ID": a.get("spec_id"), "Endorsement": a.get("endorsement"), "Execution model": a.get("execution_model"), "Runtime acceptance": "Not run"})
        node(a["id"],"dashboard",a["name"],status,f"{a.get('platform','')} {a.get('asset_type','analytics')} · {a.get('workspace') or 'workspace not supplied'}",p,[r["_source"]] if r else [],flags,runtime=not r)
        if r:
            # Same application score as the decision engine, explicitly labelled as computed.
            score,_=governance(a); nodes[a["id"]]["trust"]=score
            nodes[a["id"]]["props"]["Governance score basis"]="Computed by the existing decision engine; not a workbook field or execution check"
            nodes[a["id"]]["views"]=sum(x["views"] or 0 for x in monthly)
            nodes[a["id"]]["usage_period"]=meta["usage_period"]
            nodes[a["id"]]["evidence_sources"]=[x["_source"] for x in monthly+signals[a["id"]]]
        if a.get("lifecycle")=="candidate_retire": nodes[a["id"]]["action"]="Review retirement candidate: "+a["name"]
    products={r["product_name"]:r["product_id"] for r in records("Products")}
    for r in records("Business_Requests"):
        node(r["request_id"],"request",r["request_id"]+" · "+r["product_context"],summary=r["request_text"],props=props(r),refs=[r["_source"]])
        edge(r["request_id"],"context",products.get(r["product_context"]),"join",r["_source"],"structured product context; confirm against request text")
        edge(r["request_id"],"context","market:"+r["market_context"],"join",r["_source"],"structured market context")
    for r in records("Lineage_Edges"):
        edge(r["source_id"],"feeds",r["target_id"],"lineage",r["_source"],r["relationship"])
    for r in records("Asset_KPI_Map"):
        edge(r["asset_id"],"uses",r["kpi_id"],"join",r["_source"],r["usage_role"]+" KPI mapping")
    for sheet,idkey in [("Analytics_Assets","asset_id"),("Semantic_Models","model_id")]:
        for r in records(sheet):
            id=r[idkey]
            live=cat.asset_by_id(id) if sheet=="Analytics_Assets" else C["models"].get(id)
            oid=(live or {}).get("owner_id",r["owner_id"])
            edge(oid,"owns",id,"join" if oid==r["owner_id"] else "runtime",r["_source"] if oid==r["owner_id"] else None,"current owner_id")
            edge(id,"belongs_to",r["workspace_id"],"join",r["_source"],"workspace_id match")
            edge(id,"context",products.get(r["product_scope"]),"join",r["_source"],"declared product scope")
            if "market_scope" in r: edge(id,"context","market:"+r["market_scope"],"join",r["_source"],"declared market scope")
    for a in C["assets"]:
        if a["id"] not in raw_assets:
            edge(a.get("model_id"),"feeds",a["id"],"runtime",label="model assigned by application")
            edge(a.get("owner_id"),"owns",a["id"],"runtime")
            for k in a.get("kpis",[]): edge(a["id"],"uses",k,"runtime")
    for r in records("Migration_Backlog"):
        edge(r["source_asset_id"],"candidate_target",r["candidate_target_model_id"],"candidate",r["_source"],r["recommended_path_candidate"]+" · unapproved migration candidate")
    for r in records("Data_Quality"):
        if r["record_id"] in nodes:
            n=nodes[r["record_id"]]
            n["flags"].append({"sev":"bad" if r["severity"]=="high" else "warn","title":r["field"]+": "+r["issue_value"],"text":r["impact"],"source":r["_source"]})
            n.setdefault("evidence_sources",[]).append(r["_source"])
    for a in actions or []:
        aid=a.get("_id") or a.get("id")
        node(aid,"action",a["title"],"certified" if a["status"]=="verified" else "draft",a.get("reason",""),{"Status":a["status"],"Owner":a["owner"],"Sample":str(a.get("sample",False))},runtime=True)
        edge(aid,"tracks",a.get("asset_id"),"runtime")
        # Actions store a display name: never collapse duplicate-name owner IDs.
        edge(a.get("owner_id"),"owns",aid,"runtime")
    for req in requests or []:
        rid = "RUN-" + req["_id"]
        plan = req.get("plan") or {}
        node(rid, "request", req.get("title") or "Dashboard request", "draft", req.get("request_state", req["state"]),
             {"Request ID": req["_id"], "Version": str(req.get("revision", 1)), "Specification ID": plan.get("spec_id", "Not prepared"),
              "Review": str((plan.get("approval") or {}).get("approved", "Pending")), "Requester ID": req.get("requester_id", "Unknown")}, runtime=True)
        edge(req.get("requester_id"), "owns", rid, "runtime", label="requester; not report ownership")
        edge(rid, "supports", ((plan.get("decision") or {}).get("candidate") or {}).get("asset_id"), "runtime", label="assessed candidate")
        edge(rid, "tracks", plan.get("output_asset_id") or "GEN-" + plan.get("spec_id", ""), "runtime", label="generated draft")
        for action in actions or []:
            if action.get("conversation_id") == req["_id"]:
                edge(rid, "tracks", action["_id"], "runtime", label="accepted work")
    return {"entities":list(nodes.values()),"edges":list(links.values()),"focus":"KPI-001","source":meta,
        "counts":{"reports":len(C["assets"]),"models":len(C["models"]),"measures":len(C["measures"]),"datasets":meta["sheet_count"],"entities":len(nodes),"relationships":len(links)}}
