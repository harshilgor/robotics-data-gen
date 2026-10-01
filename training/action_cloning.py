"""Task-conditioned nearest-neighbor behavior cloning of complete actions.

Uses approved observations and task skill labels; no privileged state, evaluator
labels or scripted target/gripper planner. Phase identification remains supplied
by task predicates. This is a small local baseline, not a general robotics claim.
"""
from collections import defaultdict
import math
from taskgen.core import fingerprint
from task_library.governance import transaction


def features(obs):
    # Translation-invariant measured geometry plus gripper and orientation state.
    return ([obs['object_'+a]-obs['eef_'+a] for a in 'xyz'] +
            [obs['target_'+a]-obs['object_'+a] for a in 'xyz'] +
            [float(obs['held'])*.03, float(obs['gripper_closed'])*.03,
             obs.get('orientation_error',0.)*.03, obs.get('drawer_open_fraction',0.)*.03])


def predict(weights, skill, observations):
    examples = weights['examples'].get(skill)
    if not examples:
        raise ValueError('checkpoint has no learned action coverage for skill: '+skill)
    x = features(observations)
    neighbors = sorted(examples, key=lambda e: sum((a-b)**2 for a,b in zip(x,e['x'])))[:3]
    distances = [math.sqrt(sum((a-b)**2 for a,b in zip(x,e['x']))) for e in neighbors]
    scales = [1/max(d,1e-6) for d in distances]
    total = sum(scales)
    action = {k:sum(e['action'].get(k,0.)*w for e,w in zip(neighbors,scales))/total
              for k in ('delta_x','delta_y','delta_z','delta_angle','drawer_delta')}
    for key,low,high in [('delta_x',-.012,.012),('delta_y',-.012,.012),('delta_z',-.012,.012),('delta_angle',-.12,.12),('drawer_delta',0.,.1)]:
        action[key] = min(high,max(low,action[key]))
    action['close_gripper'] = sum(float(e['action']['close_gripper'])*w for e,w in zip(neighbors,scales))/total >= .5
    return action


class ActionCloningBackend:
    version = 'task-conditioned-action-cloning-1.0'

    def train(self, catalog, dataset_id, *, previous_weights=None):
        manifest = catalog.repo.get('dataset_manifest',dataset_id)
        if any(e['purpose'] == 'evaluation' for e in manifest['episodes']):
            raise ValueError('evaluation data cannot train policy')
        examples = defaultdict(list)
        for skill, rows in (previous_weights or {}).get('examples',{}).items():
            examples[skill].extend(rows)
        used = 0
        for record in catalog.records(dataset_id):
            metadata = record['metadata']
            if metadata['purpose'] not in ('demonstration','training'):
                raise ValueError('unsupported training purpose')
            assignment = catalog.repo.get('assignment', metadata['assignment_id'])
            task = catalog.library.get_family(assignment['family_id'],assignment['family_version'])['task']
            from evaluation.reservations import training_reserved
            if training_reserved(catalog.repo,task,{**assignment['task_parameters'],**assignment['environment_parameters']}):
                raise ValueError('reserved held-out structure cannot train policy')
            for sample in record['trajectory']['samples']:
                obs = sample['observations']
                stage = min(obs['stage'],len(task['task_graph'])-1)
                skill = task['task_graph'][stage]['skill']
                examples[skill].append({'x':features(obs),'action':sample['actions']})
                used += 1
        if not used:
            raise ValueError('training requires accepted action trajectories')
        # Deterministic deduplication, retaining the most recent action for a
        # feature. Bound storage independently per skill without reading eval.
        for skill, rows in examples.items():
            unique = {fingerprint(e['x']):e for e in rows}
            ordered = list(unique.values())
            stride = max(1, math.ceil(len(ordered)/512))
            examples[skill] = ordered[::stride]
        weights = {'policy_type':'action-knn-1.0', 'gain':.008, 'examples':dict(examples),
                   'feature_schema':'relative-approved-state-1.0','dataset_id':dataset_id}
        result = {'backend':self.version,'weights':weights,'dataset_id':dataset_id,
                  'training_metrics':{'new_action_samples':used,'retained_samples':sum(len(v) for v in examples.values()),
                                      'skill_count':len(examples)},
                  'limitations':['task phase supplied by measured predicates','small synthetic imitation baseline']}
        with transaction(catalog.repo.db):
            catalog.repo.put('training_run',fingerprint(result),result)
        return result
