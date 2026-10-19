# SPDX-License-Identifier: CC0-1.0
# Neverwinter Nights: Enhanced Edition binary model (MDL), as written by the
# game's own compiler (nwmain-linux compilemodel, build 89.8193.37-17).
# See spec/binary.md for the rules this encodes and their evidence.
#
# Written in a plain YAML style (one flow mapping per field) so the suite's
# standard-library checker (ksy/check_ksy.py) can read it. Compiled with
# kaitai-struct-compiler 0.10 and 0.11 (style warnings only); see README.md
# for how it is checked.
meta:
  id: nwn_mdl
  title: Neverwinter Nights Enhanced Edition binary model
  file-extension: mdl
  license: CC0-1.0
  endian: le
doc: "A binary model: a 12-byte file header, the model data (offsets in it are relative to file offset 12) and the raw data (vertex streams; offsets relative to 12 + raw_offset). Offsets are u4; 0 is null for model data, 0xffffffff for raw data. All positions below are absolute, computed from those bases."
seq:
  - {id: file_header, type: file_header}
instances:
  model: {pos: 12, type: model_header}
types:
  file_header:
    seq:
      - {id: binary_marker, contents: [0, 0, 0, 0], doc: "an ASCII model starts with text instead"}
      - {id: raw_offset, type: u4, doc: "size of the model data; raw data starts at 12 + raw_offset"}
      - {id: raw_size, type: u4}
  array_def:
    seq:
      - {id: offset, type: u4, doc: "model data offset; may be garbage when count is 0"}
      - {id: count, type: u4}
      - {id: alloc, type: u4, doc: "allocated size; ignore"}
  vec2:
    seq:
      - {id: x, type: f4}
      - {id: y, type: f4}
  vec3:
    seq:
      - {id: x, type: f4}
      - {id: y, type: f4}
      - {id: z, type: f4}
  quat:
    seq:
      - {id: w, type: f4}
      - {id: x, type: f4}
      - {id: y, type: f4}
      - {id: z, type: f4}
  rgba:
    seq:
      - {id: r, type: u1}
      - {id: g, type: u1}
      - {id: b, type: u1}
      - {id: a, type: u1}
  geometry_header:
    doc: "112 bytes, at the start of the model header and of every animation header (MDL-BIN-010)."
    seq:
      - {id: function_pointers, type: u4, repeat: expr, repeat-expr: 2, doc: "runtime values in EE output; ignore"}
      - {id: name, type: str, size: 64, terminator: 0, encoding: ISO-8859-1}
      - {id: root_node_offset, type: u4}
      - {id: node_count, type: u4, doc: "MDL-NODE-030"}
      - {id: runtime_array1, type: array_def}
      - {id: runtime_array2, type: array_def}
      - {id: ref_count, type: u4}
      - {id: geometry_type, type: u1, doc: "2 model, 5 animation"}
      - {id: padding, size: 3}
    instances:
      root_node: {pos: "12 + root_node_offset", type: node, if: "root_node_offset != 0"}
  model_header:
    doc: "232 bytes at file offset 12 (MDL-BIN-011)."
    seq:
      - {id: geometry, type: geometry_header}
      - {id: unknown, size: 2}
      - {id: classification, type: u1, doc: "tables/classification.yaml"}
      - {id: fog, type: u1, doc: "1 unless ignorefog is set"}
      - {id: child_model_count, type: u4}
      - {id: animations, type: array_def}
      - {id: supermodel_pointer, type: u4, doc: "runtime; 0 in files"}
      - {id: bmin, type: vec3}
      - {id: bmax, type: vec3}
      - {id: radius, type: f4}
      - {id: animation_scale, type: f4}
      - {id: supermodel_name, type: str, size: 64, terminator: 0, encoding: ISO-8859-1}
    instances:
      animation_list: {pos: "12 + animations.offset", type: animation_ref, repeat: expr, repeat-expr: animations.count}
  animation_ref:
    seq:
      - {id: offset, type: u4}
    instances:
      body: {pos: "12 + offset", type: animation_header}
  animation_header:
    doc: "196 bytes (MDL-BIN-070)."
    seq:
      - {id: geometry, type: geometry_header}
      - {id: length, type: f4}
      - {id: transtime, type: f4}
      - {id: animroot, type: str, size: 64, terminator: 0, encoding: ISO-8859-1}
      - {id: events, type: array_def}
    instances:
      event_list: {pos: "12 + events.offset", type: event, repeat: expr, repeat-expr: events.count}
  event:
    seq:
      - {id: time, type: f4}
      - {id: name, type: str, size: 32, terminator: 0, encoding: ISO-8859-1}
  node_ref:
    seq:
      - {id: offset, type: u4}
    instances:
      node: {pos: "12 + offset", type: node}
  node:
    doc: "112-byte header, then the sub-headers its flags name, in bit order (MDL-BIN-020)."
    seq:
      - {id: function_pointers, type: u4, repeat: expr, repeat-expr: 6, doc: "runtime values in EE output; ignore (MDL-BIN-030)"}
      - {id: inherit_color, type: u4}
      - {id: part_number, type: s4, doc: "MDL-NODE-010"}
      - {id: name, type: str, size: 32, terminator: 0, encoding: ISO-8859-1}
      - {id: geometry_pointer, type: u4, doc: "runtime; ignore"}
      - {id: parent_pointer, type: u4, doc: "runtime; ignore; rebuild parents from children"}
      - {id: children, type: array_def}
      - {id: controller_keys, type: array_def}
      - {id: controller_data, type: array_def}
      - {id: flags, type: u4, doc: "tables/node_flags.yaml"}
      - {id: light, type: light_header, if: "(flags & 0x2) != 0"}
      - {id: emitter, type: emitter_header, if: "(flags & 0x4) != 0"}
      - {id: reference, type: reference_header, if: "(flags & 0x10) != 0"}
      - {id: mesh, type: mesh_header, if: "(flags & 0x20) != 0"}
      - {id: skin, type: skin_header, if: "(flags & 0x40) != 0"}
      - {id: anim, type: anim_header, if: "(flags & 0x80) != 0"}
      - {id: dangly, type: dangly_header, if: "(flags & 0x100) != 0"}
      - {id: aabb, type: aabb_header, if: "(flags & 0x200) != 0"}
    instances:
      child_list: {pos: "12 + children.offset", type: node_ref, repeat: expr, repeat-expr: children.count}
      controller_list: {pos: "12 + controller_keys.offset", type: controller_key, repeat: expr, repeat-expr: controller_keys.count}
      controller_floats: {pos: "12 + controller_data.offset", type: f4, repeat: expr, repeat-expr: controller_data.count}
  controller_key:
    doc: "12 bytes (MDL-CTRL-001). Times are controller_floats[time_index .. +rows]; values start at data_index, rows x stride floats, stride = value_columns (x3 when bezier)."
    seq:
      - {id: type, type: u4, doc: "controller id: tables/controllers.yaml, by node class"}
      - {id: rows, type: u2}
      - {id: time_index, type: u2}
      - {id: data_index, type: u2}
      - {id: column_byte, type: u1}
      - {id: padding, type: u1, doc: "uninitialised"}
    instances:
      is_bezier: {value: "(column_byte & 0x10) != 0"}
      value_columns: {value: "column_byte & 0xf"}
  light_header:
    doc: "92 bytes (MDL-BIN-040)."
    seq:
      - {id: flare_radius, type: f4}
      - {id: unknown_array, type: array_def}
      - {id: flare_sizes, type: array_def}
      - {id: flare_positions, type: array_def}
      - {id: flare_color_shifts, type: array_def}
      - {id: flare_textures, type: array_def}
      - {id: light_priority, type: u4}
      - {id: ambient_only, type: u4}
      - {id: dynamic_type, type: u4}
      - {id: affect_dynamic, type: u4}
      - {id: shadow, type: u4}
      - {id: generate_flare, type: u4}
      - {id: fading_light, type: u4}
    instances:
      flare_size_list: {pos: "12 + flare_sizes.offset", type: f4, repeat: expr, repeat-expr: flare_sizes.count}
      flare_position_list: {pos: "12 + flare_positions.offset", type: f4, repeat: expr, repeat-expr: flare_positions.count}
      flare_color_shift_list: {pos: "12 + flare_color_shifts.offset", type: vec3, repeat: expr, repeat-expr: flare_color_shifts.count}
      flare_texture_list: {pos: "12 + flare_textures.offset", type: string_ref, repeat: expr, repeat-expr: flare_textures.count}
  string_ref:
    seq:
      - {id: offset, type: u4}
    instances:
      value: {pos: "12 + offset", type: strz, encoding: ISO-8859-1}
  emitter_header:
    doc: "216 bytes (MDL-BIN-041)."
    seq:
      - {id: deadspace, type: f4}
      - {id: blast_radius, type: f4}
      - {id: blast_length, type: f4}
      - {id: x_grid, type: u4, doc: "uninitialised when the ASCII has no xgrid (MDL-BIN-052)"}
      - {id: y_grid, type: u4}
      - {id: spawn_type, type: u4}
      - {id: update, type: str, size: 32, terminator: 0, encoding: ISO-8859-1}
      - {id: render, type: str, size: 32, terminator: 0, encoding: ISO-8859-1}
      - {id: blend, type: str, size: 32, terminator: 0, encoding: ISO-8859-1}
      - {id: texture, type: str, size: 64, terminator: 0, encoding: ISO-8859-1}
      - {id: chunk_name, type: str, size: 16, terminator: 0, encoding: ISO-8859-1}
      - {id: two_sided_tex, type: u4}
      - {id: loop, type: u4}
      - {id: render_order, type: u2}
      - {id: padding, type: u2}
      - {id: flags, type: u4, doc: "tables/keywords.yaml emitter flag bits"}
  reference_header:
    doc: "68 bytes (MDL-BIN-042)."
    seq:
      - {id: ref_model, type: str, size: 64, terminator: 0, encoding: ISO-8859-1}
      - {id: reattachable, type: u4}
  mesh_header:
    doc: "512 bytes (MDL-BIN-043)."
    seq:
      - {id: function_pointers, type: u4, repeat: expr, repeat-expr: 2}
      - {id: faces, type: array_def}
      - {id: bmin, type: vec3}
      - {id: bmax, type: vec3}
      - {id: radius, type: f4}
      - {id: average, type: vec3}
      - {id: diffuse, type: vec3}
      - {id: ambient, type: vec3}
      - {id: specular, type: vec3}
      - {id: shininess, type: f4}
      - {id: shadow, type: u4}
      - {id: beaming, type: u4}
      - {id: render, type: u4}
      - {id: transparency_hint, type: u4}
      - {id: render_hint, type: u4, doc: "tables/render_hints.yaml"}
      - {id: texture0, type: str, size: 64, terminator: 0, encoding: ISO-8859-1}
      - {id: texture1, type: str, size: 64, terminator: 0, encoding: ISO-8859-1}
      - {id: texture2, type: str, size: 64, terminator: 0, encoding: ISO-8859-1}
      - {id: texture3, type: str, size: 64, terminator: 0, encoding: ISO-8859-1, doc: "the materialname"}
      - {id: tile_fade, type: u4}
      - {id: vertex_indices, type: array_def}
      - {id: leftover_faces, type: array_def}
      - {id: index_list_counts, type: array_def}
      - {id: index_list_offsets, type: array_def}
      - {id: unknown_offset, type: u4}
      - {id: unknown_count, type: u4}
      - {id: triangle_mode, type: u1}
      - {id: padding1, size: 3}
      - {id: temp_mesh, type: u4}
      - {id: vertex_offset, type: u4}
      - {id: vertex_count, type: u2}
      - {id: texture_count, type: u2}
      - {id: uv_offsets, type: u4, repeat: expr, repeat-expr: 4}
      - {id: normal_offset, type: u4}
      - {id: color_offset, type: u4}
      - {id: texanim_offsets, type: u4, repeat: expr, repeat-expr: 3}
      - {id: tangent_offset, type: u4, doc: "texture animation slot 3"}
      - {id: texanim4_offset, type: u4}
      - {id: handedness_offset, type: u4, doc: "texture animation slot 5"}
      - {id: lightmapped, type: u1, doc: "uninitialised in EE output (MDL-BIN-051)"}
      - {id: rotate_texture, type: u1}
      - {id: padding2, type: u2}
      - {id: normal_sum, type: f4}
      - {id: unknown3, type: u4}
    instances:
      face_list: {pos: "12 + faces.offset", type: face, repeat: expr, repeat-expr: faces.count}
      positions: {pos: "12 + _root.file_header.raw_offset + vertex_offset", type: vec3, repeat: expr, repeat-expr: vertex_count, if: "vertex_offset != 0xffffffff"}
      uv0: {pos: "12 + _root.file_header.raw_offset + uv_offsets[0]", type: vec2, repeat: expr, repeat-expr: vertex_count, if: "uv_offsets[0] != 0xffffffff"}
      uv1: {pos: "12 + _root.file_header.raw_offset + uv_offsets[1]", type: vec2, repeat: expr, repeat-expr: vertex_count, if: "uv_offsets[1] != 0xffffffff"}
      normals: {pos: "12 + _root.file_header.raw_offset + normal_offset", type: vec3, repeat: expr, repeat-expr: vertex_count, if: "normal_offset != 0xffffffff"}
      colors: {pos: "12 + _root.file_header.raw_offset + color_offset", type: rgba, repeat: expr, repeat-expr: vertex_count, if: "color_offset != 0xffffffff"}
      tangents: {pos: "12 + _root.file_header.raw_offset + tangent_offset", type: vec3, repeat: expr, repeat-expr: vertex_count, if: "tangent_offset != 0xffffffff"}
      handedness: {pos: "12 + _root.file_header.raw_offset + handedness_offset", type: f4, repeat: expr, repeat-expr: vertex_count, if: "handedness_offset != 0xffffffff"}
      index_list_count0: {pos: "12 + index_list_counts.offset", type: u4, if: "index_list_counts.count > 0"}
      index_list_offset0: {pos: "12 + index_list_offsets.offset", type: u4, if: "index_list_offsets.count > 0"}
      index_list0: {pos: "12 + _root.file_header.raw_offset + index_list_offset0", type: u2, repeat: expr, repeat-expr: index_list_count0, if: "index_list_counts.count > 0 and index_list_offsets.count > 0"}
  face:
    doc: "32 bytes (MDL-BIN-044)."
    seq:
      - {id: normal, type: vec3}
      - {id: distance, type: f4}
      - {id: material, type: u4}
      - {id: adjacent, type: s2, repeat: expr, repeat-expr: 3}
      - {id: vertices, type: u2, repeat: expr, repeat-expr: 3}
  skin_header:
    doc: "192 bytes as the EE compiler writes it today; older files differ (MDL-BIN-061). Vertex streams follow the mesh's vertex_count."
    seq:
      - {id: weights_temp, type: array_def}
      - {id: weights_offset, type: u4, doc: "raw data, 4 f4 per vertex"}
      - {id: bone_refs_offset, type: u4, doc: "raw data, 4 s2 per vertex"}
      - {id: bone_map_offset, type: u4, doc: "model data, s2 per tree position"}
      - {id: bone_map_count, type: u4}
      - {id: qbone_ref_inv, type: array_def}
      - {id: tbone_ref_inv, type: array_def}
      - {id: bone_constant_indices, type: array_def}
      - {id: bone_nodes, type: s2, repeat: expr, repeat-expr: 64}
    instances:
      bone_map: {pos: "12 + bone_map_offset", type: s2, repeat: expr, repeat-expr: bone_map_count}
      qbone_list: {pos: "12 + qbone_ref_inv.offset", type: quat, repeat: expr, repeat-expr: qbone_ref_inv.count}
      tbone_list: {pos: "12 + tbone_ref_inv.offset", type: vec3, repeat: expr, repeat-expr: tbone_ref_inv.count}
  anim_header:
    doc: "56 bytes (MDL-BIN-045). Vertex sets are stored vertex-major: index = vertex * sets + set."
    seq:
      - {id: sample_period, type: f4}
      - {id: anim_verts_temp, type: array_def}
      - {id: anim_tverts_temp, type: array_def}
      - {id: anim_normals_temp, type: array_def}
      - {id: vertex_sets_offset, type: u4, doc: "model data"}
      - {id: texture_sets_offset, type: u4, doc: "model data"}
      - {id: vertex_set_count, type: u4}
      - {id: texture_set_count, type: u4}
    instances:
      vertex_sets: {pos: "12 + vertex_sets_offset", type: vec3, repeat: expr, repeat-expr: "vertex_set_count * _parent.mesh.vertex_count", if: "vertex_set_count > 0"}
      texture_sets: {pos: "12 + texture_sets_offset", type: vec2, repeat: expr, repeat-expr: "texture_set_count * _parent.mesh.vertex_count", if: "texture_set_count > 0"}
  dangly_header:
    doc: "24 bytes (MDL-BIN-046)."
    seq:
      - {id: constraints, type: array_def}
      - {id: displacement, type: f4}
      - {id: tightness, type: f4}
      - {id: period, type: f4}
    instances:
      constraint_list: {pos: "12 + constraints.offset", type: f4, repeat: expr, repeat-expr: constraints.count}
  aabb_header:
    doc: "4 bytes (MDL-BIN-047)."
    seq:
      - {id: root_offset, type: u4}
    instances:
      root: {pos: "12 + root_offset", type: aabb_entry, if: "root_offset != 0"}
  aabb_entry:
    doc: "40 bytes, preorder."
    seq:
      - {id: bmin, type: vec3}
      - {id: bmax, type: vec3}
      - {id: left_offset, type: u4}
      - {id: right_offset, type: u4}
      - {id: face, type: s4, doc: "-1 on inner nodes"}
      - {id: plane, type: u4, doc: "most significant axis of the split (MDL-MESH-052); 0 on leaves"}
    instances:
      left: {pos: "12 + left_offset", type: aabb_entry, if: "left_offset != 0"}
      right: {pos: "12 + right_offset", type: aabb_entry, if: "right_offset != 0"}
