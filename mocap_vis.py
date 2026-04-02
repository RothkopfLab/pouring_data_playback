import numpy as np
import pybullet as p
import pybullet_data
import h5py
import pandas as pd
import scipy.signal as sp
from scipy.spatial.transform import Rotation
from bisect import bisect_left
import json
import os

def get_closest_index(_list, myNumber):
    pos = bisect_left(_list, myNumber)
    if pos == 0:
        return 0
    if pos == len(_list):
        return len(_list) - 1
    before = _list[pos - 1]
    after = _list[pos]
    if after - myNumber < myNumber - before:
        return pos
    else:
        return pos - 1


def parseHDF5(filepath):
    data_dict = {}
    with h5py.File(filepath, 'r') as f:
        for bodyname in f['bodies'].keys():
            data = f['bodies'][bodyname][:]
            bname = bodyname[5:]
            if bname == "Tobii Layout 1":
                continue
            data_dict[bname] = data
        gaze_data = f['gaze_data'][:]
        rostime = f['rostime'][:].flatten()
    return data_dict, gaze_data, rostime

def loadJSON(filename, body_names, prj_path=""):
    mesh_data = {}

    with open(filename, "r") as f:
        data = json.load(f)

    for b_name in body_names:
        if b_name not in data:
            continue

        entry = data[b_name]
        meshfile = os.path.join(prj_path, entry["mesh"])
        color = entry["color"]

        mesh_data[b_name] = [meshfile, color]

    return mesh_data



def createBulletObject(meshfile=None, color=[.8, .8, .8, 1.]):
    visualShapeId = p.createVisualShape(
        shapeType=p.GEOM_MESH,
        fileName=meshfile,
        rgbaColor=color,
        specularColor=[0.15, 0.15, 0.15],
    )
    collisionShapeId = p.createCollisionShape(
        shapeType=p.GEOM_MESH,
        fileName=meshfile,
        flags=p.GEOM_FORCE_CONCAVE_TRIMESH
    )
    bodyid = p.createMultiBody(
        baseMass=1,
        baseCollisionShapeIndex=collisionShapeId,
        baseInertialFramePosition=[0, 0, 0],
        baseVisualShapeIndex=visualShapeId,
        basePosition=[0, 0, 0],
        useMaximalCoordinates=True
    )
    return bodyid


def apply_material(bid, name):
    lname = name.lower()
    rgba = [0.93, 0.93, 0.93, 1.0]
    spec = [0.00, 0.00, 0.00]
    if "table" in lname:
        rgba = [0.70, 0.68, 0.64, 1.0]
    if "bottle" in lname or "elongated" in lname or 'beaker' in lname:
        rgba = [0.95, 0.95, 0.95, 1.0]
    if "martini" in lname or "wine" in lname or "beer" in lname:
        rgba = [0.97, 0.97, 0.97, 1.0]
    p.changeVisualShape(bid, -1, rgbaColor=rgba, specularColor=spec)


def setup_pretty_gui():
    p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0)
    p.configureDebugVisualizer(p.COV_ENABLE_RGB_BUFFER_PREVIEW, 0)
    p.configureDebugVisualizer(p.COV_ENABLE_DEPTH_BUFFER_PREVIEW, 0)
    p.configureDebugVisualizer(p.COV_ENABLE_SEGMENTATION_MARK_PREVIEW, 0)
    p.configureDebugVisualizer(p.COV_ENABLE_SHADOWS, 0)


def _make_ray_cylinder(radius=0.004, length=2.0, rgba=[1.0, 0.0, 0.0, 0.8]):
    """
    Create a cylinder body for gaze ray.
    """
    vs = p.createVisualShape(
        p.GEOM_CYLINDER,
        radius=radius,
        length=length,
        rgbaColor=rgba,
        specularColor=[0.0, 0.0, 0.0]
    )
    return p.createMultiBody(
        baseMass=0,
        baseCollisionShapeIndex=-1,
        baseVisualShapeIndex=vs,
        basePosition=[999, 999, 999],
        baseOrientation=[0, 0, 0, 1]
    )


def _ray_pose(origin, direction, length):
    """
    Return (midpoint, quaternion) to place a Z-axis cylinder so that it starts at
    origin(eye position) and extends along direction(gaze direction) for the given length.
    """
    origin    = np.asarray(origin, dtype=float)
    direction = np.asarray(direction, dtype=float)
    direction = direction / np.linalg.norm(direction)
    midpoint  = origin + direction * (length / 2.0)

    z     = np.array([0.0, 0.0, 1.0])
    axis  = np.cross(z, direction)
    s     = np.linalg.norm(axis)
    c     = np.dot(z, direction)
    if s < 1e-8:
        quat = [0.0, 0.0, 0.0, 1.0] if c > 0 else [1.0, 0.0, 0.0, 0.0]
    else:
        axis  = axis / s
        angle = np.arctan2(s, c)
        half  = angle / 2.0
        quat  = [axis[0]*np.sin(half), axis[1]*np.sin(half),
                 axis[2]*np.sin(half), np.cos(half)]

    return midpoint.tolist(), quat


class BulletMocapWindow:
    def __init__(self, path_mocap, scene_xml,
                 cameraDistance=1.4,
                 cameraYaw=-103,
                 cameraPitch=-25,
                 cameraTargetPosition=[0.85, 0.47, 0.13]
                 ):

        self.mocap_data, gaze_raw, self.rostime = parseHDF5(path_mocap)
        self.rostime_list = list(self.rostime)

        gaze_pd = pd.DataFrame(gaze_raw, columns=np.arange(gaze_raw.shape[1]).astype(str))
        interpolated = gaze_pd.interpolate(method='linear', limit_direction='both').values
        smooth_list = []
        for i in range(interpolated.shape[1]):
            signal = interpolated[:, i]
            fc = 7
            b, a = sp.butter(4, fc, btype='low', fs=120)
            smooth = sp.filtfilt(b, a, signal)
            smooth_list.append(smooth)
        self.gaze_data = np.vstack(smooth_list).T

        mesh_data = loadJSON(scene_xml, list(self.mocap_data.keys()))

        p.connect(p.GUI, options="--width=800 --height=450")
        p.setAdditionalSearchPath(pybullet_data.getDataPath())


        p.resetDebugVisualizerCamera(
            cameraDistance=cameraDistance,
            cameraYaw=cameraYaw,
            cameraPitch=cameraPitch,
            cameraTargetPosition=cameraTargetPosition
        )
   
        setup_pretty_gui()

        planeId = p.loadURDF("plane.urdf")
        p.changeVisualShape(planeId, -1, rgbaColor=[0.1, 0.1, 0.1, 0.7],)

        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 0)
        self.bullet_bodies = {}
        for b_name, (meshfile, color) in mesh_data.items():
            bid = createBulletObject(meshfile, color)
            self.bullet_bodies[b_name] = bid
            apply_material(bid, b_name)
        p.configureDebugVisualizer(p.COV_ENABLE_RENDERING, 1)

        def make_sphere(radius=0.012, rgba=[1.0, 0.0, 0.0, 0.8]):
            vs = p.createVisualShape(p.GEOM_SPHERE, radius=radius, rgbaColor=rgba, specularColor=[0.05, 0.05, 0.05])
            return p.createMultiBody(baseMass=0, baseCollisionShapeIndex=-1, baseVisualShapeIndex=vs, basePosition=[0, 0, 0])

        self.left_eye_id  = make_sphere(radius=0.012, rgba=[1.0, 0.0, 0.0, 0.8])
        self.right_eye_id = make_sphere(radius=0.012, rgba=[1.0, 0.0, 0.0, 0.8])

        self.ray_length   = 2.0
        self.ray_radius   = 0.002
        self.left_ray_id  = _make_ray_cylinder(radius=self.ray_radius, length=self.ray_length, rgba=[1.0, 0.0, 0.0, 0.8])
        self.right_ray_id = _make_ray_cylinder(radius=self.ray_radius, length=self.ray_length, rgba=[1.0, 0.0, 0.0, 0.8])

        self.obj_names_in_bullet = {v: k for k, v in self.bullet_bodies.items()}
        self.obj_names_in_bullet[0] = "Ground"

        self._index = 0
        self._start_index = 0
        self._end_index = len(self.rostime) - 1

    def get_time_range(self):
        return self.rostime[0], self.rostime[-1]

    def set_valid_time_range(self, start, end):
        self._start_index = get_closest_index(self.rostime_list, start)
        self._end_index = get_closest_index(self.rostime_list, end)
        self._index = self._start_index

    def get_index(self, rostime):
        return get_closest_index(self.rostime_list, rostime)

    def ext_command(self, rostime):
        index = self.get_index(rostime)
        self._update_frame(index)

    def _update_frame(self, f):
        for bname, bid in self.bullet_bodies.items():
            pose = self.mocap_data[bname][f]
            position = pose[0:3] / 1000.0
            rotation_deg = pose[3:6]
            rot = Rotation.from_euler('XYZ', rotation_deg, degrees=True).as_quat()
            p.resetBasePositionAndOrientation(bid, position, rot)

        # cam = p.getDebugVisualizerCamera()
        # print("distance:", cam[10])
        # print("yaw:", cam[8])
        # print("pitch:", cam[9])
        # print("target:", cam[11])

        if not np.isnan(self.gaze_data[f]).any():

                
            left_pos = self.gaze_data[f][4:7] / 1000.0
            left_dir = self.gaze_data[f][1:4]
            left_dir = left_dir / np.linalg.norm(left_dir)
            p.resetBasePositionAndOrientation(self.left_eye_id, left_pos.tolist(), [0, 0, 0, 1])

            ray_pos, ray_quat = _ray_pose(left_pos, left_dir, self.ray_length)
            p.resetBasePositionAndOrientation(self.left_ray_id, ray_pos, ray_quat)

            # #for variable length ray.. ends at where it hits the objects.. flickers and slow
            # left_ray_to = left_pos + self.ray_length * left_dir
            # _, _, hit_fraction_l, _, _ = p.rayTest(left_pos, left_ray_to)[0]
            # left_length = self.ray_length * hit_fraction_l if hit_fraction_l < 1.0 else self.ray_length
            # ray_pos, ray_quat = _ray_pose(left_pos, left_dir, left_length)
            # if self.left_ray_id is not None:
            #     p.removeBody(self.left_ray_id)
            # self.left_ray_id  = _make_ray_cylinder(radius=self.ray_radius, length=left_length, rgba=[1.0, 0.0, 0.0, 0.8])
            # p.resetBasePositionAndOrientation(self.left_ray_id, ray_pos, ray_quat)



            right_pos = self.gaze_data[f][11:14] / 1000.0
            right_dir = self.gaze_data[f][8:11]
            right_dir = right_dir / np.linalg.norm(right_dir)
            p.resetBasePositionAndOrientation(self.right_eye_id, right_pos.tolist(), [0, 0, 0, 1])

            ray_pos, ray_quat = _ray_pose(right_pos, right_dir, self.ray_length)
            p.resetBasePositionAndOrientation(self.right_ray_id, ray_pos, ray_quat)


            # right_ray_to = right_pos + self.ray_length * right_dir
            # _, _, hit_fraction_r, _, _ = p.rayTest(right_pos.tolist(), right_ray_to.tolist())[0]
            # right_length = self.ray_length * hit_fraction_r if hit_fraction_r < 1.0 else self.ray_length
            # ray_pos, ray_quat = _ray_pose(right_pos, right_dir, right_length)
            # if self.right_ray_id is not None:
            #     p.removeBody(self.right_ray_id)
            # self.right_ray_id = _make_ray_cylinder(radius=self.ray_radius, length=right_length, rgba=[1.0, 0.0, 0.0, 0.8])
            # p.resetBasePositionAndOrientation(self.right_ray_id, ray_pos, ray_quat)

        else:
            p.resetBasePositionAndOrientation(self.left_ray_id,  [999, 999, 999], [0, 0, 0, 1])
            p.resetBasePositionAndOrientation(self.right_ray_id, [999, 999, 999], [0, 0, 0, 1])

        p.stepSimulation()
