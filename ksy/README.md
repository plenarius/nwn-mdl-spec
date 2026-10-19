# Kaitai Struct description

[nwn_mdl.ksy](nwn_mdl.ksy) describes the binary model format (spec/binary.md)
in [Kaitai Struct](https://kaitai.io), from which `kaitai-struct-compiler`
generates a reader for Python, JavaScript, Go, Nim, Java, C#, C++, Ruby, PHP,
Lua and more. It reads; it does not compile ASCII or apply the engine's
conversion rules.

## Using it

```sh
# kaitai-struct-compiler needs Java; releases at github.com/kaitai-io/kaitai_struct_compiler
kaitai-struct-compiler -t python --outdir gen ksy/nwn_mdl.ksy
pip install kaitaistruct          # the runtime, one per language
```

```python
from nwn_mdl import NwnMdl
m = NwnMdl.from_file("model.mdl")
print(m.model.geometry.name, m.model.geometry.node_count)
```

Or load the `.ksy` and a binary model in the [Web IDE](https://ide.kaitai.io)
to browse the tree next to a hex view. An ASCII model fails at once:
`binary_marker` expects the four zero bytes a binary model starts with.

Strings are read as ISO-8859-1: the engine treats names as bytes, and old
files hold bytes above 127 in them.

## How it is checked

`check_ksy.py` decodes files with the description and compares the result
with the runner's own decoder (`runner/mdlview.py`): node tree, flags, part
numbers, controllers, mesh vertices, faces and index lists, light, emitter,
reference, dangly and AABB data, animations and animmesh sets.

```sh
python3 ksy/check_ksy.py                          # the suite's interpreter, every golden
python3 ksy/check_ksy.py --generated gen          # the parser kaitai-struct-compiler generated
python3 ksy/check_ksy.py --generated gen /path/to/*.mdl
```

On 2026-10-19, with kaitai-struct-compiler 0.11 and the kaitaistruct 0.11
Python runtime: every golden decodes identically, and so do all 25,597
binary models of the base game (build 89.8193.37-17). The compiler's only
output is style warnings (it suggests `num_*` names for count fields).
