"""Read-only Unity asset inventory. Does not load save files or game processes."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from deskrawl_paths import repo_path, source_label, safe_error

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / '.tools' / 'unitypy'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--files', nargs='+', default=['resources.assets'])
    args = parser.parse_args()
    args.game = args.game.resolve()
    args.out = repo_path(args.out)
    import UnityPy
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for filename in args.files:
        if filename not in ('resources.assets', 'sharedassets0.assets', 'globalgamemanagers.assets', 'level0'):
            raise ValueError(f'Not an approved static asset: {filename}')
        path = args.game / 'Deskrawl_Data' / filename
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        env = UnityPy.load(str(path))
        records = []
        for obj in env.objects:
            record = {'file': obj.assets_file.name, 'path_id': obj.path_id,
                      'unity_type': obj.type.name, 'byte_size': obj.byte_size,
                      'has_type_tree': bool(obj.serialized_type.node)}
            if obj.type.name in ('MonoBehaviour', 'MonoScript', 'TextAsset'):
                try:
                    data = obj.read(check_read=False)
                    record['name'] = getattr(data, 'm_Name', None)
                    if obj.type.name == 'MonoScript':
                        record['class_name'] = data.m_ClassName
                        record['namespace'] = data.m_Namespace
                        record['assembly'] = data.m_AssemblyName
                    if obj.type.name == 'MonoBehaviour':
                        record['script_ref'] = {'file_id': data.m_Script.m_FileID,
                                                'path_id': data.m_Script.m_PathID}
                        try:
                            script = data.m_Script.read()
                            record['class_name'] = script.m_ClassName
                            record['namespace'] = script.m_Namespace
                            record['assembly'] = script.m_AssemblyName
                        except Exception as error:
                            record['script_error'] = safe_error(error)
                        try:
                            tree = obj.read_typetree()
                            record['field_names'] = list(tree)
                            record['is_scriptable_object'] = tree.get('m_GameObject', {}).get('m_PathID') == 0
                        except Exception as error:
                            record['parse_error'] = safe_error(error)
                except Exception as error:
                    record['header_error'] = safe_error(error)
            records.append(record)
        result = {'source': source_label(path, game=args.game), 'sha256': digest, 'bytes': path.stat().st_size,
                  'unity_version': next(iter(env.objects)).assets_file.unity_version,
                  'object_count': len(records),
                  'unity_types': dict(Counter(x['unity_type'] for x in records)),
                  'mono_classes': dict(Counter(x.get('class_name', '<unresolved>')
                                              for x in records if x['unity_type'] == 'MonoBehaviour')),
                  'records': records}
        target = args.out / f'{filename}.inventory.json'
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        manifest.append({key: result[key] for key in ('source', 'sha256', 'bytes', 'unity_version',
                                                     'object_count', 'unity_types', 'mono_classes')})
        print(json.dumps(manifest[-1], ensure_ascii=True), flush=True)
    (args.out / 'inventory-summary.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
