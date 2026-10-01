"""Procedural finite geometry for the local surrogate, not robot dynamics."""
from copy import deepcopy
import math
import random


def realize(task, resources, parameters, seed):
    rng = random.Random(seed)
    radius = parameters['object_size']/2
    origin = [.08+rng.uniform(-.005,.005), parameters.get('layout_offset', 0.)+rng.uniform(-.005,.005), radius]
    angle = parameters.get('layout_yaw', 0.)
    target = [origin[0]+parameters['target_distance']*math.cos(angle),
              origin[1]+parameters['target_distance']*math.sin(angle), radius]
    manipulated = {n['object'] for n in task['task_graph']}
    positions, geometry, openings = {}, {}, {}
    for i, role in enumerate(task['objects']):
        definition = resources[role]['definition']
        positions[role] = [origin[0], origin[1]+.035*i, radius] if role in manipulated else deepcopy(target)
        width = parameters.get('target_width', max(parameters['object_size']*2, .06))
        depth = parameters.get('target_depth', max(parameters['object_size']*2, .06))
        geometry[role] = {'radius': radius, 'half_extents': [radius]*3,
            'interior_half_extents': [width/2, width/2, depth/2], 'affordances': definition['affordances']}
        openings[role] = 1. if 'opened' in task['initial_state'].get(role, []) else 0.
    slots = {}
    for target_role in task['objects']:
        assigned = sorted({n['object'] for n in task['task_graph'] if n['target'] == target_role and n['skill'] in ('release','insert')})
        if len(assigned) > 1:
            span = parameters['object_size']*len(assigned)
            if span > geometry[target_role]['interior_half_extents'][1]*2:
                raise ValueError('multi-object target capacity exceeded')
            slots.update({(role+'@'+target_role): (i-(len(assigned)-1)/2)*parameters['object_size'] for i,role in enumerate(assigned)})
    access = {}
    template = task['scene']['template']
    relations = deepcopy(task['scene']['relations'])
    if template == 'drawer':
        drawers = [r for r,g in geometry.items() if 'openable' in g['affordances']]
        for role in manipulated:
            if drawers and role != drawers[0]:
                relations.append({'relation':'inside','roles':[role,drawers[0]]})
    if template == 'container' and task['family'] == 'retrieve_from_container':
        # A scene-owned container, not a target label pretending to be one.
        positions['_container'] = deepcopy(origin)
        geometry['_container'] = {'radius': .04, 'half_extents':[.04,.04,.03],
            'interior_half_extents':[.04,.04,.03], 'affordances':['container','receptacle']}
        relations.append({'relation':'inside','roles':[next(iter(task['initial_state'])), '_container']})
    if template == 'shelf':
        for role in positions:
            positions[role][2] += .04
    # Resolve dependencies before applying placements; reject contradictory or
    # cyclic placements rather than making dictionary order a hidden parameter.
    placements = {}
    barriers = []
    for relation in relations:
        a,b = relation['roles']
        if relation['relation'] == 'obstructs':
            barriers.append(relation)
        elif a in placements and placements[a] != relation:
            raise ValueError('conflicting spatial placements for '+a)
        else:
            placements[a] = relation
    ordered, visiting, visited = [], set(), set()
    def visit(role):
        if role in visiting: raise ValueError('cyclic spatial placement')
        if role in visited or role not in placements: return
        visiting.add(role)
        visit(placements[role]['roles'][1])
        visiting.remove(role); visited.add(role); ordered.append(placements[role])
    for role in placements: visit(role)
    relations = ordered + barriers
    for relation in relations:
        a,b = relation['roles']
        if relation['relation'] == 'inside':
            positions[a] = deepcopy(positions[b])
            interior = geometry[b]['interior_half_extents']
            if any(radius > v for v in interior):
                raise ValueError('object cannot fit enclosing container')
            access[a] = b
        elif relation['relation'] == 'above':
            positions[a] = [positions[b][0], positions[b][1], positions[b][2]+parameters['object_size']]
        elif relation['relation'] == 'beside':
            positions[a] = [positions[b][0], positions[b][1]+parameters['object_size']+.01, positions[b][2]]
        elif relation['relation'] == 'obstructs':
            positions[a] = [(origin[j]+positions[b][j])/2 for j in range(3)]
        else:
            raise ValueError('unsupported layout relation')
    count = parameters.get('obstacle_count', 1 if template == 'tabletop_obstacles' else 0)
    height = parameters.get('obstacle_height', .04)
    obstacles = [{'position':[origin[0]+(target[0]-origin[0])*(i+1)/(count+1),
                  origin[1]+(target[1]-origin[1])*(i+1)/(count+1), height/2],
                  'half_extents':[.012,.02,height/2]} for i in range(count)]
    for relation in relations:
        if relation['relation'] == 'obstructs':
            role = relation['roles'][0]
            obstacles.append({'position':positions[role], 'half_extents':geometry[role]['half_extents']})
    return {'origin':origin, 'positions':positions, 'geometry':geometry, 'openings':openings,
            'access':access, 'slots':slots, 'obstacles':obstacles, 'relations':relations,
            'lighting':random.Random(parameters.get('lighting_seed',seed)).uniform(.6,1.),
            'texture':random.Random(parameters.get('texture_seed',seed)).randint(0,255)}


def box_clearance(position, obstacle, radius):
    delta = [abs(a-b)-h for a,b,h in zip(position, obstacle['position'], obstacle['half_extents'])]
    return math.sqrt(sum(max(0.,d)**2 for d in delta))+min(0.,max(delta))-radius
