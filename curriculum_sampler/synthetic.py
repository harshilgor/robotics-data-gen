"""Synthetic fixtures only. No Isaac, SO-101 physics or learning evidence."""
from copy import deepcopy
from taskgen.core import bootstrap_families, fingerprint
from task_advisor.loop import Repository, numeric_instance, CurriculumSampler, AssignmentScheduler
from task_advisor.curriculum import Registry, make_directive
from task_advisor.research import uniform_directive
from task_advisor.worker import AssignmentEnvironments
from task_library import TaskLibrary

NOTICE = "SYNTHETIC SOFTWARE FIXTURE ONLY: no actual simulator, physics validation or learning performance"


def evidence(task, instance=None):
    result = {"family_id":fingerprint(task),"report_id":"synthetic-only-"+fingerprint(instance or task),
        "validator_version":"synthetic-validator-v1","simulator_version":"synthetic-simulator-v1",
        "evidence_label":NOTICE,"checks":dict.fromkeys(("kinematics","collision","physics","reset_stability"),True)}
    if instance is not None: result["instance_id"] = fingerprint(instance)
    else: result["envelope"] = deepcopy({**task["theta"],**task["phi"]})
    return result


def fixture_task(index):
    task = bootstrap_families()[index]
    task["schema_version"] = "1.1"
    task["theta"]["corridor_width"] = {"type":"float","bounds":[.025,.08]}
    task["theta"]["obstacle_count"] = {"type":"int","bounds":[0,3]}
    task["phi"]["surface"] = {"type":"categorical","values":["mat","tray"]}
    task["phi"]["sensor_gain"] = {"type":"float","bounds":[.9,1.1]}
    return task


def contract_for(task):
    artifact = {"synthetic_scene":task["family"],"notice":NOTICE}
    schema = {}
    units = {"target_distance":"m","tolerance":"m","object_size":"m","mass":"kg","friction":"1", "corridor_width":"m","obstacle_count":"count","surface":"1","sensor_gain":"1"}
    for group in ("theta","phi"):
        for key,value in task[group].items():
            spec = {"type":"float","bounds":deepcopy(value)} if isinstance(value,list) else deepcopy(value)
            spec.update(name=key,units=units[key],coordinate_frame="world" if units[key]=="m" else None,
                spatial=units[key]=="m",sampling_role=group,
                application_stage="build" if key in ("object_size","mass","friction","surface") else "step" if key=="sensor_gain" else "reset",
                dependencies=["object_size"] if key=="corridor_width" else [])
            schema[key] = spec
    trajectory_schema = {"schema_id":"synthetic-trajectory-v1",
        "observations":{"position":{"type":"float","bounds":[-1.,1.],"units":"m","coordinate_frame":"world"}},
        "actions":{"joint_target":{"type":"float","bounds":[-1.,1.],"units":"rad","coordinate_frame":"joint"}}}
    c = {"schema_version":"2.0","family_id":fingerprint(task),"family_version":task["revision"],"status":"active",
        "capability_tags":sorted({n["skill"] for n in task["task_graph"]}),"supported_embodiments":["so101"],
        "supported_controller_references":["synthetic-controller@v1"],"parameter_schema":schema,
        "constraints":[{"id":"corridor-clearance-v1","dependencies":["corridor_width","object_size"]}],
        "geometry_checks":[{"id":"synthetic-workspace-v1","dependencies":["target_distance"]}],
        "validation_policy":{"mode":"always","validator_id":"synthetic-physical-v1"},
        "instance_constructor_id":"typed-instance-v1","compiled_artifact_reference":"synthetic-"+fingerprint(task),
        "compiled_artifact_hash":fingerprint(artifact),"execution_compatibility_key":"synthetic-tabletop-v1",
        "robot_configuration":{"robot":"synthetic-so101"},"actuator_configuration":{"mode":"joint_target"},
        "sensor_configuration":{"state":"v1"},"observation_schema_id":task["interfaces"]["observation"],
        "action_schema_id":task["interfaces"]["action"],"success_predicate_version":"v1","reward_version":"v1",
        "compiler_version":"synthetic-compiler-v1","validation_evidence":evidence(task),
        "trajectory_schema":trajectory_schema,"demonstration_quality":{"max_collisions":0,"max_step_seconds":.1}}
    return c, artifact


def setup(store, *, registry=None):
    repo = Repository(store); library = TaskLibrary(repo)
    families = []
    for index in (0,2):
        task = fixture_task(index); name = "synthetic-"+task["family"]
        existing = library.search(family_id=name)
        if existing:
            families.append(library.get_family(fingerprint(task),1)); continue
        c,artifact = contract_for(task)
        library.register(name,"1.0.0",task,
            dependencies=dict.fromkeys(("task_dsl","predicate_library","capability_ontology","object_ontology"),"synthetic-v1"),
            provenance={"source":"human","proposal_id":name,"generator_version":"synthetic-v1","parents":[]},metadata={"notice":NOTICE})
        for state in ("STRUCTURALLY_ACCEPTED","VALIDATING","VALID"):
            library.transition(name,"1.0.0",state,event_id=name+"-"+state,reason=NOTICE)
        context = {"robot":"so101","gripper":"synthetic-gripper","controller":"synthetic-controller@v1",
                   "compiler_version":"synthetic-compiler-v1","validator_version":"synthetic-validator-v1","simulator_version":"synthetic-simulator-v1"}
        families.append(library.publish_version(name,"1.0.0",c,artifact,context=context))
        library.transition(name,"1.0.0","ACTIVE",event_id=name+"-active",reason=NOTICE)
    registry = registry or Registry().register("constructor","typed-instance-v1",numeric_instance).register("constraint","corridor-clearance-v1",lambda p:p["corridor_width"]>=p["object_size"]+.005,dependencies=("corridor_width","object_size")).register("geometry","synthetic-workspace-v1",lambda i:i["theta"]["target_distance"]<=.16,dependencies=("target_distance",)).register("validator","synthetic-physical-v1",evidence)
    sampler = CurriculumSampler(repo,library,registry=registry)
    scheduler = AssignmentScheduler(repo,library)
    advisor_directive = uniform_directive("synthetic-checkpoint-v1",families)
    store.save_snapshot({"snapshot_id":"synthetic-advisor-snapshot","directive":advisor_directive})
    d = make_directive(advisor_directive,library,total=8,seed=42,controller_id="synthetic-controller",controller_version="v1",
        window_id="synthetic-window-v1",starts_at=0.,expires_at=100.,recording_profile={"trajectory":True})
    for r in d["family_region_allocations"]["learn"]: r["parameter_restrictions"] = {"corridor_width":[.07,.08]}
    d.pop("directive_id"); d["directive_id"] = fingerprint(d)
    return repo,library,sampler,scheduler,d


class SyntheticAdapter:
    simulator_version = "synthetic-simulator-v1"
    environment_version = "synthetic-environment-v1"
    software_versions = {"adapter":"synthetic-adapter-v1","controller":"synthetic-controller-v1","sampler":"constraint-stratified-v2"}
    def __init__(self, *, bad_action=False, collisions=False, fail_goal=False):
        self.envs,self.events = {},[]
        self.bad_action,self.collisions,self.fail_goal = bad_action,collisions,fail_goal
        self.checkpoint_digest = None

    def configure(self,env,artifact,key,parameters): self.events.append([env,"build",deepcopy(parameters)])
    def install(self,env,assignment,episode_id):
        self.envs[env] = {"assignment":deepcopy(assignment),"episode_id":episode_id,"step":0,"reset_done":False}
        self.events.append([env,"install",assignment["assignment_id"]])
    def apply_reset(self,env,parameters): self.events.append([env,"apply_reset",deepcopy(parameters)])
    def reset(self,env,initial_state,goal):
        e = self.envs[env]; e["goal"] = deepcopy(goal); e["reset_done"] = True
        self.events.append([env,"reset",deepcopy(goal)])
        a = e["assignment"]
        realized = {"realized_parameters":{**a["task_parameters"],**a["environment_parameters"]},
            "initial_state":{"synthetic_env":env,"position":0.,"requested":deepcopy(initial_state)}}
        e["realized"] = realized
        return deepcopy(realized)
    def capture_initial(self,env): return deepcopy(self.envs[env]["realized"])
    def apply_step(self,env,parameters): self.events.append([env,"apply_step",deepcopy(parameters)])
    def observations(self,env): return {"position":0.}
    def controller_action(self,env,observations,controller):
        self.events.append([env,"controller",deepcopy(controller)])
        return {"joint_target":2. if self.bad_action else 0.}
    def step(self,env,action):
        e = self.envs[env]; e["step"] += 1; step = e["step"]
        frame = {"episode_id":e["episode_id"],"step":step,"sim_time":step*.02,
            "timestamp":"2026-10-01T12:00:00Z","reward":1.,"eef_object_distance":1. if self.fail_goal else 0.,
            "object_target_distance":1. if self.fail_goal else 0.,"height_above_reset":0.,"object_speed":0.,
            "grasp_contact":False,"gripper_closed":False,"target_support":True,"collision":self.collisions,
            "terminated":step>=2,"truncated":False}
        self.events.append([env,"pre_reset_frame",step])
        return {"frame":frame,"next_observations":{"position":0.},"privileged_state":{"synthetic_ground_truth":True}}
    def policy_digest(self,env): return self.checkpoint_digest
    def finalized(self,env): self.events.append([env,"finalized"]); self.envs.pop(env)
    def abandon(self,env): self.events.append([env,"abandon"]); self.envs.pop(env,None)


def smoke(store):
    repo,library,sampler,scheduler,d = setup(store)
    batch = sampler.sample(d,now=0.)
    adapter = SyntheticAdapter(); clock = [1.]
    bridge = AssignmentEnvironments(scheduler,adapter,clock=lambda:clock[0])
    # Independent vector environments are stepped round-robin, not global reseeding.
    for i,a in enumerate(batch["assignments"][:3]): bridge.start("env"+str(i),a["assignment_id"],"attempt-"+str(i),worker_id="synthetic-worker",ttl=30.)
    bridge.step("env0"); clock[0] = 2.
    bridge.interrupt("env0",reason="synthetic_worker_interruption")
    first = batch["assignments"][0]
    bridge.start("env0",first["assignment_id"],"retry-attempt",worker_id="replacement-worker",ttl=30.)
    for _ in range(2):
        for env in list(bridge.sessions): bridge.step(env)
    for i,a in enumerate(batch["assignments"][3:],3):
        bridge.start("env"+str(i%3),a["assignment_id"],"attempt-"+str(i),worker_id="synthetic-worker",ttl=30.)
        bridge.step("env"+str(i%3)); bridge.step("env"+str(i%3))
    feedback = scheduler.feedback(batch["request_id"])
    return {"notice":NOTICE,"batch":batch,"summaries":repo.records("episode_summary"),
        "attempts":[list(r) for r in repo.db.execute("SELECT * FROM execution_attempts ORDER BY identity")],
        "trajectories":repo.records("trajectory"),"initial_states":repo.records("initial_state"),
        "feedback":feedback,"adapter_events":adapter.events}
