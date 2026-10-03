"""Restore omitted SerializeReference layouts from local Cpp2IL declarations.

Read-only asset parsing: no game code, memory, saves or asset writes.
Registry v2 layout follows Unity-Technologies/UnityDataTools TextDumper.
Unknown registry versions fail explicitly rather than applying v2 blindly.
"""
from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
import re
from types import SimpleNamespace

HEADERS = Path(__file__).resolve().parents[1] / '.tools/cpp2il/deskrawl-25690430-types/DiffableCs/Assembly-CSharp'
_FIELD = re.compile(r'^\t(?:public|private|protected|internal)\s+(?:readonly\s+)?(?P<type>[\w<>.,\[\] ]+)\s+(?P<name>\w+);\s*//Field offset:', re.M)
_SERIALIZED = re.compile(r'\[SerializeReference\]\s+(?:\[[^\]]+\]\s+)*(?:public|private|protected|internal)\s+(?P<type>[\w<>.,\[\] ]+)\s+(?P<name>\w+)\s*;')


def _node(level, typ, name, size=-1, meta=0, flags=0):
    return {'m_Level': level, 'm_Type': typ, 'm_Name': name,
            'm_ByteSize': size, 'm_Version': 1, 'm_MetaFlag': meta, 'm_TypeFlags': flags}


@lru_cache(maxsize=None)
def _declarations(fullname, headers_root):
    path = Path(headers_root) / (fullname.replace('.', '/') + '.cs')
    if not path.is_file():
        return (), ()
    source = path.read_text(encoding='utf-8-sig')
    fields = tuple(m.group('name') for m in _FIELD.finditer(source))
    managed = tuple((m.group('name'), m.group('type').strip()) for m in _SERIALIZED.finditer(source))
    base = re.search(r'^public class \w+\s*:\s*([\w.]+)', source, re.M)
    if base:
        inherited_fields, inherited_managed = _declarations(base.group(1), headers_root)
        fields = inherited_fields + fields
        managed = inherited_managed + managed
    return fields, managed


def _reference_field(level, name, typename):
    is_list = typename.startswith('List<') or typename.endswith('[]')
    if is_list:
        return [_node(level, 'vector', name),
                _node(level + 1, 'Array', 'Array', flags=1),
                _node(level + 2, 'int', 'size', 4),
                _node(level + 2, 'managedReference', 'data', 8),
                _node(level + 3, 'SInt64', 'rid', 8)]
    return [_node(level, 'managedReference', name, 8),
            _node(level + 1, 'SInt64', 'rid', 8)]


def _registry(level=1):
    return [_node(level, 'ManagedReferencesRegistry', 'references'),
            _node(level + 1, 'int', 'version', 4),
            _node(level + 1, 'vector', 'RefIds'),
            _node(level + 2, 'Array', 'Array', flags=1),
            _node(level + 3, 'int', 'size', 4),
            _node(level + 3, 'ReferencedObject', 'data'),
            _node(level + 4, 'SInt64', 'rid', 8),
            _node(level + 4, 'ReferencedManagedType', 'type'),
            _node(level + 5, 'string', 'class', meta=16384),
            _node(level + 5, 'string', 'ns', meta=16384),
            _node(level + 5, 'string', 'asm', meta=16384),
            _node(level + 4, 'ReferencedObjectData', 'data')]


def repair_managed_nodes(nodes, assembly, fullname, generator=None, headers_root=HEADERS):
    """Return flat node dictionaries with missing managed fields in source order.

    Call before other ordinary-layout repairs and TypeTreeNode.from_list.
    The generator argument is accepted for the main extractor's contract.
    """
    result = copy.deepcopy(nodes)
    # UnityPy.from_list decides defaults from the first dictionary and applies
    # them to all dictionaries; mixed explicit/default keys cause duplicate args.
    for node in result:
        node.setdefault('m_ByteSize', -1)
        node.setdefault('m_Version', 1)
        node.setdefault('m_TypeFlags', 0)
    if assembly.removesuffix('.dll') != 'Assembly-CSharp':
        return result
    cursor = 0
    found_managed = False
    while cursor < len(result):
        parent = result[cursor]
        type_name = fullname if cursor == 0 else parent['m_Type'].lstrip('$')
        ordered, managed = _declarations(type_name, str(headers_root))
        if managed:
            found_managed = True
        for field, typename in managed:
            level = parent['m_Level'] + 1
            end = cursor + 1
            while end < len(result) and result[end]['m_Level'] > parent['m_Level']:
                end += 1
            children = {n['m_Name']: i for i, n in enumerate(result[cursor + 1:end], cursor + 1)
                        if n['m_Level'] == level}
            if field in children:
                continue
            later_fields = ordered[ordered.index(field) + 1:] if field in ordered else ()
            anchor = next((children[n] for n in later_fields if n in children), end)
            result[anchor:anchor] = _reference_field(level, field, typename)
        cursor += 1
    if found_managed and not any(n['m_Type'] == 'ManagedReferencesRegistry' for n in result):
        result.extend(_registry(result[0]['m_Level'] + 1))
    return result


def install_ref_resolver(get_schema):
    """Install a process-local UnityPy resolver for stripped referenced type trees.

    get_schema(assembly, fullname) returns the ordinary repaired TypeTreeNode.
    Its false MonoBehaviour header is removed on a copy for managed class data.
    Ref-type declarations stripped from asset metadata are populated on demand.
    """
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.helpers.TypeTreeNode import TypeTreeNode

    original_read = TypeTreeHelper.read_value
    cache = {}

    def resolve(ref_object, assetfile):
        typ = ref_object['type']
        cls, ns, asm = typ['class'], typ['ns'], typ['asm']
        if not cls:
            return None
        key = (asm, ns, cls)
        if key not in cache:
            fullname = '.'.join(filter(None, (ns, cls)))
            root = get_schema(asm, fullname)
            flat = []
            excluded = {'m_GameObject', 'm_Enabled', 'm_Script', 'm_Name'}
            skip_level = None
            for node in root.traverse():
                if skip_level is not None and node.m_Level > skip_level:
                    continue
                skip_level = None
                if node.m_Level == 1 and node.m_Name in excluded:
                    skip_level = node.m_Level
                    continue
                flat.append(_node(node.m_Level, node.m_Type, node.m_Name,
                                  node.m_ByteSize, node.m_MetaFlag or 0, node.m_TypeFlags or 0))
            cache[key] = TypeTreeNode.from_list(flat)
        if assetfile is not None:
            if assetfile.ref_types is None:
                assetfile.ref_types = []
            match = next((x for x in assetfile.ref_types
                          if (x.m_AssemblyName, x.m_NameSpace, x.m_ClassName) == key), None)
            if match is None:
                assetfile.ref_types.append(SimpleNamespace(m_AssemblyName=asm, m_NameSpace=ns,
                                                           m_ClassName=cls, node=cache[key]))
            else:
                match.node = cache[key]
        return cache[key]

    def read_value(node, reader, config):
        if node.m_Type == 'ManagedReferencesRegistry':
            position = reader.Position
            version = reader.read_int()
            reader.Position = position
            if version != 2:
                raise ValueError(f'Unsupported managed-reference registry version {version}; only verified v2 is implemented')
        return original_read(node, reader, config)

    TypeTreeHelper.read_typetree_boost = None
    TypeTreeHelper.get_ref_type_node = resolve
    TypeTreeHelper.read_value = read_value
    return {'registry_version': 2, 'resolver': 'local_schema_by_class_ns_asm', 'schemas': cache}
