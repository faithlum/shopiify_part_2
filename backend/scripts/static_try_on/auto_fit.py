import bpy
import mathutils
import bmesh
from mathutils import Vector, kdtree, bvhtree
import math
import time

# Command: blender --background --python auto_fit.py


print("\033[91m----------- START -----------\033[0m")
start_time = time.time()

# -------------------------------
# 0. Delete everything in the scene (Direct removal)
# -------------------------------
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

# -------------------------------
# Define file paths
# -------------------------------
avatar_path = f"../../models/joseph_walking.fbx"
#avatar_path = f"../../models/joseph_blue_shirt_shorts_slow.fbx"
garment_path = f"../../models/garment_skeleton_edited.fbx"
output_path = f"auto_fitted.obj"

# ----------------------------------------------------
# 1. Import the avatar FBX and rename imported objects
# ----------------------------------------------------
bpy.ops.import_scene.fbx(filepath=avatar_path)
for obj in bpy.context.selected_objects:
    if obj.type == 'MESH':
        obj.name = "AvatarMesh"
        avatar_mesh = obj
    elif obj.type == 'ARMATURE':
        obj.name = "AvatarArmature"
        avatar_armature = obj

# -----------------------------------------------------
# 2. Import the Garment FBX and rename imported objects
# -----------------------------------------------------
bpy.ops.import_scene.fbx(filepath=garment_path)
for obj in bpy.context.selected_objects:
    if obj.type == 'MESH':
        obj.name = "GarmentMesh"
        garment_mesh = obj
    elif obj.type == 'ARMATURE':
        obj.name = "GarmentArmature"
        garment_armature = obj
        
# TODO: scale garment to the same scale as avatar

# -------------------------------------------------------------
# 3. Shift the original animation by 10 frames (frame 11 start)
# -------------------------------------------------------------
def shift_animation_data(obj, offset=10):
    if obj.animation_data and obj.animation_data.action:
        action = obj.animation_data.action
        for fcurve in action.fcurves:
            for kp in fcurve.keyframe_points:
                kp.co.x += offset
        start, end = action.frame_range
        action.frame_range = (start + offset, end + offset)

shift_animation_data(avatar_armature, offset=10)

# -------------------------------
# 4. Setup for Garment override
# -------------------------------
# We want to override the avatar’s pose at frame 1 with the garment's pose.
source_ob = avatar_armature      # Avatar armature to modify
target_ob = garment_armature     # Garment armature providing rotations
frame_override = 1               # We'll work on frame 1

# ----------------------------------------------------
# 5. Add / remove "Copy Rotation" constraints to copy
#    only rotation from the garment (preserving scale)
# ----------------------------------------------------
def add_constraints():
    for bone in source_ob.pose.bones:
        sel_bone = source_ob.data.bones[bone.name]
        sel_bone.select = True
        bpy.context.object.data.bones.active = sel_bone
        trans_bone = bpy.context.object.pose.bones[bone.name]
        if trans_bone.constraints.find('Copy Rotation') == -1:
            if target_ob.pose.bones.get(bone.name) is not None:
                bpy.ops.pose.constraint_add(type='COPY_ROTATION')
                trans_bone.constraints["Copy Rotation"].target = target_ob
                trans_bone.constraints["Copy Rotation"].subtarget = bone.name

def del_constraints():
    for bone in bpy.context.selected_pose_bones:
        copyRotConstraints = [c for c in bone.constraints if c.type == 'COPY_ROTATION']
        for c in copyRotConstraints:
            bone.constraints.remove(c)

def apply_garment_keyframe_at_frame(frame):
    scene = bpy.context.scene
    scene.frame_current = frame
    scene.frame_set(frame)
    add_constraints()                     # Copy rotations from garment
    bpy.ops.pose.visual_transform_apply() # Bake the constraint effect
    # bpy.ops.anim.keyframe_insert_menu(type='__ACTIVE__')  # Insert keyframes
    for bone in source_ob.pose.bones:
        # Example: Insert a key for rotation_quaternion
        bone.keyframe_insert(data_path="rotation_quaternion", frame=frame)
        bone.keyframe_insert(data_path="location", frame=frame)
        bone.keyframe_insert(data_path="scale", frame=frame)
    del_constraints()                     # Remove constraints after baking

# ------------------------------------------------
# 6. Apply the Garment override at frame 1
# ------------------------------------------------
ks = bpy.data.scenes["Scene"].keying_sets_all
ks.active = ks['Whole Character']

bpy.context.view_layer.objects.active = source_ob
bpy.ops.object.mode_set(mode='POSE')
apply_garment_keyframe_at_frame(frame_override)

print("✅ Garment override applied at frame 1; original animation starts at frame 11.")

# TODO: reset rest pose with the pose of avatar in the first frame

# ------------------------------------------------------------------
# Helpers to build a KD-tree from the *deformed* (posed) avatar mesh
# ------------------------------------------------------------------
def get_deformed_mesh(obj):
    """
    Returns a copy of the object's mesh in its *posed* state,
    applying Armature and any other modifiers.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    # This mesh is a standalone copy of the final evaluated geometry
    mesh_eval = obj_eval.to_mesh()
    return mesh_eval

def build_kdtree_deformed(obj):
    """
    Builds a KD-Tree and normal array from the object's *posed* vertices.
    """
    deformed_me = get_deformed_mesh(obj)
    kd_size = len(deformed_me.vertices)
    kd_tree = kdtree.KDTree(kd_size)

    normals = [None] * kd_size
    world_mat = obj.matrix_world

    for i, v in enumerate(deformed_me.vertices):
        co_world = world_mat @ v.co
        no_world = (world_mat.to_3x3() @ v.normal).normalized()
        kd_tree.insert(co_world, i)
        normals[i] = no_world

    kd_tree.balance()

    # Clean up the evaluated mesh copy
    obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).to_mesh_clear()
    return kd_tree, normals

def build_bvh_deformed_surface(obj):
    """
    Builds a BVH tree from the object's deformed (posed) surface triangles.
    Returns:
      bvh: BVHTree
      mesh_eval: the evaluated mesh (in case you want to free or reuse it)
    """
    # 1) Get the evaluated (posed) mesh
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh_eval = obj_eval.to_mesh()

    # 2) Gather world-space vertices and polygons
    world_mat = obj.matrix_world
    vertices_world = []
    polygons = []

    for v in mesh_eval.vertices:
        vertices_world.append(world_mat @ v.co)

    for poly in mesh_eval.polygons:
        # Each polygon references loops, which reference vertices
        loop_indices = [mesh_eval.loops[i].vertex_index for i in range(poly.loop_start, poly.loop_start + poly.loop_total)]
        polygons.append(loop_indices)

    # 3) Build the BVHTree from these world-space coords
    bvh = bvhtree.BVHTree.FromPolygons(vertices_world, polygons)

    return bvh, mesh_eval

# --------------------------------------------------------
# 7. Remove interpenetration using the *posed* avatar mesh
# --------------------------------------------------------
def build_kdtree_deformed(obj):
    """
    Builds a KD-tree of the *posed* avatar mesh (world space).
    Returns (kd_tree, normals_list).
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = obj.evaluated_get(depsgraph)
    mesh_eval = obj_eval.to_mesh()

    world_mat = obj.matrix_world
    kd_size = len(mesh_eval.vertices)
    kd = kdtree.KDTree(kd_size)
    
    normals = [None] * kd_size
    for i, v in enumerate(mesh_eval.vertices):
        co_world = world_mat @ v.co
        no_world = (world_mat.to_3x3() @ v.normal).normalized()
        kd.insert(co_world, i)
        normals[i] = no_world

    kd.balance()

    # Clean up the evaluated mesh copy
    obj.evaluated_get(depsgraph).to_mesh_clear()

    return kd, normals

def remove_interpenetration(
    garment_obj, 
    avatar_obj,
    iterations=5,
    lambda_collision=1.0,  # lambda1
    lambda_smooth=0.1,     # lambda2
    kappa=0.01,
):
    """
    Approximate the energy-based approach from the reference:
    E(G,H) = lambda_collision * v(G,H) + lambda_smooth * w(H).

    v(G,H) ~ sum_{i in I} (kappa - f_dot(i)) if f_dot<0
    w(H) ~ shape smoothing using neighbor-based weighting

    Steps:
      1) Collision push if f_dot<0
      2) Weighted smoothing to preserve shape
    """
    # Ensure we're in OBJECT mode
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    # 1) Build KD-tree from the *deformed* avatar mesh
    kd_tree, avatar_normals = build_kdtree_deformed(avatar_obj)

    # 2) Create a BMesh for garment
    garment_me = garment_obj.data
    bm = bmesh.new()
    bm.from_mesh(garment_me)
    bm.verts.ensure_lookup_table()

    # Build adjacency for shape smoothing
    adjacency = [[] for _ in range(len(bm.verts))]
    for e in bm.edges:
        v1_idx = e.verts[0].index
        v2_idx = e.verts[1].index
        adjacency[v1_idx].append(v2_idx)
        adjacency[v2_idx].append(v1_idx)

    # Precompute original positions for shape reference (optional)
    original_positions = [None] * len(bm.verts)
    for v in bm.verts:
        original_positions[v.index] = garment_obj.matrix_world @ v.co

    world_inv = garment_obj.matrix_world.inverted()

    for it in range(iterations):
        # --------------------------------------------------
        # (A) Collision Step: push outward if f_dot < 0
        # --------------------------------------------------
        for v in bm.verts:
            gv_world = garment_obj.matrix_world @ v.co

            co, index, dist = kd_tree.find(gv_world)
            n_h = avatar_normals[index]  # normal at nearest avatar vertex
            diff = gv_world - co
            f_dot = diff.dot(n_h)

            if f_dot < 0:
                # E(G,H) collision term: v(G,H) ~ sum(kappa - f_dot)
                # push outward by: lambda_collision * (kappa - f_dot)
                correction = (kappa - f_dot) * lambda_collision
                new_pos_world = gv_world + (n_h * correction)
                v.co = world_inv @ new_pos_world

        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        # --------------------------------------------------
        # (B) Shape Smooth Step (Weighted by 1/d(i,j))
        # eqn(21) uses adjacency + 1/d factor
        # We'll do a simple gradient-like update
        # --------------------------------------------------
        new_positions = [None] * len(bm.verts)

        for vert in bm.verts:
            idx = vert.index
            v_world = garment_obj.matrix_world @ vert.co

            neighbors_world = []
            weights = []
            for nb_idx in adjacency[idx]:
                nb_vert = bm.verts[nb_idx]
                nb_world = garment_obj.matrix_world @ nb_vert.co

                # Distance for weighting
                dist_ij = (v_world - nb_world).length
                if dist_ij < 1e-8:
                    dist_ij = 1e-8  # avoid division by zero
                w_ij = 1.0 / dist_ij
                neighbors_world.append((nb_world, w_ij))
            
            if not neighbors_world:
                new_positions[idx] = world_inv @ v_world
                continue

            # Weighted average of neighbors
            sum_w = 0.0
            sum_pos = Vector((0,0,0))
            for (nb_pos, w) in neighbors_world:
                sum_w += w
                sum_pos += w * nb_pos

            avg_pos = sum_pos / sum_w if sum_w > 0 else v_world
            # Move vertex slightly toward weighted neighbor average
            # scaled by lambda_smooth
            new_v_world = v_world + lambda_smooth * (avg_pos - v_world)
            new_positions[idx] = world_inv @ new_v_world

        # Apply the smoothing result
        for vert in bm.verts:
            vert.co = new_positions[vert.index]

    # 3) Write back the BMesh
    bm.to_mesh(garment_me)
    bm.free()
    garment_me.update()

    print("Energy-based interpenetration removal done (approx).")




# -------------------------------------------------------
# 8. Run the interpenetration removal on the new T-pose
# -------------------------------------------------------
remove_interpenetration(
    garment_mesh, 
    avatar_mesh,
    iterations=2,
    lambda_collision=1.1,
    lambda_smooth=0.001,
    kappa=0.003
)


# TODO: try subtraction


# 9. Export file
if bpy.context.mode != 'OBJECT':
    bpy.ops.object.mode_set(mode='OBJECT')
bpy.ops.object.select_all(action='SELECT')

bpy.ops.wm.obj_export(
    filepath=output_path,
    check_existing=False
)

run_time = time.time() - start_time
print(f"Scene exported to: {output_path}")
print(f"Script complete in {run_time:.2f} seconds.")
print("\033[92m✅ Script complete.\033[0m")