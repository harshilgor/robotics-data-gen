"""Version-pinned Isaac Lab 2.x procedural scene and SO-101 joint integration.

Create only after a caller has launched Isaac Sim via AppLauncher. Resources and
measured physical evidence belong to that deployment. No USD is downloaded and
no synthetic evidence is accepted as real feasibility evidence.
"""
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import math
from hashlib import sha256
from taskgen.core import fingerprint
from simulation.layout import realize

JOINTS = ('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll','gripper')


@dataclass(frozen=True)
class SO101Config:
    isaac_lab_version: str
    usd_path: str
    asset_version: str
    joint_names: tuple
    joint_limits: tuple
    home: tuple
    stiffness: float
    damping: float
    effort_limit: float
    velocity_limit: float
    eef_body: str
    dt: float = .02

    def validate(self):
        if self.isaac_lab_version not in ('2.1','2.2','2.3'):
            raise ValueError('unsupported Isaac Lab API version; explicitly migrate bindings')
        if not self.asset_version or not Path(self.usd_path).is_file() or not self.eef_body:
            raise ValueError('versioned local SO-101 USD and end-effector body required')
        if len(self.joint_names) != 6 or len(set(self.joint_names)) != 6 or len(self.joint_limits) != 6 or len(self.home) != 6:
            raise ValueError('exact six-joint SO-101 mapping required')
        for bounds,home in zip(self.joint_limits,self.home):
            if len(bounds) != 2 or not all(math.isfinite(v) for v in (*bounds,home)) or not bounds[0] <= home <= bounds[1]:
                raise ValueError('joint limits/home mismatch')
        if any(not math.isfinite(v) or v <= 0 for v in (self.stiffness,self.damping,self.effort_limit,self.velocity_limit,self.dt)):
            raise ValueError('positive deployment actuator/clock configuration required')
        return self


class IsaacLabCompiler:
    def __init__(self, robot, *, articulated_assets=None):
        self.robot = robot.validate()
        self.articulated_assets = deepcopy(articulated_assets or {})
        for role,asset in self.articulated_assets.items():
            required = {'usd_path','asset_version','joint_name','joint_limits','closed','open','stiffness','damping','effort_limit','velocity_limit'}
            if set(asset) != required or not asset['asset_version'] or not Path(asset['usd_path']).is_file():
                raise ValueError('complete pinned articulated scene asset required')
            if not asset['joint_name'] or any(not math.isfinite(asset[k]) or asset[k] <= 0 for k in ('stiffness','damping','effort_limit','velocity_limit')):
                raise ValueError('positive articulated actuator configuration required')
            low,high=asset['joint_limits']
            if not all(math.isfinite(v) for v in (low,high,asset['closed'],asset['open'])) or not low <= asset['closed'] < asset['open'] <= high:
                raise ValueError('articulated object joint configuration invalid')

    def compile(self, compiled, parameters, *, seed, num_envs=1):
        if type(num_envs) is not int or num_envs < 1:
            raise ValueError('positive parallel environment count required')
        from task_compiler.bindings import parameter_schema
        from taskgen.parameters import check_values
        task = compiled['task']
        check_values(parameter_schema(task),parameters)
        if task['scene']['template'] == 'drawer' and not self.articulated_assets:
            raise ValueError('articulated drawer requires a separately pinned deployment USD/joint binding')
        unsupported = set(parameters) - {'target_distance','tolerance','object_size','mass','friction','obstacle_count','obstacle_height','target_width','target_depth','layout_offset','layout_yaw'}
        if unsupported:
            raise ValueError('Isaac deployment lacks physical bindings for: '+','.join(sorted(unsupported)))
        layout = realize(task,compiled['objects'],parameters,seed)
        geometry = []
        for role,resource in compiled['objects'].items():
            definition = resource['definition']
            shape = definition['shape']
            if shape == 'prismatic_container' and role not in self.articulated_assets:
                raise ValueError('drawer role lacks deployment USD/joint binding: '+role)
            if shape not in ('box','cylinder','support','container','prismatic_container'):
                raise ValueError('unsupported physical asset shape: '+shape)
            geometry.append({'role':role,'shape':shape,'position':layout['positions'][role],
                'size':parameters['object_size'],'mass':parameters['mass'], 'friction':parameters['friction'],
                'interior_half_extents':layout['geometry'][role]['interior_half_extents'],
                'dynamic':any(n['object']==role for n in task['task_graph'])})
        for role in set(layout['geometry'])-set(compiled['objects']):
            geometry.append({'role':role,'shape':'container','position':layout['positions'][role],
                'size':parameters['object_size'],'mass':parameters['mass'],'friction':parameters['friction'],
                'interior_half_extents':layout['geometry'][role]['interior_half_extents'],'dynamic':False})
        plan = {'schema_version':'isaac-scene-plan-1.0','source_compiled_id':compiled['compiled_id'],
            'robot':{**deepcopy(self.robot.__dict__),'usd_sha256':sha256(Path(self.robot.usd_path).read_bytes()).hexdigest()},'num_envs':num_envs,'seed':seed,'parameters':deepcopy(parameters),
            'geometry':geometry,'articulated_assets':{role:{**asset,'usd_sha256':sha256(Path(asset['usd_path']).read_bytes()).hexdigest()} for role,asset in self.articulated_assets.items()},'obstacles':layout['obstacles'],'scene_spacing':1.,
            'sensors':{'contacts':True,'eef_body':self.robot.eef_body},
            'evidence_status':'requires live simulation validation; synthetic envelope is not transferable'}
        plan['plan_id'] = fingerprint(plan)
        return plan

    def instantiate(self, plan):
        return IsaacSceneRuntime(plan)


class IsaacSceneRuntime:
    """Actual Isaac API calls for parallel bodies, joints, contact sensors and reset.

    Joint actions are deployment policy outputs in radians. Cartesian synthetic
    actions are deliberately not relabeled as joint targets or real IK.
    """
    def __init__(self,plan):
        content = deepcopy(plan); claimed = content.pop('plan_id',None)
        if claimed != fingerprint(content): raise ValueError('Isaac plan digest mismatch')
        if sha256(Path(plan['robot']['usd_path']).read_bytes()).hexdigest() != plan['robot']['usd_sha256']:
            raise ValueError('SO-101 USD changed since compilation')
        for asset in plan['articulated_assets'].values():
            if sha256(Path(asset['usd_path']).read_bytes()).hexdigest() != asset['usd_sha256']:
                raise ValueError('articulated scene USD changed since compilation')
        try:
            import torch
            import isaaclab
            import isaaclab.sim as sim
            from importlib.metadata import version
            installed = getattr(isaaclab,'__version__',None) or version('isaaclab')
            if not str(installed).startswith(plan['robot']['isaac_lab_version']+'.'):
                raise RuntimeError('installed Isaac Lab version differs from compiled API binding')
            from isaaclab.assets import Articulation, ArticulationCfg, RigidObject, RigidObjectCfg
            from isaaclab.actuators import ImplicitActuatorCfg
            from isaaclab.sensors import ContactSensor, ContactSensorCfg
            from isaacsim.core.utils.prims import create_prim
        except ImportError as exc:
            raise RuntimeError('Isaac Lab/Sim and torch are optional; launch AppLauncher in the deployment first') from exc
        self.torch,self.plan,self.bodies,self.sensors,self.robots = torch,deepcopy(plan),[],[],[]
        cfg = plan['robot']
        self.sim = sim.SimulationContext(sim.SimulationCfg(dt=cfg['dt']))
        self.sim.set_camera_view([.7,.7,.7],[0.,0.,0.])
        sim.GroundPlaneCfg().func('/World/Ground',sim.GroundPlaneCfg())
        light = sim.DomeLightCfg(intensity=1500.)
        light.func('/World/Light',light)
        self.initial_poses = []
        for env in range(plan['num_envs']):
            path = '/World/env_'+str(env)
            create_prim(path,'Xform')
            offset = env*plan['scene_spacing']
            robot_cfg = ArticulationCfg(prim_path=path+'/Robot',spawn=sim.UsdFileCfg(usd_path=cfg['usd_path'],activate_contact_sensors=True),
                init_state=ArticulationCfg.InitialStateCfg(pos=(offset,0.,0.),joint_pos=dict(zip(cfg['joint_names'],cfg['home']))),
                actuators={'arm':ImplicitActuatorCfg(joint_names_expr=list(cfg['joint_names']),stiffness=cfg['stiffness'],damping=cfg['damping'],
                    effort_limit_sim=cfg['effort_limit'],velocity_limit_sim=cfg['velocity_limit'])})
            self.robots.append(Articulation(robot_cfg))
            objects = {}
            poses = {}
            for item in plan['geometry']:
                role = item['role']; size = item['size']
                base = [item['position'][0]+offset,*item['position'][1:]]
                material = sim.RigidBodyMaterialCfg(static_friction=item['friction'],dynamic_friction=item['friction'])
                rigid = sim.RigidBodyPropertiesCfg(kinematic_enabled=not item['dynamic'])
                common = {'rigid_props':rigid,'collision_props':sim.CollisionPropertiesCfg(),
                    'mass_props':sim.MassPropertiesCfg(mass=item['mass']), 'physics_material':material, 'activate_contact_sensors':True}
                if item['shape'] == 'prismatic_container':
                    asset = plan['articulated_assets'][role]
                    objects[role] = Articulation(ArticulationCfg(prim_path=path+'/'+role,
                        spawn=sim.UsdFileCfg(usd_path=asset['usd_path'],activate_contact_sensors=True),
                        init_state=ArticulationCfg.InitialStateCfg(pos=tuple(base),joint_pos={asset['joint_name']:asset['closed']}),
                        actuators={'drawer':ImplicitActuatorCfg(joint_names_expr=[asset['joint_name']],stiffness=asset['stiffness'],damping=asset['damping'],effort_limit_sim=asset['effort_limit'],velocity_limit_sim=asset['velocity_limit'])}))
                    continue
                if item['shape'] == 'container':
                    # Five physical walls leave the top accessible.
                    x,y,z = item['interior_half_extents']; wall=.004
                    pieces = [((2*x+2*wall,2*y+2*wall,wall),(0.,0.,-z)),
                        ((wall,2*y+2*wall,2*z),(-x-wall/2,0.,0.)),((wall,2*y+2*wall,2*z),(x+wall/2,0.,0.)),
                        ((2*x,wall,2*z),(0.,-y-wall/2,0.)),((2*x,wall,2*z),(0.,y+wall/2,0.))]
                    for j,(dims,delta) in enumerate(pieces):
                        spawn = sim.CuboidCfg(size=dims,**common)
                        spawn.func(path+'/'+role+'_wall_'+str(j),spawn,translation=tuple(a+b for a,b in zip(base,delta)))
                    continue
                spawn = sim.CylinderCfg(radius=size/2,height=size,**common) if item['shape']=='cylinder' else sim.CuboidCfg(size=(size,size,size),**common)
                objects[role] = RigidObject(RigidObjectCfg(prim_path=path+'/'+role,spawn=spawn,init_state=RigidObjectCfg.InitialStateCfg(pos=tuple(base))))
                poses[role] = base
                self.sensors.append(ContactSensor(ContactSensorCfg(prim_path=path+'/'+role,update_period=0.,history_length=2)))
            for j, obstacle in enumerate(plan['obstacles']):
                spawn = sim.CuboidCfg(size=tuple(2*h for h in obstacle['half_extents']),collision_props=sim.CollisionPropertiesCfg())
                spawn.func(path+'/Obstacle_'+str(j),spawn,translation=tuple([obstacle['position'][0]+offset,*obstacle['position'][1:]]))
            self.bodies.append(objects); self.initial_poses.append(poses)
        self.sim.reset()
        self.joint_ids = [r.find_joints(list(cfg['joint_names']),preserve_order=True)[0] for r in self.robots]
        if any(len(ids) != 6 for ids in self.joint_ids): raise ValueError('USD joint mapping mismatch')
        self.eef_ids = []
        for robot in self.robots:
            ids,_ = robot.find_bodies(cfg['eef_body'])
            if len(ids) != 1: raise ValueError('USD end-effector mapping must be unique')
            self.eef_ids.append(ids[0])
        self.reset()

    def step_cartesian(self, targets, *, gripper_targets, articulation_targets=None):
        """Measured Jacobian DLS translation controller; never asserts feasibility.

        Targets are world xyz positions. Orientation is intentionally not claimed
        controllable by this five-arm-joint embodiment. The returned residual is
        a linearization estimate; callers must inspect subsequent measured pose.
        """
        from .ik import damped_joint_target
        if len(targets) != len(self.robots) or len(gripper_targets) != len(targets):
            raise ValueError('one Cartesian/gripper target per environment required')
        actions,evidence = [],[]
        for env,(robot,target) in enumerate(zip(self.robots,targets)):
            if len(target) != 3 or not all(math.isfinite(v) for v in target):
                raise ValueError('finite xyz Cartesian target required')
            body = self.eef_ids[env]
            current = robot.data.body_pos_w[0,body].detach().cpu().numpy()
            jac = robot.root_physx_view.get_jacobians()
            fixed = robot.is_fixed_base
            index = body-1 if fixed else body
            columns = [j if fixed else j+6 for j in self.joint_ids[env][:5]]
            measured = jac[0,index,:3,columns].detach().cpu().numpy()
            joints = robot.data.joint_pos[0,self.joint_ids[env][:5]].detach().cpu().numpy()
            result = damped_joint_target(joints,measured,[a-b for a,b in zip(target,current)],self.plan['robot']['joint_limits'][:5])
            actions.append(result['joint_target']+[gripper_targets[env]])
            evidence.append(result)
        telemetry = self.step(actions,articulation_targets=articulation_targets)
        telemetry['ik_evidence'] = evidence
        telemetry['eef_positions'] = [r.data.body_pos_w[0,b].detach().cpu().tolist() for r,b in zip(self.robots,self.eef_ids)]
        return telemetry

    def reset(self):
        torch = self.torch
        for env,robot in enumerate(self.robots):
            positions = robot.data.default_joint_pos.clone(); velocities = positions*0
            robot.write_joint_state_to_sim(positions,velocities); robot.reset()
            for role,body in self.bodies[env].items():
                root = body.data.default_root_state.clone()
                body.write_root_state_to_sim(root)
                if role in self.plan['articulated_assets']:
                    body.write_joint_state_to_sim(body.data.default_joint_pos.clone(),body.data.default_joint_vel.clone())
                body.reset()
        for sensor in self.sensors: sensor.reset()

    def step(self,joint_targets, *, articulation_targets=None):
        if len(joint_targets) != len(self.robots): raise ValueError('one joint action per environment required')
        cfg = self.plan['robot']
        for env,(robot,target) in enumerate(zip(self.robots,joint_targets)):
            if len(target) != 6 or any(not math.isfinite(v) or not lo <= v <= hi for v,(lo,hi) in zip(target,cfg['joint_limits'])):
                raise ValueError('joint action outside configured limits')
            robot.set_joint_position_target(self.torch.tensor([target],device=self.sim.device),joint_ids=self.joint_ids[env]); robot.write_data_to_sim()
        for env,objects in enumerate(self.bodies):
            for role,body in objects.items():
                if role in self.plan['articulated_assets']:
                    asset = self.plan['articulated_assets'][role]
                    fraction = (articulation_targets or {}).get((env,role),0.)
                    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
                        raise ValueError('articulation fraction outside declared domain')
                    target = asset['closed']+fraction*(asset['open']-asset['closed'])
                    ids,_=body.find_joints([asset['joint_name']],preserve_order=True)
                    body.set_joint_position_target(self.torch.tensor([[target]],device=self.sim.device),joint_ids=ids)
                body.write_data_to_sim()
        self.sim.step()
        for robot in self.robots:robot.update(cfg['dt'])
        for objects in self.bodies:
            for body in objects.values():body.update(cfg['dt'])
        for sensor in self.sensors:sensor.update(cfg['dt'])
        return {'joint_positions':[r.data.joint_pos.detach().cpu().tolist() for r in self.robots],
            'objects':[{role:{'position':b.data.root_pos_w.detach().cpu().tolist(),'velocity':b.data.root_lin_vel_w.detach().cpu().tolist()} for role,b in objects.items()} for objects in self.bodies],
            'contact_forces':[s.data.net_forces_w.detach().cpu().tolist() for s in self.sensors],
            'evidence_status':'measured telemetry; not yet a governed feasibility report'}
