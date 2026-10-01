"""Restartable adaptive operating loop with immutable phase checkpoints."""
from datetime import datetime, timezone
from taskgen.core import fingerprint
from taskgen.discovery import TaskDiscovery
from task_library.governance import transaction
from task_advisor.evaluation import BenchmarkRegistry
from evaluation.local import LocalProbeRuntime
from evaluation.suite import representative_suite, transfer_report
from training import CheckpointStore, ActionCloningBackend


class AdaptiveLoop:
    def __init__(self,factory, *, job='local-adaptive', seed=42, episodes=28):
        if type(episodes) is not int or episodes < 1:
            raise ValueError('positive episode budget required')
        self.factory,self.job,self.seed,self.episodes = factory,job,seed,episodes
        self.checkpoints = CheckpointStore(factory.repo)
        self.benchmarks = BenchmarkRegistry(factory.repo,factory.library)
        config = {'job':job,'seed':seed,'episodes':episodes,'algorithm':ActionCloningBackend.version}
        with transaction(factory.repo.db): factory.repo.put('adaptive_job',job,config)

    def phase(self, index, name, operation):
        key = fingerprint([self.job,index,name])
        existing = [r for r in self.factory.repo.records('adaptive_phase') if r['phase_id'] == key]
        if existing:
            return existing[0]['result']
        result = operation()
        with transaction(self.factory.repo.db):
            self.factory.repo.put('adaptive_phase',key,{'phase_id':key,'job':self.job,'iteration':index,'phase':name,'result':result})
        return result

    def seed_library(self):
        from taskgen.bootstrap import coverage_bootstrap
        return [self.factory.publish(task,source='bootstrap') for task in coverage_bootstrap()]

    def initialize(self):
        f = self.factory
        self.phase(-1,'seed',self.seed_library)
        suite = self.phase(-1,'suite',lambda:representative_suite(f,seed=self.seed+10000,name=self.job+'-fixed'))
        # Bootstrap complete action demonstrations once. They are never eval.
        batch = self.phase(-1,'demonstration_batch',lambda:f.sample(total=max(28,self.episodes),seed=self.seed,
            policy_version=self.job+'-reference',window=self.job+'-demonstrations',purpose='demonstration'))
        self.phase(-1,'demonstrations',lambda:f.execute(batch,interrupt_first=True))
        stamp = self.phase(-1,'timestamp',lambda:datetime.now(timezone.utc).isoformat())
        dataset = self.phase(-1,'dataset',lambda:f.catalog.create(self.job+'-bootstrap',1,
            [a['assignment_id'] for a in batch['assignments']],created_at=stamp,purposes=('demonstration',),deduplicate=False))
        trained = self.phase(-1,'train',lambda:ActionCloningBackend().train(f.catalog,dataset['dataset_id']))
        policy = self.job+'-policy-0'
        self.phase(-1,'checkpoint',lambda:self.checkpoints.save(policy,trained['weights'],backend=trained['backend'],dataset_id=dataset['dataset_id']))
        return suite,policy

    def advise(self,current,previous):
        snapshot = self.factory.advise(current,previous)
        directive = snapshot['directive']
        allocated = sum(directive['budget'].values())
        if allocated > 0:
            directive['budget'] = {k:v/allocated for k,v in directive['budget'].items()}
            directive['unallocated_budget'] = 0.
            directive.pop('directive_id')
            directive['directive_id'] = fingerprint(directive)
        snapshot['allocation_policy'] = 'Explicit adaptive-loop policy: renormalize active Advisor channels; unsupported regions remain shortfalls.'
        snapshot.pop('snapshot_id')
        snapshot['snapshot_id'] = fingerprint(snapshot)
        return snapshot

    def run(self, iterations, *, stop_after_phase=None):
        from .locking import exclusive
        with exclusive(self.factory.root/'adaptive.lock'):
            return self._run(iterations,stop_after_phase=stop_after_phase)

    def _run(self, iterations, *, stop_after_phase=None):
        if type(iterations) is not int or iterations < 1:
            raise ValueError('positive target iteration count required')
        suite,policy = self.initialize()
        reports = []
        f = self.factory
        for i in range(iterations):
            current = self.job+'-policy-'+str(i)
            next_policy = self.job+'-policy-'+str(i+1)
            before = self.phase(i,'before_evaluation',lambda:self.benchmarks.run(suite['manifest_id'],current,LocalProbeRuntime(f,self.checkpoints)))
            advisor = self.phase(i,'advisor',lambda:self.advise(current,self.job+'-policy-'+str(i-1) if i else None))
            self.phase(i,'advisor_snapshot',lambda:f.store.save_snapshot(advisor))
            discovery = self.phase(i,'discovery',lambda:TaskDiscovery(f).resolve(advisor['directive']))
            batch = self.phase(i,'batch',lambda:f.sample(total=self.episodes,seed=self.seed+i+1,policy_version=current,
                window=self.job+'-iteration-'+str(i),advisor_directive=advisor['directive']))
            executed = self.phase(i,'execution',lambda:f.execute(batch,policies={current:self.checkpoints.load(current)}))
            if stop_after_phase == (i,'execution'):
                return {'job':self.job,'interrupted_after':[i,'execution'],'manifest_id':suite['manifest_id']}
            if not batch['assignments']:
                raise ValueError('Advisor batch has no executable coverage; explicit shortfall: '+str(batch['shortfall']))
            stamp = self.phase(i,'timestamp',lambda:datetime.now(timezone.utc).isoformat())
            dataset = self.phase(i,'dataset',lambda:f.catalog.create(self.job+'-experience',i+1,[a['assignment_id'] for a in batch['assignments']],created_at=stamp,deduplicate=False))
            trained = self.phase(i,'train',lambda:ActionCloningBackend().train(f.catalog,dataset['dataset_id'],previous_weights=self.checkpoints.load(current)))
            checkpoint = self.phase(i,'checkpoint',lambda:self.checkpoints.save(next_policy,trained['weights'],backend=trained['backend'],dataset_id=dataset['dataset_id']))
            after = self.phase(i,'after_evaluation',lambda:self.benchmarks.run(suite['manifest_id'],next_policy,LocalProbeRuntime(f,self.checkpoints)))
            transfer = self.phase(i,'transfer',lambda:transfer_report(f,before,after,[a['assignment_id'] for a in batch['assignments']]))
            report = {'iteration':i,'before':before,'after':after,'checkpoint':checkpoint,'dataset_id':dataset['dataset_id'],
                'advisor_snapshot_id':advisor['snapshot_id'],'discovery':discovery,'feedback':executed['feedback'],
                'shortfall':batch['shortfall'],'unresolved_targets':batch.get('unresolved_advisor_targets',[]),
                'training_metrics':trained['training_metrics'],'transfer':transfer}
            reports.append(self.phase(i,'report',lambda:report))
        return {'job':self.job,'manifest_id':suite['manifest_id'],'iterations':reports,
                'notice':'Synthetic full-action imitation baseline; no GPU/physical validation or causal transfer claim.'}
