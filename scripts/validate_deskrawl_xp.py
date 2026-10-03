"""Verify local sources against the reviewed Deskrawl XP evidence (no game execution)."""
import argparse
import hashlib
import json
import os
import struct
from pathlib import Path

from deskrawl_paths import REPO_ROOT, repo_path, resolve_source


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, default=os.environ.get('DESKRAWL_GAME_DIR'))
    parser.add_argument('--source-root', type=Path,
                        default=REPO_ROOT / 'data/extracted/deskrawl/25690430')
    parser.add_argument('--evidence', type=Path,
                        default=REPO_ROOT / 'research/experience-penalty.json')
    args = parser.parse_args()
    if args.game is None:
        parser.error('Provide --game or DESKRAWL_GAME_DIR.')
    evidence = json.loads(repo_path(args.evidence).read_text(encoding='utf-8'))
    source_root = repo_path(args.source_root)
    manifest = json.loads((source_root / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['build_id'] == evidence['build_id'], 'extraction build mismatch'
    for source in evidence['sources']:
        path = ((source_root / 'objects.jsonl') if source['path'].endswith('/objects.jsonl')
                else resolve_source(source['path'], game=args.game))
        assert sha256(path) == source['sha256'], source['path'] + ': hash mismatch'

    records = {r['object_id']: r for r in
               (json.loads(line) for line in (source_root / 'objects.jsonl')
                .read_text(encoding='utf-8').splitlines())}
    config = records[evidence['release_config']['object_id']]
    assert config['class_name'] == 'GameConfig'
    assert config['expected_byte_size'] == config['consumed_bytes']
    assert all(config['validation'].values())
    for key, value in evidence['release_config']['fields'].items():
        assert config['data'][key] == value, key
    tiers = [{'difficulty': t['Difficulty'], 'exp_multiplier': t['ExpMultiplier']}
             for t in config['data']['DifficultyTiers']]
    assert tiers == evidence['release_config']['difficulty_exp_multipliers']
    manager = records[evidence['scene_binding']['object_id']]
    assert manager['class_name'] == 'GameManager'
    link = next(r for r in manager['references'] if r['field'] == '$.Config')
    assert link['target_id'] == config['object_id'] and link['target_parsed']

    binary = resolve_source('game://GameAssembly.dll', game=args.game).read_bytes()
    pe = struct.unpack_from('<I', binary, 0x3c)[0]
    assert binary[pe:pe + 4] == b'PE\0\0'
    count = struct.unpack_from('<H', binary, pe + 6)[0]
    optional_size = struct.unpack_from('<H', binary, pe + 20)[0]
    sections = [struct.unpack_from('<8sIIII', binary, pe + 24 + optional_size + i * 40)
                for i in range(count)]

    def offset(rva, size):
        section = next(s for s in sections if s[2] <= rva and rva + size <= s[2] + s[3])
        return rva - section[2] + section[4]

    for method in evidence['native_methods']:
        start = offset(method['rva'], method['length'])
        assert start == method['offset'], method['name'] + ': PE mapping'
        code = binary[start:start + method['length']]
        assert hashlib.sha256(code).hexdigest() == method['sha256'], method['name']
    for constant in evidence['constants']:
        size = struct.calcsize(constant['format'])
        assert struct.unpack_from(constant['format'], binary,
                                  offset(constant['rva'], size))[0] == constant['value']
    print(json.dumps({
        'build_id': evidence['build_id'],
        'source_hash_checks': len(evidence['sources']),
        'native_method_hash_and_pe_mapping_checks': len(evidence['native_methods']),
        'constant_checks': len(evidence['constants']),
        'release_config_and_scene_binding': 'pass',
        'status': 'pass_static_source_and_evidence_identity',
        'limits': 'Checks reviewed evidence identity; no game execution, behavioral experiment or server verification.'
    }, ensure_ascii=False))


if __name__ == '__main__':
    main()
