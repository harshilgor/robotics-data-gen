"""Semantic-to-local lowering with pinned source semantics and measured predicates.

Disjoint DAG branches are serialized in deterministic topological order. The
single-gripper backend rejects unordered branches that write the same object.
Transport/insert expand to trusted lift/align reference primitives. These are
compiler transformations, not additional user task goals.
"""
from copy import deepcopy
from .registry import default_registry, validate_task
from taskgen.core import family, fingerprint


def lower(source, registry=None):
    registry = registry or default_registry()
    report = validate_task(source, registry)
    nodes = {n['id']: n for n in source['skill_graph']}
    def ancestors(identity):
        result = set()
        for dep in nodes[identity]['depends_on']:
            result.add(dep)
            result.update(ancestors(dep))
        return result
    for a in nodes.values():
        for b in nodes.values():
            if a['id'] == b['id'] or a['id'] in ancestors(b['id']) or b['id'] in ancestors(a['id']):
                continue
            a_write, b_write = a['roles'].get('object'), b['roles'].get('object')
            if a_write in {b_write,b['roles'].get('target')} or b_write in {a_write,a['roles'].get('target')}:
                raise ValueError('single-gripper lowering rejects unordered writes to the same object')
    robots = [r for r,s in source['roles'].items() if 'manipulator' in s['requires']]
    if len(robots) != 1:
        raise ValueError('local compiler requires one manipulator role')
    objects = {r:deepcopy(s) for r,s in source['roles'].items() if r not in robots}
    if not objects:
        raise ValueError('local compiler requires physical object roles')
    task = family(source['family'], ['reach'], 'near')
    task.update(schema_version='1.3', embodiment='so101', objects=objects,
        interfaces={'observation':'local_cartesian_state_v1','action':'local_cartesian_delta_v1'},
        initial_state={r:['reachable','free'] for r in objects}, task_graph=[], semantic=deepcopy(source))
    target_default = next((r for r,s in objects.items() if 'receptacle' in s['requires']), next(iter(objects)))
    source_nodes = {}
    # Finish each available object stream before switching the single gripper.
    # Lexicographic topological interleaving can drop a previously held object.
    order, completed, previous_object = [], set(), None
    while len(completed) < len(nodes):
        ready = [n for n in source['skill_graph'] if n['id'] not in completed and set(n['depends_on']) <= completed]
        ready.sort(key=lambda n:(n['roles']['object'] != previous_object, list(nodes).index(n['id'])))
        n = ready[0]
        order.append(n['id']); completed.add(n['id']); previous_object = n['roles']['object']
    for identity in order:
        n = nodes[identity]
        obj = n['roles']['object']
        target = n['roles'].get('target', target_default)
        expansion = {'transport':['lift','transport'], 'insert':['align','insert'], 'open':['articulate'], 'place':['release']}.get(n['skill'], [n['skill']])
        for i, skill in enumerate(expansion):
            key = identity if i == len(expansion)-1 else identity+'__'+skill
            task['task_graph'].append({'id':key,'skill':skill,'object':obj,'target':target,
                'depends_on':[] if not task['task_graph'] else [task['task_graph'][-1]['id']]})
        source_nodes[identity] = identity
    last = task['task_graph'][-1]
    goals = {'reach':'near','grasp':'held','transport':'at_target','push':'at_target','insert':'inserted','articulate':'opened','release':'placed','lift':'lifted','rotate':'oriented','align':'aligned','slide':'at_target'}
    task['success'] = {'object':last['object'],'predicate':goals[last['skill']], 'tolerance_parameter':'tolerance'}
    for expression in source['initial']:
        if expression['predicate'] == 'open':
            task['initial_state'][expression['roles'][0]].append('opened')
        elif expression['predicate'] not in ('reachable','near','stable','inside','outside','aligned'):
            raise ValueError('initial predicate has no supported realization: '+expression['predicate'])
    task['provenance'] = {'engine':'semantic-lowering','parents':[], 'source_digest':fingerprint(source)}
    return task


def program(task, registry):
    source = task.get('semantic')
    if source is None:
        return None
    validate_task(source, registry)
    subgoals = {}
    for node in source['skill_graph']:
        definition = registry.get('skill', node['skill'])
        effects = []
        for expression in definition['effects']:
            expr = deepcopy(expression)
            expr['roles'] = [node['roles'][r] for r in expr['roles']]
            effects.append(expr)
        subgoals[node['id']] = effects
    return {'source_digest':fingerprint(source), 'initial':source['initial'], 'goal':source['goal'],
            'constraints':source['constraints'], 'subgoals':subgoals, 'registry_digest':registry.snapshot()['digest']}


def measured_state(environment, task):
    result = {}
    for role, pos in environment['role_positions'].items():
        geometry = environment['layout']['geometry'][role]
        result[role] = {**deepcopy(geometry),'position':deepcopy(pos),
            'speed':environment['role_speeds'].get(role,0.), 'reset_height':environment['reset_height'],
            'yaw':environment['role_orientations'].get(role,0.),
            'grasped':environment.get('held_role') == role,
            'open':environment['role_openings'].get(role,0.) >= .9,
            'reachable':sum(v*v for v in pos)**.5 <= .35}
    for role, spec in task['semantic']['roles'].items():
        if 'manipulator' in spec['requires']:
            result[role] = {'position':deepcopy(environment['eef']), 'radius':.005,'yaw':0.,'speed':0.}
    return result


def evaluate_program(program, state, registry):
    bindings = {r:r for r in state}
    def evaluate(expressions):
        return [registry.evaluate(e,state,bindings) for e in expressions]
    return {'initial':evaluate(program['initial']), 'goal':evaluate(program['goal']),
        'constraints':evaluate(program['constraints']),
        'subgoals':{key:all(evaluate(expressions)) for key,expressions in program['subgoals'].items()}}
