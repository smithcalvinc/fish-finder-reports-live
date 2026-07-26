#!/usr/bin/env python3
"""Build the Fish Finder Outdoors admin feed from every installed state database."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

def clean(value: Any) -> str:
    return " ".join(str(value or "").split())

def map_freshness(value: str) -> str:
    value=clean(value).lower()
    if value in {"very_current","current"}: return "current"
    if value=="recent": return "aging"
    return "stale"

def report_for_admin(report, generated_at, unmatched_ids, state):
    water=clean(report.get("water_name")); title=clean(report.get("title")) or "Fishing update"
    species=clean(report.get("species")); rating=clean(report.get("rating")); techniques=clean(report.get("techniques")); access=clean(report.get("access_notes")); url=clean(report.get("source_url")); rid=clean(report.get("report_id"))
    catches=[]
    if species: catches.append({"species":species,"metric":rating or "Reported","detail":techniques})
    return {"report_kind":clean(report.get("source_type")) or "official","report_id":rid,"state":state,"counties":report.get("counties") or [],"names":[water] if water else [f"Statewide {state}"],"water_name":water,"agency":clean(report.get("source_name")) or f"{state} fishing source","report_type":clean(report.get("source_type")).replace("_"," ").title() or "Fishing report","published_date":clean(report.get("report_date")),"report_period":clean(report.get("observed_period")),"headline":title,"summary":clean(report.get("summary")),"catches":catches,"conditions":[v for v in (access,techniques) if v],"rating":rating,"species":species,"techniques":techniques,"source_url":url,"specificity":f"Matched {state} public water" if water else f"Statewide or multi-water {state} report","freshness_status":map_freshness(clean(report.get("freshness"))),"freshness_days":report.get("age_days"),"last_checked_at":generated_at,"source_status":"available" if url else "source-not-linked","source_error":"","review_required":rid in unmatched_ids}

def write_js(path, comment, variable, value):
    path.write_text(f"/* {comment} */\nwindow.{variable} = "+json.dumps(value,indent=2,ensure_ascii=False)+";\n",encoding="utf-8")

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--database",action="append",default=[]); parser.add_argument("--output-dir",default="."); args=parser.parse_args()
    discovered=sorted(Path("data").glob("*_fishing_report_database.json"))
    paths=[]
    for item in [Path(p) for p in args.database]+discovered:
        if item.exists() and item not in paths: paths.append(item)
    if not paths: raise FileNotFoundError("No state fishing report databases were found.")
    reports=[]; state_rows=[]; last_runs=[]; unmatched_total=0
    for path in paths:
        db=json.loads(path.read_text(encoding="utf-8")); meta=db.get("metadata") or {}; state=clean(meta.get("state")) or clean(meta.get("title")).split(" ")[0] or path.name.split("_")[0].title(); generated=clean(meta.get("generated_at")); last_runs.append(generated)
        unmatched=db.get("unmatched_reports") or []; unmatched_ids={clean(r.get("report_id")) for r in unmatched if isinstance(r,dict)}; unmatched_total+=len(unmatched)
        reports.extend(report_for_admin(r,generated,unmatched_ids,state) for r in (db.get("flat_reports") or []) if isinstance(r,dict))
        state_rows.append({"state":state,"report_count":db.get("report_count",0),"public_water_count":db.get("public_water_count",0),"county_count":db.get("county_count",0),"generated_at":generated})
    unique={}
    for row in reports: unique[(row.get("state"),row.get("report_id"))]=row
    reports=list(unique.values()); reports.sort(key=lambda r:(clean(r.get("published_date")),clean(r.get("headline"))),reverse=True)
    current=sum(r["freshness_status"]=="current" for r in reports); aging=sum(r["freshness_status"]=="aging" for r in reports); stale=sum(r["freshness_status"]=="stale" for r in reports); review=sum(bool(r["review_required"]) for r in reports)
    source_keys={clean(r.get("source_url")) or clean(r.get("agency")) for r in reports if clean(r.get("source_url")) or clean(r.get("agency"))}; updated=max((x for x in last_runs if x),default="")
    recent={"version":f"{updated or 'current'}-multi-state","updated_at":updated,"coverage_note":"Automatically generated from every installed state county-by-county fishing database.","states":state_rows,"reports":reports}
    status={"last_run":updated,"mode":"multi-state-database","state_count":len(state_rows),"states":state_rows,"reports_total":len(reports),"public_water_count":sum(int(s["public_water_count"] or 0) for s in state_rows),"county_count":sum(int(s["county_count"] or 0) for s in state_rows),"unique_sources":len(source_keys),"freshness":{"current":current,"aging":aging,"stale":stale,"unknown":0},"changed_reports":len(reports),"review_required":review,"unreachable_sources":0,"unmatched_report_count":unmatched_total,"sources":[]}
    out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True); write_js(out/"recent_fishing_reports.js","Automatically generated multi-state fishing report feed. Do not hand-edit.","FFO_RECENT_REPORTS",recent); write_js(out/"update_status.js","Automatically generated multi-state admin status. Do not hand-edit.","FFO_UPDATE_STATUS",status)
    print(json.dumps({"states":state_rows,"reports_written":len(reports),"public_waters":status["public_water_count"],"counties":status["county_count"]},indent=2)); return 0

if __name__=="__main__": raise SystemExit(main())
