from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from factory import LocalFactory
from factory.adaptive import AdaptiveLoop
from semantics import default_registry, predicate
from semantics.execution import lower
from taskgen.bootstrap import coverage_bootstrap
from taskgen.structural import mutate_structure
from taskgen.core import TaskGenerator, fingerprint, novelty
from taskgen.proposals import FixtureProposalProvider, HostedProposalProvider
from task_compiler.bindings import split_parameters
from simulation import LocalSimulationAdapter
from training import ActionCloningBackend, CheckpointStore
from integrations.isaac_lab import SO101Config, IsaacLabCompiler, JOINTS
from integrations.so101 import SO101Transport
from tests.test_semantics import semantic_task


class ClosureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.factory = LocalFactory(self.directory.name)
    def tearDown(self):
        self.factory.close()
        self.directory.cleanup()

    def run_task(self,task, *, parameters=None):
        compiled = self.factory.compiler.compile(task)
        task = compiled['task']
        instance = TaskGenerator(7).sample(task)
        if parameters:
            for name,value in parameters.items():
                instance['theta' if name in task['theta'] else 'phi'][name] = value
        values = {**instance['theta'],**instance['phi']}
        build,reset = split_parameters(task,values)
        adapter = LocalSimulationAdapter()
        adapter.configure('e',compiled,'k',build)
        adapter.install('e',{'assignment_id':'a','sampling_seed':instance['seed'],'task_parameters':instance['theta'],
            'environment_parameters':instance['phi'],'compiled_artifact_hash':fingerprint(compiled)},'ep')
        adapter.apply_reset('e',reset)
        adapter.reset('e',task['initial_state'],task['success'])
        frames = []
        for _ in range(task['horizon']):
            action = adapter.controller_action('e',adapter.observations('e'),{'id':'local-reference'})
            frame = adapter.step('e',action)['frame'];frames.append(frame)
            if frame['terminated'] or frame['truncated']:break
        return adapter, frames

    def test_semantic_source_compound_goal_runs_through_governed_factory(self):
        source = semantic_task(default_registry())
        source['goal'].append(predicate('near','movable','destination',tolerance=.03))
        record = self.factory.publish(source)
        self.assertEqual(record['task']['semantic'],source)
        batch = self.factory.sample(total=1,seed=2,policy_version='p',window='semantic')
        result = self.factory.execute(batch)
        self.assertTrue(result['summaries'][0]['success'])
        ep = self.factory.store.records('episodes')[0]
        self.assertTrue(all(ep['predicate_outcomes']['goal']))
        self.assertTrue(self.factory.advise('p')['generator_feedback'])

    def test_semantic_constraints_terminate_and_attribute_failure(self):
        source = semantic_task(default_registry())
        source['constraints'] = [predicate('avoid_collision','arm','movable')]
        adapter,frames = self.run_task(source)
        self.assertTrue(frames[-1]['terminated'])
        self.assertFalse(all(frames[-1]['semantic_measurements']['constraints']))
        self.assertLess(adapter.environments['e']['stage'],len(adapter.configurations['e']['artifact']['task']['task_graph']))
        self.assertLess(frames[-1]['reward'],1.)

    def test_disjoint_role_dag_serialization_and_unsafe_shared_role_rejection(self):
        source = semantic_task(default_registry())
        source['roles']['second'] = {'requires':['graspable','insertable']}
        source['initial'].append(predicate('reachable','second'))
        for node in deepcopy(source['skill_graph']):
            node['id'] += '2'
            node['roles'] = {k:('second' if v=='movable' else v) for k,v in node['roles'].items()}
            node['depends_on'] = [d+'2' for d in node['depends_on']]
            source['skill_graph'].append(node)
        source['goal'].append(predicate('inside','second','destination'))
        executable = lower(source)
        self.assertEqual(len(executable['task_graph']),12)
        _, frames = self.run_task(source)
        self.assertTrue(all(frames[-1]['semantic_measurements']['goal']))
        source['skill_graph'][-4]['roles']['object'] = 'movable'
        with self.assertRaises(ValueError):lower(source)

    def test_realized_drawer_access_open_initial_flag_and_container_fit(self):
        task = next(t for t in coverage_bootstrap() if t['family']=='open_and_retrieve')
        adapter,frames = self.run_task(task)
        self.assertTrue(frames[-1]['terminated'])
        env=adapter.environments['e']
        self.assertEqual(env['layout']['access']['movable'],'object')
        self.assertGreaterEqual(env['role_openings']['object'],.9)
        opened=deepcopy(task);opened['initial_state']['object'].append('opened')
        adapter,_=self.run_task(opened)
        self.assertEqual(adapter.environments['e']['initial_state']['layout']['openings']['object'],1.)
        retrieval=next(t for t in coverage_bootstrap() if t['family']=='retrieve_from_container')
        adapter,_=self.run_task(retrieval)
        self.assertIn('_container',adapter.environments['e']['layout']['geometry'])
        inserted=next(t for t in coverage_bootstrap() if t['family']=='insert')
        inserted['theta']['target_width']=[.01,.01]
        with self.assertRaisesRegex(ValueError,'fit'):
            # Explicit initial inclusion proves container-fit rejection at reset.
            inserted['scene']['relations']=[{'relation':'inside','roles':['object','target']}]
            self.run_task(inserted)

    def test_parameters_change_geometry_sensor_and_contact_and_unknown_rejects(self):
        task=next(t for t in coverage_bootstrap() if t['family']=='transport_around_obstacle')
        task['theta'].update(obstacle_count={'type':'int','bounds':[0,2]},layout_offset=[-.03,.03])
        first,_=self.run_task(task,parameters={'obstacle_count':0,'layout_offset':-.03})
        second,_=self.run_task(task,parameters={'obstacle_count':2,'layout_offset':.03})
        self.assertEqual(len(first.environments['e']['layout']['obstacles']),0)
        self.assertEqual(len(second.environments['e']['layout']['obstacles']),2)
        self.assertNotEqual(first.capture_initial('e'),second.capture_initial('e'))
        task['phi']['grip_strength']=[.05,.05]
        _,frames=self.run_task(task)
        self.assertTrue(frames[-1]['truncated'])
        task['phi']['unimplemented_wind']=[1.,2.]
        with self.assertRaisesRegex(ValueError,'binding'):self.factory.compiler.compile(task)

    def test_slide_and_disturbed_recovery_have_measured_events(self):
        for name in ('slide_to_target','drop_and_recover'):
            task=next(t for t in coverage_bootstrap() if t['family']==name)
            self.factory.publish(task,source='bootstrap')
        batch=self.factory.sample(total=2,seed=2,policy_version='p',window='coverage')
        result=self.factory.execute(batch)
        self.assertTrue(all(s['success'] for s in result['summaries']))
        recovery=next(e for e in self.factory.store.records('episodes') if e['grasp_losses'])
        self.assertGreater(recovery['capability_events']['regrasp_step_count'],0)
        capabilities={c['capability_id']:c for c in self.factory.advise('p')['capabilities']}
        self.assertEqual(capabilities['recovery']['sample_count'],1)
        self.assertEqual(capabilities['grasp_stability']['successes'],0)
        self.assertEqual(capabilities['manipulation']['sample_count'],2)

    def test_structural_mutation_and_novelty_are_nontextual(self):
        task=next(t for t in coverage_bootstrap() if t['family']=='insert')
        child=mutate_structure(task,'spatial')
        self.assertGreater(novelty(child,[task])['spatial'],0.)
        child=mutate_structure(task,'object')
        self.assertGreater(novelty(child,[task])['compositional'],0.)
        changed=deepcopy(task);changed['family']='new textual description'
        self.assertEqual(novelty(changed,[task])['goal'],0.)
        with self.assertRaises(ValueError):mutate_structure(task,'eval_python')

    def test_proposal_fixture_strict_validation_and_no_charges_by_default(self):
        task=next(t for t in coverage_bootstrap() if t['family']=='insert')
        self.assertEqual(FixtureProposalProvider({'tasks':[task]}).propose({},{}),[task])
        task['code']='print(1)'
        with self.assertRaises(ValueError):FixtureProposalProvider({'tasks':[task]}).propose({},{})
        provider=HostedProposalProvider(endpoint='https://example.invalid',model='configured',api_key_env='UNUSED')
        with self.assertRaises(PermissionError):provider.propose({},{})

    def test_publication_patch_minor_major_preserves_exact_versions(self):
        first=self.factory.seed()[0]['task']
        patch=deepcopy(first);patch['revision']+=1;patch['provenance']['note']='metadata only'
        self.factory.publish(patch)
        minor=deepcopy(patch);minor['revision']+=1;minor['theta']['tolerance'][1]=.05
        self.factory.publish(minor)
        major=deepcopy(minor);major['revision']+=1;major['theta']['tolerance'][0]=.02
        self.factory.publish(major)
        versions=self.factory.library.search(family_id='local-reach')
        self.assertEqual({r['version'] for r in versions},{'1.0.0','1.0.1','1.1.0','2.0.0'})
        self.assertEqual(self.factory.library.get_version('local-reach','1.0.0')['task_spec'],first)

    def test_optional_integration_plans_and_hardware_do_not_claim_live_validation(self):
        asset=Path(self.directory.name)/'robot.usd';asset.write_text('#usda 1.0')
        robot=SO101Config('2.2',str(asset),'so101-test',JOINTS,tuple([(-1.,1.)]*6),tuple([0.]*6),10.,1.,1.,1.,'gripper')
        task=self.factory.seed()[0]['task'];compiled=self.factory.compiler.compile(task)
        instance=TaskGenerator(1).sample(task)
        plan=IsaacLabCompiler(robot).compile(compiled,{**instance['theta'],**instance['phi']},seed=1,num_envs=2)
        self.assertEqual(plan['num_envs'],2)
        self.assertIn('requires live',plan['evidence_status'])
        robot_bad=SO101Config('unknown',str(asset),'test',JOINTS,robot.joint_limits,robot.home,10.,1.,1.,1.,'gripper')
        with self.assertRaises(ValueError):IsaacLabCompiler(robot_bad)
        transport=SO101Transport(object(),limits=dict(zip(JOINTS,robot.joint_limits)))
        with self.assertRaises(PermissionError):transport.connect()


    def test_compound_place_goal_and_signed_orientation(self):
        source = semantic_task(default_registry())
        source['skill_graph'][-1]['skill'] = 'place'
        source['capabilities'][-1] = 'precision_placement'
        source['goal'].append(predicate('stable','movable',maximum_speed=.01))
        adapter,frames = self.run_task(source)
        self.assertTrue(all(frames[-1]['semantic_measurements']['goal']))
        task = next(t for t in coverage_bootstrap() if t['family']=='object_rotation')
        task['phi']['initial_yaw'] = [-.6,-.4]
        _,frames = self.run_task(task,parameters={'initial_yaw':-.5})
        self.assertTrue(frames[-1]['terminated'])
        self.assertLess(frames[-1]['extended_measurements']['orientation_error'],.05)

    def test_spatial_conflicts_are_rejected_before_execution(self):
        task = next(t for t in coverage_bootstrap() if t['family']=='pick_place')
        roles = list(task['objects'])
        task['scene']['relations'] = [{'relation':'beside','roles':roles}, {'relation':'beside','roles':roles[::-1]}]
        with self.assertRaisesRegex(ValueError,'cyclic'): self.run_task(task)

    def test_restart_recovers_inflight_local_lease_without_duplicate_evidence(self):
        self.factory.seed()
        batch = self.factory.sample(total=1,seed=9,policy_version='p',window='crash')
        assignment = batch['assignments'][0]
        from task_advisor.worker import AssignmentEnvironments
        import time
        bridge = AssignmentEnvironments(self.factory.scheduler,LocalSimulationAdapter(),clock=time.monotonic)
        bridge.start('e',assignment['assignment_id'],'dead-attempt',worker_id='local-worker',ttl=60.)
        bridge.step('e')
        result = self.factory.execute(batch)
        self.assertEqual(len(result['summaries']),1)
        self.assertEqual(len(self.factory.repo.records('completion')),1)
        self.assertEqual(self.factory.repo.get('execution_failure','dead-attempt')['reason'],'local_process_restart')
        self.assertEqual(self.factory.execute(batch)['summaries'],result['summaries'])
        self.assertEqual(len(self.factory.repo.records('completion')),1)

    def test_s3_idempotency_integrity_and_unauthorized_write(self):
        import io
        from data.s3 import S3ObjectStore
        class Conflict(Exception):
            response = {'ResponseMetadata':{'HTTPStatusCode':412}}
        class Client:
            def __init__(self): self.data = {}
            def put_object(self,**kw):
                if kw['Key'] in self.data: raise Conflict()
                self.data[kw['Key']] = kw['Body']
            def get_object(self,**kw): return {'Body':io.BytesIO(self.data[kw['Key']])}
        client = Client()
        with self.assertRaises(PermissionError): S3ObjectStore(bucket='test',client=client).put({'x':1})
        store = S3ObjectStore(bucket='test',client=client,allow_external_writes=True)
        ref = store.put({'x':1})
        self.assertEqual(ref,store.put({'x':1}))
        self.assertEqual(store.get(ref),{'x':1})
        client.data[store.key(ref['sha256'])] = b'corrupt'
        with self.assertRaisesRegex(ValueError,'integrity'): store.get(ref)

    def test_ik_joint_limits_and_residual_do_not_claim_feasibility(self):
        try: __import__('numpy')
        except ImportError: self.skipTest('optional NumPy IK dependency unavailable')
        from integrations.ik import damped_joint_target
        result = damped_joint_target([0.],[[1.]],[1.],[(-.02,.02)])
        self.assertEqual(result['joint_target'],[.02])
        self.assertGreater(result['linearized_residual'],.9)
        self.assertIn('unknown',result['feasibility_status'])
        with self.assertRaises(ValueError): damped_joint_target([0.],[[float('nan')]],[1.],[(-1.,1.)])

    def test_hosted_fixture_transport_and_semantic_allowlist(self):
        from unittest.mock import patch
        source = semantic_task(default_registry())
        calls=[]
        def transport(endpoint,body,headers,timeout):
            calls.append(json.loads(body))
            return json.dumps({'choices':[{'message':{'content':json.dumps({'tasks':[source]})}}]}).encode()
        provider=HostedProposalProvider(endpoint='https://example.invalid',model='fixture',api_key_env='TEST_FIXTURE_KEY',allow_external_inference=True,transport=transport)
        with patch.dict('os.environ',{'TEST_FIXTURE_KEY':'offline-fixture'}):
            self.assertEqual(provider.propose({},{}),[source])
        self.assertEqual(len(calls),1)
        source['goal'][0]['predicate'] = 'execute_code'
        with self.assertRaises(ValueError): FixtureProposalProvider({'tasks':[source]}).propose({},{})


class AdaptiveRestartTests(unittest.TestCase):
    def test_two_iterations_restart_idempotency_frozen_eval_and_complete_actions(self):
        with tempfile.TemporaryDirectory() as root:
            f=LocalFactory(root)
            try:
                loop=AdaptiveLoop(f,job='test-loop',episodes=16)
                interrupted=loop.run(2,stop_after_phase=(0,'execution'))
                self.assertIn('interrupted_after',interrupted)
                before_count=len(f.repo.records('completion'))
            finally:f.close()
            f=LocalFactory(root)
            try:
                loop=AdaptiveLoop(f,job='test-loop',episodes=16)
                report=loop.run(2)
                self.assertEqual(len(report['iterations']),2)
                self.assertTrue(all(i['feedback']['executed_episodes'] > 0 for i in report['iterations']))
                count=len(f.repo.records('completion'))
                self.assertGreater(count,before_count)
                self.assertEqual(report,loop.run(2))
                self.assertEqual(count,len(f.repo.records('completion')))
                manifest=f.repo.get('benchmark',report['manifest_id'])
                self.assertEqual({c['partition'] for c in manifest['cases']},{'precision','contact','long_horizon','unseen_parameters','unseen_layout','unseen_object_combination','heldout_composition'})
                heldouts={(r['family_id'],r['family_version']) for r in f.repo.records('heldout_family')}
                self.assertFalse(heldouts & {(a['family_id'],a['family_version']) for a in f.repo.records('assignment') if a['episode_purpose']!='evaluation'})
                checkpoint=CheckpointStore(f.repo).load('test-loop-policy-2')
                self.assertEqual(checkpoint['policy_type'],'action-knn-1.0')
                self.assertGreater(len(checkpoint['examples']),6)
                self.assertTrue(report['iterations'][1]['transfer']['capability_changes'])
                self.assertIn('Observational',report['iterations'][1]['transfer']['interpretation'])
                with self.assertRaisesRegex(ValueError,'immutable'):AdaptiveLoop(f,job='test-loop',episodes=9)
            finally:f.close()
