"""Reproducible v1 schemas and synthetic-only evidence, never desktop capture."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = {"type": "string", "maxLength": 4000}
ID = {"type": "string", "pattern": "^[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}$"}
STRINGS = {"type": "array", "items": S, "maxItems": 256}
IDS = {"type": "array", "items": ID, "maxItems": 256, "uniqueItems": True}
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}

def enum(*values): return {"enum": list(values)}
def arr(items, limit=256): return {"type": "array", "items": items, "maxItems": limit}
def obj(properties, required=None):
    return {"type": "object", "properties": properties, "required": list(properties) if required is None else required, "additionalProperties": False}
def nullable(value): return {"anyOf": [value, {"type": "null"}]}
def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2)+"\n", encoding="utf-8")
def schema(name, body):
    body = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"https://plva.local/contracts/v1/{name}.schema.json", **body}
    for directory in [ROOT/"contracts/v1", ROOT/"src/plva_skill_learning/contracts"]:
        save(directory/f"{name}.schema.json", body)

manifest = obj({
 "schema_version": enum("1.0"), "recording_id": ID, "task": S,
 "capture_mode": enum("screenshots_only", "enriched"),
 "provenance": obj({"producer": ID, "data_class": enum("synthetic", "sanitized"), "privacy_policy_version": ID}),
 "environment": obj({"kind": S, "apps": STRINGS}), "events_file": S,
 "frames": arr(obj({"frame_id": ID,"path": S,"sha256": SHA}),1000),
 "outcome": obj({"status": enum("unknown","passed","failed","cancelled"),"check_ids": IDS})})
schema("manifest", manifest)
base = {"event_id": ID,"sequence":{"type":"integer","minimum":0},"time_ms":{"type":"integer","minimum":0},"type":S}
observation = obj({**base,"type":enum("observation"),"frame_id":ID,"app":S,"text":S,
 "tokens":arr(obj({"token":{"type":"string","pattern":"^[A-Z][A-Z0-9]*_[0-9]+_[a-f0-9]{4,32}$"},"class":ID,"role_hint":nullable(ID)},["token","class"])),
 "public_values":arr(obj({"value":S,"role_hint":ID}))},list(base)+["frame_id"])
operation=obj({"kind":enum("click","type","select","navigate","wait","inspect"),"target_hint":S,"text":S,"coordinates":arr({"type":"number"},2)},["kind","target_hint"])
action=obj({**base,"type":enum("action"),"action_id":ID,"status":enum("proposed","executed","failed","blocked"),"operation":operation,"before_event_id":ID,"after_event_id":ID},list(base)+["action_id","status","operation"])
correction=obj({**base,"type":enum("correction"),"source":enum("user","observed_recovery"),"text":S,"evidence_ids":IDS},list(base)+["source","text","evidence_ids"])
check=obj({**base,"type":enum("check"),"check_id":ID,"result":enum("passed","failed","unknown"),"source":enum("core_verifier","user_confirmation","model_interpretation"),"criterion":S,"evidence_ids":IDS})
schema("event", {"oneOf":[observation,action,correction,check]})
basis=enum("observed","inferred","user_confirmed")
parameter=obj({"name":{"type":"string","pattern":"^[a-z][a-z0-9_]{0,63}$"},"type":enum("string","private_token"),"visibility":enum("public","private"),"required":{"type":"boolean"},"binding_role":nullable(ID),"token_class":nullable(ID),"source_token_hashes":arr(SHA)})
recovery=obj({"instruction":S,"basis":basis,"evidence_ids":IDS})
step=obj({"step_id":ID,"goal":S,"preconditions":STRINGS,"instruction":S,"target_hints":STRINGS,"postcondition":S,"check_ids":IDS,"recovery":arr(recovery),"evidence_ids":IDS,"basis":basis,"open_questions":STRINGS})
wcheck=obj({"check_id":ID,"criterion":S,"source":enum("core_verifier","user_confirmation","model_interpretation"),"result":enum("passed","failed","unknown"),"evidence_ids":IDS,"basis":basis})
workflow=obj({"schema_version":enum("1.0"),"skill_id":{"type":"string","pattern":"^[a-z0-9]+(?:-[a-z0-9]+)*$","maxLength":63},"revision":{"type":"integer","minimum":1},"title":S,"objective":S,"parameters":arr(parameter),"preconditions":STRINGS,"required_capabilities":IDS,"steps":arr(step),"checks":arr(wcheck),"unresolved_questions":STRINGS,"source_recording_ids":IDS,"generation":obj({"mode":enum("mock","astra"),"model":nullable(S),"bundle_digest":SHA,"window_count":{"type":"integer","minimum":1},"warnings":STRINGS}),"review":obj({"status":enum("candidate","reviewed"),"accepted_revision":nullable({"type":"integer","minimum":1})}),"validation_status":enum("candidate","reviewed","validated_on_fixture")})
schema("workflow",workflow)
mapping=obj({"target_id":ID,"event_ids":IDS,"frame_ids":IDS,"basis":basis})
evidence=obj({"schema_version":enum("1.0"),"recording_id":ID,"data_class":enum("synthetic","sanitized"),"bundle_digest":SHA,"event_ids":IDS,"frame_ids":IDS,"links":arr(mapping,1000),"outcome":manifest["properties"]["outcome"],"local_recording_available":{"type":"boolean"}})
# Whole recordings may contain more IDs than a single step.
evidence["properties"]["event_ids"]={**IDS,"maxItems":10000}
evidence["properties"]["frame_ids"]={**IDS,"maxItems":1000}
schema("evidence-map",evidence)
validation=obj({"schema_version":enum("1.0"),"status":enum("candidate","reviewed","validated_on_fixture","invalid"),"structure":obj({"passed":{"type":"boolean"},"errors":STRINGS}),"privacy":obj({"passed":{"type":"boolean"},"errors":STRINGS,"image_redaction_verified":{"const":False}}),"outcome":obj({"status":enum("unknown","passed","failed","cancelled"),"supporting_check_ids":IDS,"source":enum("synthetic_fixture","trusted_recording","none")}),"review":workflow["properties"]["review"],"reruns":arr(obj({"kind":enum("mock_hook","live_runner"),"status":enum("passed","failed","pending","invalidated"),"revision":{"type":"integer","minimum":1},"details":S})),"warnings":STRINGS})
schema("validation",validation)
prepared=obj({"schema_version":enum("1.0"),"status":enum("ready","needs_input","unsupported","invalid"),"skill_id":S,"revision":{"type":"integer","minimum":0},"missing_bindings":STRINGS,"missing_capabilities":STRINGS,"issues":STRINGS,"context":nullable(obj({"objective":S,"parameters":{"type":"object","additionalProperties":S},"steps":arr(step),"checks":arr(wcheck),"preconditions":STRINGS,"policy":S}))})
schema("prepared-context",prepared)

fixture=ROOT/"fixtures/shipment-demo"
frames=[]
screens=[("Support / ticket", "Order DEMO-104 | Replacement requested", "Customer shipping address: ADDRESS_1_a3f9"),
 ("Shipping / replacement", "Order field empty", "Destination field empty"),
 ("Shipping / replacement", "Order DEMO-104", "Destination field empty"),
 ("Shipping / replacement", "Validation: select an item before continuing", "Order DEMO-104"),
 ("Shipping / replacement", "Order DEMO-104 | Item: Replacement item", "Destination field empty"),
 ("Shipping / replacement", "Order DEMO-104 | Item: Replacement item", "Destination: ADDRESS_1_a3f9"),
 ("Shipping / replacement", "Draft ready for review", "Order DEMO-104 | Destination: ADDRESS_1_a3f9")]
for n,lines in enumerate(screens,1):
    path=fixture/f"frames/frame-{n:04d}.png"
    path.parent.mkdir(parents=True,exist_ok=True)
    im=Image.new("RGB",(800,480),"#eef2f6"); d=ImageDraw.Draw(im)
    d.rectangle((0,0,800,76),fill="#163a52"); d.text((24,24),"SYNTHETIC FIXTURE - no live application",fill="white")
    for k,line in enumerate(lines): d.text((36,115+k*65),line,fill="#17384f")
    d.rectangle((500,380,744,434),fill="#007f7a"); d.text((520,399),"Prepare draft",fill="white")
    im.save(path)
    frames.append({"frame_id":f"frame-{n:04d}","path":f"frames/frame-{n:04d}.png","sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
events=[]
def emit(type, **props):
    n=len(events)+1; events.append({"event_id":f"e{n}","sequence":n,"time_ms":(n-1)*500,"type":type,**props}); return f"e{n}"
emit("observation",frame_id="frame-0001",app="support",text="Replacement requested for order DEMO-104. Customer shipping address is protected.",tokens=[{"token":"ADDRESS_1_a3f9","class":"ADDRESS","role_hint":"customer_shipping_address"}],public_values=[{"value":"DEMO-104","role_hint":"order_id"}])
emit("action",action_id="a1",status="proposed",operation={"kind":"navigate","target_hint":"Replacement shipment form"},before_event_id="e1")
emit("action",action_id="a1",status="executed",operation={"kind":"navigate","target_hint":"Replacement shipment form"},before_event_id="e1",after_event_id="e4")
emit("observation",frame_id="frame-0002",app="shipping",text="Replacement shipment form is open.")
emit("action",action_id="a2",status="executed",operation={"kind":"type","target_hint":"Order reference","text":"DEMO-104"},before_event_id="e4",after_event_id="e6")
emit("observation",frame_id="frame-0003",app="shipping",text="Order reference DEMO-104 is present.")
emit("action",action_id="a3",status="failed",operation={"kind":"click","target_hint":"Prepare draft"},before_event_id="e6",after_event_id="e8")
emit("observation",frame_id="frame-0004",app="shipping",text="Validation message: select the replacement item.")
emit("correction",source="user",text="Select the replacement item shown on the support ticket before preparing the draft.",evidence_ids=["e7","e8"])
emit("action",action_id="a4",status="executed",operation={"kind":"select","target_hint":"Replacement item","text":"Replacement item"},before_event_id="e8",after_event_id="e11")
emit("observation",frame_id="frame-0005",app="shipping",text="Replacement item is selected.")
emit("action",action_id="a5",status="executed",operation={"kind":"type","target_hint":"Customer shipping address","text":"ADDRESS_1_a3f9"},before_event_id="e11",after_event_id="e13")
emit("observation",frame_id="frame-0006",app="shipping",text="Shipping address field contains the protected customer shipping address.")
emit("check",check_id="c1",result="passed",source="core_verifier",criterion="Destination value equals the selected source value.",evidence_ids=["e1","e12","e13"])
emit("action",action_id="a6",status="blocked",operation={"kind":"click","target_hint":"Purchase shipping label"},before_event_id="e13")
emit("action",action_id="a7",status="executed",operation={"kind":"click","target_hint":"Prepare draft"},before_event_id="e13",after_event_id="e17")
emit("observation",frame_id="frame-0007",app="shipping",text="Replacement shipment draft ready for review. Order, replacement item, and destination are populated.")
emit("check",check_id="c2",result="passed",source="core_verifier",criterion="Draft contains the selected order, replacement item, and matching shipping destination; no purchase was made.",evidence_ids=["e6","e11","e13","e16","e17"])
fixture.mkdir(parents=True,exist_ok=True)
(fixture/"events.jsonl").write_text("".join(json.dumps(e)+"\n" for e in events),encoding="utf-8")
m={"schema_version":"1.0","recording_id":"recording-demo-001","task":"Prepare a replacement shipment draft from a support ticket.","capture_mode":"enriched","provenance":{"producer":"plva-synthetic-fixture","data_class":"synthetic","privacy_policy_version":"synthetic-v1"},"environment":{"kind":"browser","apps":["support","shipping"]},"events_file":"events.jsonl","frames":frames,"outcome":{"status":"passed","check_ids":["c1","c2"]}}
save(fixture/"manifest.json",m)
# Changed interface is a synthetic INPUT for the external runtime, not a rerun result.
changed=ROOT/"fixtures/changed-layout"; changed.mkdir(parents=True,exist_ok=True)
im=Image.new("RGB",(800,480),"#fff8e9"); d=ImageDraw.Draw(im)
d.text((30,20),"SYNTHETIC RUN B - input only, not executed",fill="black")
for xy,line in [((470,110),"Destination: ADDRESS_7_b812"),((40,300),"Order: DEMO-205"),((40,160),"Item: Replacement item"),((470,380),"Save for review")]: d.text(xy,line,fill="#333333")
im.save(changed/"screen.png")
save(changed/"scenario.json",{"kind":"synthetic_input","layout_changes":["Destination moved above order","Prepare draft renamed Save for review"],"order_id":"DEMO-205","session_token":"ADDRESS_7_b812","live_runner_status":"pending"})
save(ROOT/"fixtures/new-run-bindings.json",{"customer_shipping_address":"ADDRESS_7_b812","order_id":"DEMO-205"})
save(ROOT/"fixtures/capabilities.json",["observe","navigate","type","select","click"])
# Digest algorithm frozen: sha256(canonical JSON of path -> sha256(file bytes)), required files only.
files=["manifest.json","events.jsonl"]+[f["path"] for f in frames]
parts={p:hashlib.sha256((fixture/p).read_bytes()).hexdigest() for p in files}
bundle_digest=hashlib.sha256(json.dumps(parts,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()
registry={"schema_version":"1.0","approvals":[{"bundle_digest":bundle_digest,"producer":"plva-synthetic-fixture","data_class":"synthetic","allow_cloud":False,"role_hints_trusted":True}]}
save(ROOT/"src/plva_skill_learning/data/trusted-synthetic.json",registry)
save(ROOT/"fixtures/trusted-synthetic.json",registry)

# Keep the visual demo available when regenerating all synthetic fixtures.
from build_hd_fixtures import build as build_hd
build_hd()
