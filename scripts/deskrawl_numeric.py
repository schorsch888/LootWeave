"""Build-25690430 static serialized-number decoding, never executing game code.

Algorithms were read from six small ACTk native methods in GameAssembly.dll.
The extractor verifies the exact method bytes before using these algorithms.
Raw serialized fields remain unchanged; decoded values are separate derivatives.
"""
import struct

METHODS = [
    {'type': 'ObscuredFloat', 'method': 'jwu', 'rva': 0x4547E0, 'offset': 0x452FE0,
     'hex': 'f30f114424088b44240833c2894424080fb64c240ac1e808884c24098844240a8b442408c3',
     'instructions': ['movss [rsp+8],xmm0', 'mov eax,[rsp+8]', 'xor eax,edx',
                      'mov [rsp+8],eax', 'movzx ecx,byte [rsp+10]', 'shr eax,8',
                      'mov [rsp+9],cl', 'mov [rsp+10],al', 'mov eax,[rsp+8]', 'ret']},
    {'type': 'ObscuredFloat', 'method': 'jwv / FloatIntBytesUnion.jwk', 'rva': 0x454810, 'offset': 0x453010,
     'hex': '894c2410894c24080fb644240988442412c1e910884c24118b44241033c2660f6ec0c3',
     'instructions': ['mov [rsp+16],ecx', 'mov [rsp+8],ecx', 'movzx eax,byte [rsp+9]',
                      'mov [rsp+18],al', 'shr ecx,16', 'mov [rsp+17],cl',
                      'mov eax,[rsp+16]', 'xor eax,edx', 'movd xmm0,eax', 'ret']},
    {'type': 'ObscuredInt', 'method': 'jyl', 'rva': 0x455700, 'offset': 0x453F00,
     'hex': '33ca8d040ac3', 'instructions': ['xor ecx,edx', 'lea eax,[rdx+rcx]', 'ret']},
    {'type': 'ObscuredInt', 'method': 'jym', 'rva': 0x455710, 'offset': 0x453F10,
     'hex': '2bca33ca8bc1c3', 'instructions': ['sub ecx,edx', 'xor ecx,edx', 'mov eax,ecx', 'ret']},
    {'type': 'ObscuredLong', 'method': 'jze', 'rva': 0x452330, 'offset': 0x450B30,
     'hex': '4833ca488d040ac3', 'instructions': ['xor rcx,rdx', 'lea rax,[rdx+rcx]', 'ret']},
    {'type': 'ObscuredLong', 'method': 'jzf', 'rva': 0x452340, 'offset': 0x450B40,
     'hex': '482bca4833ca488bc1c3', 'instructions': ['sub rcx,rdx', 'xor rcx,rdx', 'mov rax,rcx', 'ret']},
]


def verify_methods(binary_path):
    with binary_path.open('rb') as stream:
        for method in METHODS:
            expected = bytes.fromhex(method['hex'])
            stream.seek(method['offset'])
            if stream.read(len(expected)) != expected:
                raise ValueError('Build-specific numerical decoder native bytes differ: ' + method['method'])


def swap_middle(value):
    value &= 0xFFFFFFFF
    return (value & 0xFF0000FF) | ((value & 0xFF00) << 8) | ((value & 0xFF0000) >> 8)


def decode(typename, raw):
    hidden, key = raw['hiddenValue'], raw['currentCryptoKey']
    if typename == 'ObscuredFloat':
        legacy = raw['hiddenValueOldByte4']
        if any(legacy.values()):
            raise ValueError('Legacy ObscuredFloat nonzero Byte4 migration not verified')
        bits = (swap_middle(hidden) ^ key) & 0xFFFFFFFF
        value = struct.unpack('<f', struct.pack('<I', bits))[0]
        return value, bits
    width = 64 if typename == 'ObscuredLong' else 32
    mask = (1 << width) - 1
    bits = (((hidden - key) & mask) ^ key) & mask
    value = bits - (1 << width) if bits & (1 << (width - 1)) else bits
    return value, bits


def encode_bits(typename, bits, key):
    if typename == 'ObscuredFloat':
        return swap_middle((bits ^ key) & 0xFFFFFFFF)
    mask = (1 << (64 if typename == 'ObscuredLong' else 32)) - 1
    return ((bits ^ key) + key) & mask


def collect(node, value, managed_schemas, path='$'):
    """Walk data alongside repaired type trees, including concrete ref classes."""
    if node.m_Type in ('ObscuredFloat', 'ObscuredInt', 'ObscuredLong'):
        decoded, bits = decode(node.m_Type, value)
        mask = (1 << (64 if node.m_Type == 'ObscuredLong' else 32)) - 1
        roundtrip = encode_bits(node.m_Type, bits, value['currentCryptoKey']) == (value['hiddenValue'] & mask)
        if not roundtrip:
            raise ValueError('Serialized numeric roundtrip failed at ' + path)
        yield {'field': path, 'serialized_type': node.m_Type, 'value': decoded,
               'decoded_bits_hex': hex(bits), 'raw_hash': value['hash'],
               'roundtrip_matches': True, 'evidence': 'numeric-decoding.json'}
        return
    if isinstance(value, list) and node.m_Children and node.m_Children[0].m_Type == 'Array':
        element = node.m_Children[0].m_Children[1]
        for index, item in enumerate(value):
            yield from collect(element, item, managed_schemas, f'{path}[{index}]')
    elif isinstance(value, dict):
        if node.m_Type == 'ReferencedObject' and value.get('type', {}).get('class'):
            typ = value['type']
            concrete = managed_schemas[(typ['asm'], typ['ns'], typ['class'])]
            yield from collect(concrete, value['data'], managed_schemas, path + '.data')
        for child in node.m_Children:
            if child.m_Type == 'ReferencedObjectData':
                continue
            if child.m_Name in value:
                yield from collect(child, value[child.m_Name], managed_schemas, path + '.' + child.m_Name)
