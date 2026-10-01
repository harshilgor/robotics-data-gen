"""Allowlisted application bindings shared by compiler, reset and validation."""
from taskgen.parameters import domain

# name: (type, units, application stage, bounds/allowed values)
BINDINGS = {
    'target_distance': ('float', 'm', 'reset', (.001, .3)),
    'tolerance': ('float', 'm', 'reset', (.001, .1)),
    'object_size': ('float', 'm', 'build', (.005, .055)),
    'mass': ('float', 'kg', 'build', (.001, 2.)),
    'friction': ('float', '1', 'build', (.05, 2.)),
    'obstacle_count': ('int', 'count', 'reset', (0, 4)),
    'obstacle_height': ('float', 'm', 'reset', (.005, .08)),
    'target_width': ('float', 'm', 'build', (.01, .15)),
    'target_depth': ('float', 'm', 'build', (.01, .15)),
    'layout_offset': ('float', 'm', 'reset', (-.06, .06)),
    'layout_yaw': ('float', 'rad', 'reset', (-1., 1.)),
    'approach_direction': ('categorical', '1', 'reset', ('any', 'top', 'side')),
    'orientation_tolerance': ('float', 'rad', 'reset', (.005, .2)),
    'initial_yaw': ('float', 'rad', 'reset', (-1., 1.)),
    'grip_strength': ('float', 'N', 'build', (.05, 30.)),
    'lighting_seed': ('int', 'seed', 'reset', (0, 1000000)),
    'grasp_disturbance': ('categorical', '1', 'reset', ('drop_once',)),
    'texture_seed': ('int', 'seed', 'reset', (0, 1000000)),
}

def parameter_schema(task):
    schema = {}
    for group in ('theta', 'phi'):
        for name, value in task[group].items():
            if name not in BINDINGS:
                raise ValueError('compiler has no declared application binding for parameter: ' + name)
            kind, units, stage, limits = BINDINGS[name]
            spec = domain(value)
            if spec['type'] != kind:
                raise ValueError('binding type mismatch: ' + name)
            if kind == 'categorical':
                if not set(spec['values']) <= set(limits):
                    raise ValueError('unsupported binding value: ' + name)
            elif not limits[0] <= spec['bounds'][0] <= spec['bounds'][1] <= limits[1]:
                raise ValueError('unsupported modeled binding domain: ' + name)
            schema[name] = {**spec, 'name': name, 'units': units,
                'coordinate_frame': 'world' if units in ('m', 'rad') else None,
                'spatial': units in ('m', 'rad'), 'sampling_role': group,
                'application_stage': stage, 'dependencies': []}
    return schema


def split_parameters(task, values):
    schema = parameter_schema(task)
    return ({k: values[k] for k, s in schema.items() if s['application_stage'] == 'build'},
            {k: values[k] for k, s in schema.items() if s['application_stage'] == 'reset'})
