"""Independent static validation of build-25690430 numerical derivatives.

Reads exported data and the native binary as bytes. Does not import the
extractor/decoder and never loads or executes game assemblies.
"""
import collections
import hashlib
import json
import math
import re
import struct
import argparse
import os
from pathlib import Path
from deskrawl_paths import REPO_ROOT, repo_path, resolve_source, source_label

ROOT = REPO_ROOT / 'data/extracted/deskrawl/25690430'
REPORT = REPO_ROOT / 'research/extraction-validation.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_tree(flat):
    stack = []
    root = None
    for item in flat:
        node = dict(item, children=[])
        depth = item['m_Level']
        while stack and stack[-1]['m_Level'] >= depth:
            stack.pop()
        if stack:
            stack[-1]['children'].append(node)
        else:
            assert root is None
            root = node
        stack.append(node)
    return root


def raw_numbers(value, path='$'):
    if isinstance(value, dict):
        if {'hiddenValue', 'currentCryptoKey', 'hash'} <= value.keys():
            yield path, value
        for name, item in value.items():
            yield from raw_numbers(item, path + '.' + name)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from raw_numbers(item, f'{path}[{i}]')


def typed_numbers(node, value, schemas, path='$'):
    typ = node['m_Type']
    if typ in ('ObscuredFloat', 'ObscuredInt', 'ObscuredLong'):
        yield path, typ, value
        return
    children = node['children']
    if isinstance(value, list) and children and children[0]['m_Type'] == 'Array':
        element = children[0]['children'][1]
        for i, item in enumerate(value):
            yield from typed_numbers(element, item, schemas, f'{path}[{i}]')
    elif isinstance(value, dict):
        if typ == 'ReferencedObject' and value.get('type', {}).get('class'):
            ref = value['type']
            fullname = (ref['ns'] + '.' if ref['ns'] else '') + ref['class']
            yield from typed_numbers(schemas[ref['asm'] + ':' + fullname], value['data'], schemas, path + '.data')
        for child in children:
            if child['m_Type'] != 'ReferencedObjectData' and child['m_Name'] in value:
                yield from typed_numbers(child, value[child['m_Name']], schemas, path + '.' + child['m_Name'])


def independent_decode(typename, raw):
    width = 64 if typename == 'ObscuredLong' else 32
    hidden = (raw['hiddenValue'] % (1 << width)).to_bytes(width // 8, 'little')
    key = raw['currentCryptoKey'] % (1 << width)
    if typename == 'ObscuredFloat':
        assert not any(raw['hiddenValueOldByte4'].values())
        # Independently express the native byte exchange, without bit masks.
        reordered = bytes([hidden[0], hidden[2], hidden[1], hidden[3]])
        bits = int.from_bytes(reordered, 'little') ^ key
        decoded = struct.unpack('<f', bits.to_bytes(4, 'little'))[0]
        mixed = (bits ^ key).to_bytes(4, 'little')
        encoded = bytes([mixed[0], mixed[2], mixed[1], mixed[3]])
        assert math.isfinite(decoded)
        assert struct.pack('<f', decoded) == bits.to_bytes(4, 'little')
    else:
        bits = ((int.from_bytes(hidden, 'little') - key) % (1 << width)) ^ key
        decoded = int.from_bytes(bits.to_bytes(width // 8, 'little'), 'little', signed=True)
        encoded = (((bits ^ key) + key) % (1 << width)).to_bytes(width // 8, 'little')
    assert encoded == hidden
    return decoded, bits


def main():
    global ROOT, REPORT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, default=os.environ.get('DESKRAWL_GAME_DIR'), help='Read-only game installation directory; alternatively DESKRAWL_GAME_DIR.')
    parser.add_argument('--steam-manifest', type=Path)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path, default=REPORT)
    parser.add_argument('--address-dll', type=Path, help='Optional override when generated address DLL is outside the repository.')
    args = parser.parse_args()
    if args.game is None:
        parser.error('Provide --game or DESKRAWL_GAME_DIR.')
    ROOT, REPORT = repo_path(args.source_root), repo_path(args.report)
    def source(value):
        return resolve_source(value, game=args.game, steam_manifest=args.steam_manifest)
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    numeric = json.loads((ROOT / 'numeric-decoding.json').read_text(encoding='utf-8'))
    address_source = numeric['method_address_source']
    assert digest(args.address_dll or source(address_source['path'])) == address_source['sha256']
    records = [json.loads(x) for x in (ROOT / 'objects.jsonl').read_text(encoding='utf-8').splitlines()]
    schemas = {key: make_tree(flat) for key, flat in json.loads((ROOT / 'type-trees.json').read_text(encoding='utf-8')).items()}
    binary_path = next(s['path'] for s in manifest['source_files'] if s['path'].endswith('GameAssembly.dll'))
    binary = source(binary_path).read_bytes()
    pe = int.from_bytes(binary[0x3c:0x40], 'little')
    assert binary[pe:pe + 4] == b'PE\0\0'
    section_count, optional_size = struct.unpack_from('<H', binary, pe + 6)[0], struct.unpack_from('<H', binary, pe + 20)[0]
    sections = [struct.unpack_from('<8sIIII', binary, pe + 24 + optional_size + i * 40) for i in range(section_count)]
    method_checks = []
    for method in numeric['methods']:
        section = next(s for s in sections if s[2] <= method['rva'] < s[2] + max(s[1], s[3]))
        computed_offset = method['rva'] - section[2] + section[4]
        expected = bytes.fromhex(method['hex'])
        assert computed_offset == method['offset']
        assert binary[computed_offset:computed_offset + len(expected)] == expected
        method_checks.append(dict(type=method['type'], method=method['method'], rva=method['rva'], offset=computed_offset, hex=expected.hex(), bytes_match=True, pe_mapping_matches=True))
    assert len(method_checks) == 6
    counts = collections.Counter()
    groups = collections.defaultdict(set)
    seen_objects = set()
    for record in records:
        assert record['object_id'] not in seen_objects
        seen_objects.add(record['object_id'])
        assert record['expected_byte_size'] == record['consumed_bytes']
        assert all(record['validation'][key] for key in ('full_byte_count', 'builtin_header_matches', 'strict_parser_success'))
        raw = dict(raw_numbers(record['data']))
        typed_list = list(typed_numbers(schemas['Assembly-CSharp:' + record['class_name']], record['data'], schemas))
        typed = {path: (typename, item) for path, typename, item in typed_list}
        assert len(typed) == len(typed_list)
        derived_list = record.get('derived_numeric_fields', [])
        derived = {item['field']: item for item in derived_list}
        assert len(derived) == len(derived_list)
        assert raw.keys() == typed.keys() == derived.keys(), record['object_id']
        for path, (typename, item) in typed.items():
            out = derived[path]
            value, bits = independent_decode(typename, item)
            assert typename == out['serialized_type']
            assert value == out['value']
            assert bits == int(out['decoded_bits_hex'], 16)
            assert item['hash'] == out['raw_hash']
            assert out['roundtrip_matches'] is True
            counts[typename] += 1
            if typename == 'ObscuredFloat':
                groups[item['hash']].add(bits)
    assert dict(counts) == numeric['decoded_counts']
    assert not numeric['derivation_errors']
    assert all(len(bits) == 1 for bits in groups.values())
    source_checks = []
    for item in manifest['source_files']:
        if 'appmanifest_' in item['path']:
            continue
        path = source(item['path'])
        observed = digest(path)
        source_checks.append(dict(path=source_label(path, game=args.game), expected_sha256=item['sha256'], observed_sha256=observed, matches=observed == item['sha256']))
    assert all(x['matches'] for x in source_checks)
    acf = source('steam://appmanifest_4623570.acf')
    build = re.search(r'"buildid"\s+"(\d+)"', acf.read_text(encoding='utf-8')).group(1)
    assert build == '25690430'
    baseline = REPORT if REPORT.is_file() else REPO_ROOT / 'research/extraction-validation.json'
    report = json.loads(baseline.read_text(encoding='utf-8'))
    report['status'] = 'structural_and_serialized_numeric_validation_complete'
    report['numeric_semantics'] = {
        'status': 'verified_build_25690430_serialized_numeric_conversion',
        'independent_validator': 'scripts/validate_deskrawl_numeric.py',
        'independent_validator_sha256': digest(__file__),
        'decoder_imported_or_used': False,
        'game_code_executed': False,
        'native_methods': method_checks,
        'method_address_source_hash_matches': True,
        'method_identity_note': 'Symbolic method identities use the Cpp2IL Address attributes documented in numeric-decoding.json; binary bytes, PE address mapping and conversion instruction semantics were independently checked without native execution.',
        'native_instruction_semantics_review': 'Float encode XORs then exchanges byte offsets 1 and 2; decode reverses exchange then XORs. Int and Long encode XOR then add key; decode subtracts key then XORs. Register widths establish modulo 2^32/2^64.',
        'decoded_counts': dict(counts),
        'coverage': 'Independent flat-type-tree traversal, including concrete managed types, matched all raw encrypted structures and all derived field paths one-to-one.',
        'derived_value_bit_and_raw_hash_failures': 0,
        'byte_reencoding_failures': 0,
        'float_nonfinite_values': 0,
        'float_hash_groups': len(groups),
        'float_hash_group_conflicts': 0,
        'raw_obscured_structures_preserved': True,
        'limits': ['Only serialized numeric conversion verified; units, stat scaling, enhancement formulas, combat order, runtime requirements and live server overrides remain outside this check.', 'All sampled legacy hiddenValueOldByte4 fields were zero; nonzero legacy migration was not validated.'],
    }
    report['source_provenance_validation'] = {
        'static_build': build,
        'source_file_sha256_checks': source_checks,
        'immutable_game_sources_match': True,
        'steam_build_identity': {'source': 'steam://appmanifest_4623570.acf', 'appid': '4623570', 'buildid': build},
        'steam_manifest_note': 'Only application and build identity are retained. Steam mutable state, activity times and ACF file hashes are omitted.',
    }
    report['local_facts'].pop('appmanifest_hash_matches', None)
    names = list(report['local_facts']['hashes']) + ['numeric-decoding.json', 'type-trees.json']
    report['local_facts']['hashes'] = {name: digest(ROOT / name) for name in names}
    report['limitations'] = [x for x in report['limitations'] if 'numeric ObscuredFloat/Int/Long semantics are not verified' not in x]
    report['limitations'] = list(dict.fromkeys(report['limitations'] + ['Serialized encrypted-number conversion is verified; interpretation as game-rule units or formulas is separate and remains outside this validation.']))
    index = {x['object_id']: x for x in records}
    for check in report['checks']:
        check['unknown'] = [x for x in check.get('unknown', []) if 'ObscuredFloat' not in x and 'numeric values' not in x]
        if check['id'] == 'normal_rune_skill':
            check['unknown'] = list(dict.fromkeys(check['unknown'] + ['Runtime formula applying EveryNRuneLevels and leveled attributes has not been verified.']))
        sample_ids = []
        def collect_ids(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ('object_id', 'set_object', 'target_id') and isinstance(item, str) and item in index:
                        sample_ids.append(item)
                    collect_ids(item)
            elif isinstance(value, list):
                for item in value:
                    collect_ids(item)
        collect_ids(check['local'])
        check['verified_decoded_fields'] = {oid: index[oid].get('derived_numeric_fields', []) for oid in sorted(set(sample_ids)) if index[oid].get('derived_numeric_fields')}
        if check['status'] == 'pass_structure_partial_numeric_semantics':
            check['status'] = 'pass_static_serialized_numeric_values'
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'objects': len(records), 'counts': dict(counts), 'native_methods': len(method_checks), 'float_groups': len(groups), 'immutable_sources_match': True, 'steam_build_identity_matches': True, 'failures': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
