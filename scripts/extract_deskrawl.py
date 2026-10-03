"""Extract static gameplay definitions. All game files are opened read-only.

No save, process memory, game execution, art or audio export is performed.
Requires isolated UnityPy and dummy type DLLs generated from static IL2CPP files.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import copy
import math
from importlib.metadata import version as package_version
from deskrawl_paths import source_label, repo_path, safe_error

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / '.tools' / 'unitypy'))
ASSETS = ('resources.assets', 'sharedassets0.assets', 'globalgamemanagers.assets', 'level0')
TABLES = {'Stats', 'Slaves', 'Talents', 'Items', 'Equipments', 'World', 'Abilities', 'Lifeskills', 'UI'}
EXCLUDED = {'AudioConfig', 'GraphicsConfig', 'LeaderboardCodex'}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def selected(class_name):
    return class_name not in EXCLUDED and (
        class_name.endswith(('Data', 'Config')) or
        class_name.startswith(('EquipmentEffect_', 'TalentEffect_', 'LifeSkillEffect_')) or
        class_name in {'RandomEquipment', 'RecipeBook', 'Enemy', 'TriggerEffectOnStatus', 'GameManager'})


def walk_refs(value, field='$'):
    if isinstance(value, dict):
        if set(value) == {'m_FileID', 'm_PathID'}:
            yield field, value
        else:
            for key, child in value.items():
                yield from walk_refs(child, f'{field}.{key}')
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_refs(child, f'{field}[{index}]')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--game', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--dummy', required=True, type=Path)
    parser.add_argument('--steam-manifest', type=Path, help='Steam appmanifest used only for app/build identity; its hash is not exported.')
    parser.add_argument('--headers', type=Path, default=PROJECT / '.tools/cpp2il/deskrawl-25690430-types/DiffableCs')
    parser.add_argument('--address-dll', type=Path, default=PROJECT / '.tools/cpp2il/deskrawl-25690430-addresses/ACTk.Runtime.dll')
    parser.add_argument('--cpp2il', type=Path, default=PROJECT / '.tools/cpp2il/Cpp2IL.exe', help='Pinned research tool used to generate the local types; verified as bytes, not executed by this extractor.')
    parser.add_argument('--toolchain', type=Path, default=PROJECT / 'research/toolchain-provenance.json')
    args = parser.parse_args()
    toolchain = json.loads(repo_path(args.toolchain).read_text(encoding='utf-8'))
    cpp2il_provenance = toolchain['cpp2il']
    if digest(repo_path(args.cpp2il)) != cpp2il_provenance['sha256']:
        raise ValueError('Cpp2IL differs from the pinned research tool; abort.')
    for name, expected in toolchain['direct_python_dependencies'].items():
        if package_version(name) != expected['version']:
            raise ValueError('Research dependency version mismatch: ' + name)
    import UnityPy
    from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
    from UnityPy.helpers.TypeTreeNode import TypeTreeNode
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams.EndianBinaryReader import EndianBinaryReader
    from deskrawl_managed_refs import repair_managed_nodes, install_ref_resolver
    from deskrawl_numeric import METHODS, verify_methods, collect as collect_numeric
    # Python reader reports actual position on failure rather than consuming the
    # entire outer block before its native reader validates the inner layout.
    TypeTreeHelper.read_typetree_boost = None

    args.game = args.game.resolve()
    args.out = repo_path(args.out)
    args.dummy = repo_path(args.dummy)
    args.headers = repo_path(args.headers)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.steam_manifest or args.game.parents[1] / 'appmanifest_4623570.acf'
    build_match = re.search(r'"buildid"\s+"(\d+)"', manifest_path.read_text(encoding='utf-8'))
    if not build_match or build_match.group(1) != '25690430':
        raise ValueError('Expected Steam build 25690430; abort without mixing versions.')
    verify_methods(args.game / 'GameAssembly.dll')
    source_paths = [args.game / 'Deskrawl_Data' / name for name in ASSETS]
    immutable_paths = source_paths + [args.game / 'GameAssembly.dll',
        args.game / 'Deskrawl_Data' / 'il2cpp_data' / 'Metadata' / 'global-metadata.dat']
    starting_hashes = {str(path): digest(path) for path in immutable_paths}
    env = UnityPy.load(*(str(path) for path in source_paths))
    unity_version = next(iter(env.objects)).assets_file.unity_version
    generator = TypeTreeGenerator(unity_version)
    generator.load_local_dll_folder(str(args.dummy))
    schemas = {}
    schema_exports = {}
    all_objects = {(obj.assets_file.name, obj.path_id): obj for obj in env.objects}
    indexes, records, errors, external_maps = [], [], [], {}
    localization_counts = {}
    attempted_classes = Counter()
    all_mb_classes = Counter()
    numeric_counts = Counter()
    numeric_errors = []
    float_hash_bits = {}
    repairs = []

    def primitive(parent, name, typ, size, aligned=False):
        return {'m_Level': parent['m_Level'] + 1, 'm_Name': name,
                'm_Type': typ, 'm_ByteSize': size, 'm_Version': 1,
                'm_MetaFlag': 16384 if aligned else 0, 'm_TypeFlags': 0}

    def repair_nodes(nodes, key):
        nodes = copy.deepcopy(nodes)
        if key.endswith(':MapData'):
            # Exact-build MapData.cs declares a private [SerializeField] string
            # between GatherableMeanPerTile and Gatherables.
            start = next(i for i, n in enumerate(nodes) if n['m_Level'] == 1 and n['m_Name'] == 'm_Name')
            end = next((i for i in range(start+1, len(nodes)) if nodes[i]['m_Level'] <= 1), len(nodes))
            field = copy.deepcopy(nodes[start:end])
            field[0]['m_Name'] = '_gatherablePoissonPreview'
            place = next(i for i, n in enumerate(nodes) if n['m_Level'] == 1 and n['m_Name'] == 'Gatherables')
            nodes[place:place] = field
            repairs.append({'schema': key, 'field': '_gatherablePoissonPreview', 'repair': 'MapData.cs private SerializeField string'})
        if key.endswith(':Enemy'):
            # Enemy inherits Character._level, a serialized private ObscuredInt.
            place = next(i for i, n in enumerate(nodes) if n['m_Level'] == 1 and n['m_Name'] == 'BaseMaxHealth')
            nodes.insert(place, {'m_Level': 1, 'm_Name': '_level', 'm_Type': 'ObscuredInt', 'm_MetaFlag': 0})
            repairs.append({'schema': key, 'field': '_level', 'repair': 'Character.cs private SerializeField ObscuredInt'})
        result = []
        for index, node in enumerate(nodes):
            node = copy.deepcopy(node)
            if node['m_Level'] == 1 and node['m_Name'] == 'm_Enabled':
                node['m_MetaFlag'] = node.get('m_MetaFlag', 0) | 16384
            # AssetsTools incorrectly labels List<String> as a scalar string;
            # scalar strings have char elements, lists have string elements.
            if node['m_Type'] == 'string' and index + 3 < len(nodes):
                child = nodes[index + 3]
                if child['m_Name'] == 'data' and child['m_Type'] == 'string':
                    node['m_Type'] = 'vector'
                    repairs.append({'schema': key, 'field': node['m_Name'], 'repair': 'List<String> vector'})
            result.append(node)
            if node['m_Type'] in ('ObscuredFloat', 'ObscuredInt', 'ObscuredLong'):
                if index + 1 < len(nodes) and nodes[index + 1]['m_Level'] > node['m_Level']:
                    continue
                long_type = node['m_Type'] == 'ObscuredLong'
                result.extend([primitive(node, 'hash', 'int', 4),
                               primitive(node, 'hiddenValue', 'SInt64' if long_type else 'int', 8 if long_type else 4),
                               primitive(node, 'currentCryptoKey', 'SInt64' if long_type else 'int', 8 if long_type else 4)])
                if node['m_Type'] == 'ObscuredFloat':
                    byte4 = primitive(node, 'hiddenValueOldByte4', 'ACTkByte4', -1)
                    result.append(byte4)
                    result.extend(primitive(byte4, f'b{i}', 'UInt8', 1, True) for i in range(1, 5))
                repairs.append({'schema': key, 'field': node['m_Name'], 'repair': node['m_Type'] + ' SerializeField internals'})
        return result

    def get_schema(assembly, fullname):
        key = f'{assembly}:{fullname}'
        if key not in schemas:
            nodes = json.loads(generator.get_nodes_as_json(
                assembly if assembly.endswith('.dll') else assembly + '.dll', fullname))
            nodes = repair_managed_nodes(nodes, assembly, fullname, generator, headers_root=args.headers / 'Assembly-CSharp')
            nodes = repair_nodes(nodes, key)
            for node in nodes:
                node.setdefault('m_ByteSize', 0)
                node.setdefault('m_Version', 0)
            schemas[key] = TypeTreeNode.from_list(nodes)
            schema_exports[key] = nodes
        return schemas[key]

    managed_state = install_ref_resolver(get_schema)

    for obj in env.objects:
        file = obj.assets_file.name
        if file not in external_maps:
            external_maps[file] = [
                {'file_id': index + 1, 'path': ext.path, 'name': ext.name,
                 'guid_hex': ext.guid.hex() if ext.guid else None, 'type': ext.type}
                for index, ext in enumerate(obj.assets_file.externals)]
        if obj.type.name == 'TextAsset':
            text = obj.read()
            if text.m_Name in TABLES:
                content = text.m_Script
                if isinstance(content, bytes):
                    content = content.decode('utf-8-sig')
                rows = list(csv.reader(io.StringIO(content.lstrip('\ufeff'))))
                write_json(args.out / 'localization' / f'{text.m_Name}.json',
                           {'source_file': file, 'path_id': obj.path_id,
                            'object_id': f'{file}:{obj.path_id}', 'name': text.m_Name,
                            'format': 'csv', 'headers': rows[0] if rows else [],
                            'rows': rows[1:], 'byte_count_checked': obj.byte_size,
                            'content_sha256': hashlib.sha256(content.encode('utf-8')).hexdigest()})
                localization_counts[text.m_Name] = max(0, len(rows) - 1)
            continue
        if obj.type.name != 'MonoBehaviour':
            continue
        try:
            head = obj.parse_monobehaviour_head()
            script = head.m_Script.read()
        except Exception as error:
            errors.append({'source_file': file, 'path_id': obj.path_id,
                           'stage': 'header', 'error': safe_error(error)})
            continue
        if script.m_AssemblyName.removesuffix('.dll') != 'Assembly-CSharp':
            continue
        all_mb_classes[script.m_ClassName] += 1
        if not selected(script.m_ClassName):
            continue
        fullname = '.'.join(filter(None, (script.m_Namespace, script.m_ClassName)))
        record = {'object_id': f'{file}:{obj.path_id}', 'source_file': file,
                  'path_id': obj.path_id, 'class_name': script.m_ClassName,
                  'namespace': script.m_Namespace, 'assembly': script.m_AssemblyName,
                  'name': head.m_Name, 'expected_byte_size': obj.byte_size,
                  'kind': 'scriptable_definition' if head.m_GameObject.m_PathID == 0 else 'static_prefab_component'}
        attempted_classes[script.m_ClassName] += 1
        raw = obj.get_raw_data()
        bounded_reader = EndianBinaryReader(raw, endian=obj.reader.endian)
        try:
            tree = TypeTreeHelper.read_typetree(get_schema(script.m_AssemblyName, fullname), bounded_reader,
                                               byte_size=obj.byte_size, check_read=True, assetsfile=obj.assets_file)
            consumed = bounded_reader.Position
            original_script = {'m_FileID': head.m_Script.m_FileID, 'm_PathID': head.m_Script.m_PathID}
            if tree.get('m_Script') != original_script or tree.get('m_Name') != head.m_Name:
                raise ValueError('Rebuilt TypeTree header disagrees with built-in header.')
            if consumed != obj.byte_size:
                raise ValueError('Parser succeeded without consuming full object.')
            record.update(data=tree, consumed_bytes=consumed,
                          validation={'full_byte_count': consumed == obj.byte_size,
                                      'builtin_header_matches': True, 'strict_parser_success': True}, references=[])
            try:
                derived = list(collect_numeric(get_schema(script.m_AssemblyName, fullname), tree, managed_state['schemas']))
                if any(isinstance(n['value'], float) and not math.isfinite(n['value']) for n in derived):
                    raise ValueError('Nonfinite derived numerical value')
                record['derived_numeric_fields'] = derived
                for number in derived:
                    numeric_counts[number['serialized_type']] += 1
                    if number['serialized_type'] == 'ObscuredFloat':
                        float_hash_bits.setdefault(number['raw_hash'], set()).add(number['decoded_bits_hex'])
            except Exception as numerical_error:
                record['derived_numeric_fields'] = []
                numeric_errors.append({'object_id': record['object_id'], 'error': safe_error(numerical_error)})
            for field, raw in walk_refs(tree):
                path_id, file_id = raw['m_PathID'], raw['m_FileID']
                target_file = file if file_id == 0 else (
                    external_maps[file][file_id - 1]['name'] if 0 < file_id <= len(external_maps[file]) else None)
                target = all_objects.get((target_file, path_id)) if path_id else None
                record['references'].append({'field': field, 'raw': raw,
                                             'target_file': target_file,
                                             'target_id': f'{target_file}:{path_id}' if path_id else None,
                                             'resolved': target is not None if path_id else True,
                                             'target_unity_type': target.type.name if target else None})
            records.append(record)
            old_raw = args.out / 'raw-unparsed' / file / f'{obj.path_id}.bin'
            if old_raw.is_file():
                old_raw.unlink()
            indexes.append({key: record[key] for key in ('object_id', 'source_file', 'path_id',
                                                         'class_name', 'name', 'kind')})
        except Exception as error:
            position = bounded_reader.Position
            raw_path = args.out / 'raw-unparsed' / file / f'{obj.path_id}.bin'
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes(raw)
            record.update(stage='custom_fields', error=safe_error(error), consumed_bytes=None,
                          reader_position_on_error=position,
                          validation={'strict_parser_success': False, 'full_byte_count': False},
                          raw_block={'path': str(raw_path.relative_to(args.out)), 'bytes': len(raw),
                                     'sha256': hashlib.sha256(raw).hexdigest()})
            errors.append(record)
    by_class = Counter(record['class_name'] for record in records)
    exported_ids = {record['object_id'] for record in records}
    error_ids = {record.get('object_id') for record in errors}
    reference_coverage = Counter()
    for record in records:
        for reference in record['references']:
            reference['target_parsed'] = reference['target_id'] in exported_ids
            reference['target_exported'] = reference['target_parsed']
            reference['target_parse_failed'] = reference['target_id'] in error_ids
            state = ('null' if reference['target_id'] is None else 'parsed' if reference['target_parsed']
                     else 'parse_failed' if reference['target_parse_failed'] else 'source_exists_not_exported'
                     if reference['resolved'] else 'unresolved')
            reference_coverage[state] += 1
    with (args.out / 'objects.jsonl').open('w', encoding='utf-8') as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    write_json(args.out / 'object-index.json', indexes)
    write_json(args.out / 'external-references.json', external_maps)
    write_json(args.out / 'type-trees.json', schema_exports)
    headers = args.headers
    repair_sources = list((headers / 'ACTk.Runtime/CodeStage/AntiCheat/ObscuredTypes').glob('Obscured*.cs'))
    repair_sources += [headers / 'Assembly-CSharp' / name for name in ('MapData.cs', 'Character.cs', 'AbilityData.cs')]
    repair_sources += [path for path in (headers / 'Assembly-CSharp').glob('*.cs') if '[SerializeReference]' in path.read_text(encoding='utf-8-sig')]
    write_json(args.out / 'schema-repairs.json', {'build_id': build_match.group(1),
               'sources': [{'path': source_label(p), 'sha256': digest(p)} for p in repair_sources],
               'repairs': repairs, 'numeric_decoding': 'Separate derived_numeric_fields; raw structures unchanged. See numeric-decoding.json. fakeValue is not serialized.'})
    address_dll = repo_path(args.address_dll)
    write_json(args.out / 'numeric-decoding.json', {
        'build_id': build_match.group(1), 'status': 'verified_local_native_methods',
        'evidence_level': 'local static native instructions plus byte-for-byte re-encoding of every extracted numerical field',
        'method_address_source': {'path': source_label(address_dll), 'sha256': digest(address_dll),
                                 'format': 'Cpp2IL attributeinjector Address/RVA/Offset/Length attributes'},
        'methods': METHODS,
        'algorithms': {'ObscuredFloat': 'float32_from_bits(swap_bytes_1_2(hiddenValue) XOR currentCryptoKey)',
                       'ObscuredInt': 'signed32(((hiddenValue-currentCryptoKey) mod 2^32) XOR currentCryptoKey)',
                       'ObscuredLong': 'signed64(((hiddenValue-currentCryptoKey) mod 2^64) XOR currentCryptoKey)'},
        'decoded_counts': dict(numeric_counts), 'derivation_errors': numeric_errors,
        'float_hash_group_count': len(float_hash_bits),
        'float_hash_groups_with_conflicting_bits': sum(len(bits) > 1 for bits in float_hash_bits.values()),
        'raw_fields_preserved': True, 'game_code_executed': False,
        'limits': ['Numerical decoding does not establish stat units, combat calculation order or runtime formulas.',
                   'Legacy nonzero hiddenValueOldByte4 migration is not implemented and fails explicitly.']})
    write_json(args.out / 'parse-errors.json', errors)
    duplicate_names = Counter((record['class_name'], record['name']) for record in records)
    write_json(args.out / 'duplicate-definitions.json', [
        {'class_name': key[0], 'name': key[1], 'object_ids': [record['object_id'] for record in records
                                                           if (record['class_name'], record['name']) == key]}
        for key, count in duplicate_names.items() if count > 1])
    provenance_paths = source_paths + [args.game / 'GameAssembly.dll',
                                     args.game / 'Deskrawl_Data' / 'il2cpp_data' / 'Metadata' / 'global-metadata.dat']
    provenance = [{'path': source_label(path, game=args.game), 'bytes': path.stat().st_size, 'sha256': digest(path)}
                  for path in provenance_paths]
    immutable_unchanged = all(digest(path) == starting_hashes[str(path)] for path in immutable_paths)
    if not immutable_unchanged:
        raise ValueError('Game static source changed during extraction; output must not be used.')
    inventory_checks = []
    for path in source_paths:
        inventory = args.out / 'inventory' / f'{path.name}.inventory.json'
        if inventory.is_file():
            old = json.loads(inventory.read_text(encoding='utf-8'))
            inventory_checks.append({'source_file': path.name, 'matches_initial_inventory_hash':
                                     old['sha256'] == starting_hashes[str(path)]})
    scripts = [PROJECT / 'scripts' / name for name in ('extract_deskrawl.py', 'deskrawl_managed_refs.py', 'deskrawl_numeric.py')]
    dummy_files = sorted(args.dummy.glob('*.dll'))
    write_json(args.out / 'tool-provenance.json', {
        'python_version': sys.version.split()[0], 'python_executable': '${PYTHON}',
        'tools': {'UnityPy': {'version': UnityPy.__version__, 'source': 'https://github.com/K0lb3/UnityPy'},
                  'TypeTreeGeneratorAPI': {'version': '0.0.10', 'source': 'https://github.com/UnityPy-Org/TypeTreeGeneratorAPI'},
                  'Cpp2IL': cpp2il_provenance},
        'scripts': [{'path': source_label(path), 'sha256': digest(path)} for path in scripts],
        'dummy_dlls': [{'name': path.name, 'sha256': digest(path)} for path in dummy_files],
        'cpp2il_commands': [
            ['--game-path', '${GAME_DIR}', '--exe-name', 'Deskrawl', '--output-as', 'dummydll', '--output-to', source_label(args.dummy)],
            ['--game-path', '${GAME_DIR}', '--exe-name', 'Deskrawl', '--output-as', 'diffable-cs', '--output-to', source_label(args.headers.parent)],
            ['--game-path', '${GAME_DIR}', '--exe-name', 'Deskrawl', '--use-processor', 'attributeinjector', '--output-as', 'dll_default', '--output-to', source_label(address_dll.parent)]],
        'source_hashes_checked_before_after': immutable_unchanged,
        'initial_inventory_hash_checks': inventory_checks,
        'game_static_files_open_mode': 'read-only', 'game_or_native_code_executed': False,
        'save_and_account_data_accessed': False, 'art_or_audio_exported': False})
    game_manager = next((r for r in records if r['class_name'] == 'GameManager'), None)
    binding = next((ref for ref in game_manager['references'] if ref['field'] == '$.Config'), None) if game_manager else None
    summary = {'build_id': build_match.group(1), 'unity_version': unity_version,
               'extractor': 'scripts/extract_deskrawl.py', 'unitypy_version': UnityPy.__version__,
               'source_files': provenance, 'successfully_parsed_objects': len(records),
               'parsed_classes': dict(by_class), 'localization_row_counts': localization_counts,
               'class_coverage': {name: {'selected': count, 'parsed': by_class[name], 'failed': count-by_class[name]}
                                  for name, count in attempted_classes.items()},
               'source_object_count': len(all_objects), 'reference_coverage': dict(reference_coverage),
               'extraction_scope': {'selected_monobehaviour_objects': sum(attempted_classes.values()),
                                    'all_assembly_csharp_monobehaviour_objects': sum(all_mb_classes.values()),
                                    'omitted_classes': {k: v-attempted_classes[k] for k, v in all_mb_classes.items() if v > attempted_classes[k]},
                                    'parsed_kinds': dict(Counter(r['kind'] for r in records)),
                                    'selection_rule': 'Gameplay *Data/*Config, EquipmentEffect_/TalentEffect_/LifeSkillEffect_ and listed static components; media/config exclusions explicit in extractor.'},
               'scene_game_config_binding': binding,
               'immutable_sources_unchanged_during_run': immutable_unchanged,
               'steam_build_identity': {'source': 'steam://appmanifest_4623570.acf', 'appid': '4623570', 'buildid': build_match.group(1)},
               'managed_reference_schema_count': len(managed_state['schemas']),
               'numeric_decoding': {'status': 'verified_local_native_methods', 'counts': dict(numeric_counts),
                                    'derivation_errors': len(numeric_errors)},
               'errors': len(errors), 'duplicate_class_name_groups': sum(count > 1 for count in duplicate_names.values()),
               'raw_definitions_not_player_items': True,
               'combat_method_implementation_extracted': False,
               'native_method_evidence_scope': 'Six ACTk numerical conversion methods only.',
               'missing_evidence': ['Nonserialized static field values and combat method logic are outside this serialized-object extraction.',
                                    'Runtime combat formulas and true player item rolls are outside this extraction.']}
    write_json(args.out / 'manifest.json', summary)
    print(json.dumps(summary, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
