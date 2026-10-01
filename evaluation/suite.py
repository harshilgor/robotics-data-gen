"""Representative frozen development partitions, reserved before training."""
from copy import deepcopy
from taskgen.bootstrap import broad_bootstrap
from taskgen.structural import mutate_structure
from taskgen.core import fingerprint
from task_advisor.evaluation import BenchmarkRegistry
from task_library.governance import transaction
from task_library.library import structural_signature
from task_advisor.core import capability_outcomes, shared_ontology


def representative_suite(factory, *, seed, name='representative-heldout', version=1):
    old = [m for m in factory.repo.records('benchmark') if m['name'] == name and m['version'] == version]
    if old:
        return old[0]
    seeds = broad_bootstrap()
    by_name = {t['family']:t for t in seeds}
    candidates = []
    # Seen families receive exact unseen parameter realizations.
    for task_name, partition in [('precision_place','precision'),('insert','contact'),('sequential_rearrangement','long_horizon')]:
        candidates.append((deepcopy(by_name[task_name]),partition,False))
    unseen = deepcopy(by_name['pick_place'])
    unseen['family'] = 'heldout_far_pick_place'
    unseen['theta']['target_distance'] = [.20,.24]
    candidates.append((unseen,'unseen_parameters',True))
    layout = mutate_structure(by_name['pick_place'],'layout')
    layout['theta']['layout_offset'] = [.04,.06]
    candidates.append((layout,'unseen_layout',True))
    combo = mutate_structure(by_name['pick_place'],'object')
    combo['objects']['object_additional'] = {'requires':['graspable','insertable']}
    candidates.append((combo,'unseen_object_combination',True))
    composed = mutate_structure(by_name['insert'],'obstacle')
    candidates.append((composed,'heldout_composition',True))
    registry = BenchmarkRegistry(factory.repo,factory.library)
    cases = []
    for task, partition, heldout in candidates:
        record = factory.publish(task,source='bootstrap')
        contract = record['contract']
        if heldout:
            reservation = {'family_id':contract['family_id'],'family_version':contract['family_version'],
                'partition':partition,'task_hash':fingerprint(task),
                'structural_hash':fingerprint(structural_signature(task)),
                'parameter_restrictions':({'layout_offset':task['theta']['layout_offset']} if partition == 'unseen_layout' else {'target_distance':task['theta']['target_distance']} if partition == 'unseen_parameters' else {})}
            with transaction(factory.repo.db):
                factory.repo.put('heldout_family',fingerprint(reservation),reservation)
        generated = registry.generate_cases([(contract['family_id'],contract['family_version'])],
            seed=seed+len(cases),per_family=2,validator=factory.validator.evidence,registry=factory.registry)
        for case in generated:
            case['partition'] = partition
        cases.extend(generated)
    return registry.freeze(name,version,cases,seed=seed,registry=factory.registry)


def transfer_report(factory, before, after, assignment_ids):
    if before['manifest_id'] != after['manifest_id']:
        raise ValueError('transfer needs identical frozen evaluation suite')
    episodes = {e['episode_id']:e for e in factory.store.records('episodes')}
    annotations = {(t['family_id'],t['family_version']):t for t in factory.store.records('tasks')}
    def summarize(run):
        tasks, capabilities = {}, {}
        for eid in run['episode_ids']:
            ep = episodes[eid]
            key = ep['family_id']+'@'+str(ep['family_version'])
            tasks.setdefault(key,[]).append(ep['success'])
            annotation = annotations[(ep['family_id'],ep['family_version'])]
            for cap, outcome in capability_outcomes(ep,annotation,shared_ontology()).items():
                capabilities.setdefault(cap,[]).append(outcome)
        return tasks,capabilities
    pre,post = summarize(before),summarize(after)
    def differences(a,b):
        return {key:{'before_attempts':len(a.get(key,[])), 'after_attempts':len(b.get(key,[])),
            'before':sum(a[key])/len(a[key]) if a.get(key) else None,
            'after':sum(b[key])/len(b[key]) if b.get(key) else None,
            'delta':sum(b[key])/len(b[key])-sum(a[key])/len(a[key]) if a.get(key) and b.get(key) else None}
            for key in sorted(set(a)|set(b))}
    focus = {}
    for aid in assignment_ids:
        ep = factory.repo.get('completion',aid)['episode']
        annotation = annotations[(ep['family_id'],ep['family_version'])]
        for cap in capability_outcomes(ep,annotation,shared_ontology()):
            focus[cap] = focus.get(cap,0)+1
    report = {'before_run':before['run_id'],'after_run':after['run_id'],'manifest_id':before['manifest_id'],
        'assignment_ids':assignment_ids,'training_capability_exposures':focus,
        'task_changes':differences(pre[0],post[0]),'capability_changes':differences(pre[1],post[1]),
        'interpretation':'Observational association only; no causal transfer or skill isolation.'}
    with transaction(factory.repo.db): factory.repo.put('transfer_report',fingerprint(report),report)
    return report
