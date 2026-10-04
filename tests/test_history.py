"""Historical ownership, corruption rejection and comparable confirmed build identity."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from contracts import DomainError, canonical, digest
from services.evaluation.app import Evaluation
from services.evaluation.domain import EVALUATOR_VERSION, evaluate
from services.knowledge.app import Knowledge
from services.profile.app import Profile
from services.profile.domain import build_fingerprint
from storage import connect

ROOT = Path(__file__).resolve().parents[1]
DEMO = json.loads((ROOT/"fixtures/demo.json").read_text(encoding="utf-8"))

class API:
    def __init__(self,app):
        self.app=app
    def call(self,method,path,body=None):
        return self.app.handle(method,path,body or {})

class BuildIdentityTests(unittest.TestCase):
    def test_capture_evidence_level_and_unequipped_candidate_do_not_change_build_identity(self):
        base=copy.deepcopy(DEMO["facts"])
        changed=copy.deepcopy(base)
        changed["captured_at"]="2026-03-01T00:00:00Z"
        changed["evidence"][0]["source_ref"]="observation://another-capture"
        changed["evidence"][0]["captured_at"]=changed["captured_at"]
        changed["candidate_item"]["affixes"][0]["value"]=999
        changed["character_level"]+=1
        self.assertEqual(build_fingerprint(base),build_fingerprint(changed))

    def test_actual_equipment_skills_conditions_and_version_change_build_identity(self):
        for kind in ("equipment","skill","condition","version"):
            base=copy.deepcopy(DEMO["facts"]); changed=copy.deepcopy(base)
            if kind=="equipment":
                changed["equipped_items"]["weapon"]["affixes"][0]["value"]+=1
            elif kind=="skill":
                changed["skills"][0]["rank"]+=1
            elif kind=="condition":
                changed["conditions"]["hero_cast"]="inactive"
            else:
                changed["context"]["game_build"]="2"
            with self.subTest(kind=kind):
                self.assertNotEqual(build_fingerprint(base),build_fingerprint(changed))

class HistoricalStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        data=Path(self.temp.name)
        self.profile=Profile(data/"profile")
        self.knowledge=Knowledge(ROOT/"knowledge-packs")
        self.evaluation=Evaluation(data/"evaluation",API(self.profile),API(self.knowledge))
        self.observation={"observation_id":"demo-text","method":"text","raw_text":"Synthetic"}
        self.profile.observe(self.observation)
        self.profile.confirm({"request_id":"confirm","profile_id":"demo","observation_id":"demo-text",
                              "expected_revision":0,"player_confirmed":True,"facts":copy.deepcopy(DEMO["facts"])})
        pack=next(p for p in self.knowledge.handle("GET","/v1/packs",{})["packs"] if p["execution_policy"]=="synthetic_only")
        self.body={"request_id":"evaluation-1","profile_id":"demo","profile_revision":1,
                   "pack_id":pack["pack_id"],"pack_version":pack["version"],"pack_hash":pack["pack_hash"],
                   "intent":copy.deepcopy(DEMO["intent"])}

    def test_observation_read_keeps_its_unconfirmed_shape(self):
        result=self.profile.handle("GET","/v1/observations/demo-text",{})
        self.assertEqual("unconfirmed",result["state"])
        self.assertEqual("Synthetic",result["raw_text"])
        self.assertNotIn("facts",result)
        with self.assertRaisesRegex(DomainError,"not_found"):
            self.profile.handle("GET","/v1/unknown",{})

    def test_historical_list_is_frozen_and_does_not_fetch_current_source_services(self):
        result=self.evaluation.create(self.body)
        self.profile=None; self.knowledge=None
        self.evaluation.profile=API(None); self.evaluation.knowledge=API(None)
        listing=self.evaluation.handle("GET","/v1/evaluations",{})
        self.assertEqual([{"evaluation_id":result["evaluation_id"],"retention":result["retention"],"pin":result["pin"]}],
                         listing["evaluations"])
        self.assertEqual(100,listing["limit"])
        self.assertTrue(self.evaluation.replay("evaluation-1")["identical"])

    def test_idempotent_fetch_and_list_reject_corrupted_result(self):
        self.evaluation.create(self.body)
        with connect(self.evaluation.database) as db:
            db.execute("UPDATE evaluations SET result=? WHERE id=?",('{"retention":"keep"}',"evaluation-1"))
        for read in (lambda:self.evaluation.create(self.body),self.evaluation.recent,
                     lambda:self.evaluation.read("evaluation-1")):
            with self.subTest(read=read),self.assertRaisesRegex(DomainError,"evaluation_integrity_error"):
                read()

    def test_archived_evaluator_replays_without_source_services_or_relabeling(self):
        cases = [case for version in ("0.1.0", "0.1.1", "0.1.2", "0.1.3")
                 for case in json.loads((ROOT/f"fixtures/evaluation-{version}.json").read_text(encoding="utf-8"))["cases"]]
        bodies = []
        for case in cases:
            inputs = case["inputs"]
            result = {"evaluation_id": case["evaluation_id"],
                      **evaluate(inputs["profile"], inputs["knowledge"], inputs["intent"],
                                 evaluator_version=inputs["evaluator_version"])}
            self.assertEqual(case["result_hash"], digest(result))
            body = {"request_id": case["evaluation_id"], "profile_id": inputs["profile"]["profile_id"],
                    "profile_revision": inputs["profile"]["revision"],
                    "pack_id": inputs["knowledge"]["pack"]["pack_id"],
                    "pack_version": inputs["knowledge"]["pack"]["version"],
                    "pack_hash": inputs["knowledge"]["pack_hash"], "intent": inputs["intent"]}
            bodies.append(body)
            with connect(self.evaluation.database) as db:
                db.execute("INSERT INTO evaluations VALUES (?,?,?,?,?)",
                           (case["evaluation_id"], digest(body), canonical(inputs),
                            canonical(result), case["result_hash"]))
        self.evaluation.profile = API(None)
        self.evaluation.knowledge = API(None)
        for case, body in zip(cases, bodies):
            with self.subTest(case=case["evaluation_id"]):
                self.assertEqual(case["result_hash"], digest(self.evaluation.create(body)))
                for _ in range(10):
                    replay = self.evaluation.replay(case["evaluation_id"])
                    self.assertTrue(replay["identical"])
                    self.assertEqual(case["inputs"]["evaluator_version"], replay["result"]["pin"]["evaluator_version"])
                    self.assertEqual(case["result_hash"], digest(replay["result"]))
        self.assertEqual(24, len(self.evaluation.recent()["evaluations"]))

    def test_new_evaluations_pin_the_corrected_engine(self):
        result = self.evaluation.create(self.body)
        self.assertEqual("0.1.5", EVALUATOR_VERSION)
        self.assertEqual(EVALUATOR_VERSION, result["pin"]["evaluator_version"])
        self.assertEqual(result, self.evaluation.replay(result["evaluation_id"])["result"])

    def test_unavailable_historical_engine_is_rejected(self):
        self.evaluation.create(self.body)
        with connect(self.evaluation.database) as db:
            encoded = db.execute("SELECT inputs FROM evaluations WHERE id=?", ("evaluation-1",)).fetchone()[0]
            inputs = json.loads(encoded)
            inputs["evaluator_version"] = "9.9.9"
            db.execute("UPDATE evaluations SET inputs=? WHERE id=?", (canonical(inputs), "evaluation-1"))
        with self.assertRaisesRegex(DomainError, "evaluator_version_unavailable"):
            self.evaluation.replay("evaluation-1")

    def test_profile_rejects_corrupted_facts_and_build_metadata(self):
        original=self.profile.read("demo",1)
        for field in ("facts","build_hash"):
            changed=copy.deepcopy(original)
            if field=="facts":
                changed["facts"]["character_level"]+=1
            else:
                changed["build_hash"]="0"*64
            with connect(self.profile.database) as db:
                db.execute("UPDATE revisions SET payload=? WHERE profile_id=? AND revision=?",(canonical(changed),"demo",1))
            with self.subTest(field=field),self.assertRaisesRegex(DomainError,"profile_integrity_error"):
                self.profile.read("demo",1)
            with connect(self.profile.database) as db:
                db.execute("UPDATE revisions SET payload=? WHERE profile_id=? AND revision=?",(canonical(original),"demo",1))

if __name__=="__main__":
    unittest.main()
