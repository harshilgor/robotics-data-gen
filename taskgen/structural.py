"""Bounded trusted structural mutations; every result re-enters grammar."""
from copy import deepcopy
from .core import validate, fingerprint


def mutate_structure(base, operation):
    child = deepcopy(base)
    if child['schema_version'] == '1.1':
        child['schema_version'] = '1.2'
    if child['schema_version'] not in ('1.2',):
        raise ValueError('structural mutation requires extended execution DSL')
    if operation == 'obstacle':
        child['scene']['template'] = 'tabletop_obstacles'
        child['theta']['obstacle_count'] = {'type':'int','bounds':[1,2]}
        child['theta']['target_distance'] = [.12,.16]
        for node in child['task_graph']:
            if node['skill'] == 'transport':
                node['skill'] = 'obstacle_transport'
    elif operation == 'layout':
        child['theta']['layout_offset'] = [-.04,.04]
        child['theta']['layout_yaw'] = [-.5,.5]
    elif operation == 'approach':
        child['theta']['approach_direction'] = {'type':'categorical','values':['top']}
    elif operation == 'geometry':
        child['theta']['target_width'] = [.05,.09]
        child['theta']['target_depth'] = [.05,.09]
    elif operation == 'object':
        source = child['task_graph'][0]['object']
        new_role = source+'_additional'
        if new_role in child['objects']:
            raise ValueError('bounded object expansion already applied')
        child['objects'][new_role] = deepcopy(child['objects'][source])
        child['initial_state'][new_role] = deepcopy(child['initial_state'][source])
        original = deepcopy(child['task_graph'])
        for node in original:
            if node['object'] != source:
                raise ValueError('object expansion requires single-object plan')
            node['object'] = new_role
            node['id'] += '_additional'
            node['depends_on'] = [child['task_graph'][-1]['id']]
            child['task_graph'].append(node)
        child['success']['object'] = new_role
        child['horizon'] *= 2
        child['scene']['template'] = 'multi_object'
    elif operation == 'spatial':
        child['objects']['barrier'] = {'requires':['collision_object']}
        child['scene']['relations'].append({'relation':'obstructs','roles':['barrier',child['task_graph'][-1]['target']]})
        for node in child['task_graph']:
            if node['skill'] == 'transport': node['skill'] = 'obstacle_transport'
    else:
        raise ValueError('unsupported structural mutation')
    child['revision'] += 1
    child['family'] += '_'+operation
    child['provenance'] = {'engine':'mutation','parents':[fingerprint(base)],'operation':operation}
    report = validate(child)
    if not report.structurally_valid:
        raise ValueError(report.errors)
    return child
