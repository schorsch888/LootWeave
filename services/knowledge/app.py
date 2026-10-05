"""GameKnowledge API with explicit versions and verified bundled-file identities."""
from __future__ import annotations

import hashlib
from pathlib import Path

from contracts import DomainError, canonical, context, digest, identifier, object_value, parse_json, require
from services.knowledge.domain import validate_pack


class Knowledge:
    def __init__(self, pack_dir: Path):
        pack_dir = pack_dir.resolve()
        index = parse_json((pack_dir / "index.json").read_bytes())
        require(index.get("contract_version") == 1 and index.get("algorithm") == "sha256",
                "incompatible_pack_index")
        require(isinstance(index.get("packs"), list), "invalid_pack_index")
        self.packs = {}
        for entry in index["packs"]:
            require(isinstance(entry, dict) and isinstance(entry.get("file"), str), "invalid_pack_index")
            path = (pack_dir / entry["file"]).resolve()
            require(path.parent == pack_dir and path.suffix == ".json" and path.name != "index.json",
                    "invalid_pack_path")
            raw = path.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == entry.get("sha256"), "pack_file_integrity_error")
            pack = validate_pack(parse_json(raw))
            key = (pack["pack_id"], pack["version"])
            require(key not in self.packs, "duplicate_pack_version")
            self.packs[key] = canonical({"pack": pack, "pack_hash": digest(pack)})
        require(bool(self.packs), "knowledge_packs_missing", 503)

    def handle(self, method, path, _body):
        if method == "GET" and path == "/v1/health":
            return {"service": "knowledge", "contract_version": 1}
        if method == "GET" and path == "/v1/packs":
            result = []
            for value in self.packs.values():
                decoded = parse_json(value)
                pack = decoded["pack"]
                metadata = {key: pack[key] for key in
                            ("pack_id", "version", "context", "class_id", "scenario", "execution_policy")}
                metadata["pack_hash"] = decoded["pack_hash"]
                if pack.get("item_dependencies"):
                    metadata["dependency_templates"] = [
                        {"template_id": item["template_id"], "label": item["template_name"]}
                        for item in pack["item_dependencies"]]
                result.append(metadata)
            return {"contract_version": 1, "packs": result}
        if method == "POST" and path == "/v1/item-dependencies":
            body = object_value(_body)
            pack_id = identifier(body.get("pack_id"))
            version = identifier(body.get("pack_version"))
            key = (pack_id, version)
            require(key in self.packs, "pack_version_not_found", 404)
            decoded = parse_json(self.packs[key])
            pack = decoded["pack"]
            require(body.get("pack_hash") == decoded["pack_hash"], "pack_hash_conflict", 409)
            request_context = context(body.get("context"))
            require(request_context == pack["context"] and body.get("class_id") == pack["class_id"],
                    "dependency_scope_mismatch", 409)
            require(pack.get("execution_policy") == "research_only" and pack.get("item_dependencies"),
                    "dependency_data_unavailable", 404)
            template_id = identifier(body.get("template_id"))
            dependency = next((item for item in pack["item_dependencies"]
                               if item["template_id"] == template_id), None)
            require(dependency is not None, "dependency_template_not_found", 404)
            evidence_by_id = {item["id"]: item for item in pack["evidence"]}
            return {"contract_version": 1, "record_kind": "item_template_dependency",
                    "scope": "reviewed_static_only", "mechanics_accepted": False,
                    "pack_id": pack_id, "pack_version": version, "pack_hash": decoded["pack_hash"],
                    "context": request_context, "class_id": pack["class_id"],
                    "dependency": dependency,
                    "evidence": [evidence_by_id[evidence_id] for evidence_id in dependency["evidence_ids"]]}
        parts = path.strip("/").split("/")
        if method == "GET" and len(parts) == 4 and parts[:2] == ["v1", "packs"]:
            key = (identifier(parts[2]), identifier(parts[3]))
            require(key in self.packs, "pack_version_not_found", 404)
            return parse_json(self.packs[key])
        raise DomainError("not_found", 404)
