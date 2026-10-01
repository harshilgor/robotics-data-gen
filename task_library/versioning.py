"""Conservative semantic publication classification; identities stay governed."""
from .library import semver, structural_signature
from taskgen.parameters import domain, intersect_domain


def classify(previous, task, dependencies):
    if previous is None:
        return 'initial', '1.0.0'
    prior = previous['task_spec']
    major, minor, patch = semver(previous['version'])
    semantic_keys = ('reward','interfaces','horizon','objects','embodiment','semantic')
    if (structural_signature(task) != previous['structural_signature'] or
        dependencies != previous['dependencies'] or any(task.get(k) != prior.get(k) for k in semantic_keys)):
        return 'major', f'{major+1}.0.0'
    changed = any(task[k] != prior[k] for k in ('theta','phi'))
    if changed:
        for group in ('theta','phi'):
            if set(task[group]) != set(prior[group]):
                return 'major', f'{major+1}.0.0'
            for key, old in prior[group].items():
                new = task[group][key]
                if domain(new)['type'] != domain(old)['type'] or intersect_domain(old,new) != old:
                    return 'major', f'{major+1}.0.0'
        return 'minor', f'{major}.{minor+1}.0'
    return 'patch', f'{major}.{minor}.{patch+1}'
