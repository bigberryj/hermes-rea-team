import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from rea_team import core, safety, pins, worker
from rea_team.cli import main
from rea_team.process import run_bounded

class TargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'targets'
        self.root.mkdir()
        self.patch = patch.object(safety, 'TARGET_ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.target = self.root / 'app'
        self.target.mkdir()
        (self.target / 'index.js').write_text('export const x = 1;')
    def snap(self, target=None, kind='javascript', destination=None):
        return safety.snapshot(str(target or self.target), kind, destination)
    def rejects(self, target=None, kind='javascript'):
        with self.assertRaises(safety.ReaError): self.snap(target, kind)
    def test_valid_snapshot_deterministic_private(self):
        dest = Path(self.temp.name) / 'snapshot'
        a = self.snap(destination=dest)
        self.assertEqual(a, self.snap())
        self.assertEqual((dest/'index.js').read_text(), 'export const x = 1;')
        self.assertEqual((dest/'index.js').stat().st_mode & 0o777, 0o600)
        self.assertEqual(dest.stat().st_mode & 0o777, 0o700)
    def test_relative(self): self.rejects('app')
    def test_parent_traversal(self): self.rejects(str(self.target) + '/../app')
    def test_double_slash(self): self.rejects(str(self.root) + '//app')
    def test_dot(self): self.rejects(str(self.root) + '/./app')
    def test_escape(self): self.rejects('/etc/passwd')
    def test_prefix_collision(self): self.rejects(str(self.root) + '-other/app')
    def test_root(self): self.rejects(self.root)
    def test_root_symlink(self):
        link = self.root/'link'; link.symlink_to(self.target); self.rejects(link)
    def test_recursive_symlink(self):
        (self.target/'evil').symlink_to('/etc'); self.rejects()
    def test_internal_symlink(self):
        (self.target/'copy.js').symlink_to('index.js'); self.rejects()
    def test_ancestor_symlink(self):
        link = Path(self.temp.name)/'alias'; link.symlink_to(self.root)
        with patch.object(safety, 'TARGET_ROOT', link): self.rejects(link/'app')
    def test_secret_names(self):
        for name in ('.env', '.env.local', 'auth.json', 'credentials.json', 'private-file', 'my-key.txt', 'secret.txt', 'passwords', 'id_rsa', '.npmrc', 'a.pem'):
            with self.subTest(name=name):
                p = self.target/name; p.write_text('SENSITIVE_SENTINEL')
                self.rejects(); p.unlink()
    def test_sensitive_directory(self):
        (self.target/'credentials').mkdir(); self.rejects()
    def test_hardlink(self):
        os.link(self.target/'index.js', self.target/'copy.js'); self.rejects()
    def test_fifo(self):
        os.mkfifo(self.target/'fifo'); self.rejects()
    def test_file_budget(self):
        with patch.object(safety,'MAX_FILE',2): self.rejects()
    def test_tree_budget(self):
        with patch.object(safety,'MAX_TREE',2): self.rejects()
    def test_entry_budget(self):
        with patch.object(safety,'MAX_ENTRIES',1): self.rejects()
    def test_depth_budget(self):
        (self.target/'dir').mkdir()
        with patch.object(safety,'MAX_DEPTH',0): self.rejects()
    def test_binary_requires_file(self): self.rejects(kind='binary')
    def test_packed_javascript_rejected(self): self.rejects(self.target/'index.js')
    def test_kind_is_allowlisted(self): self.rejects(kind='execute')
    def test_binary_static_snapshot(self): self.assertEqual(self.snap(self.target/'index.js','binary')['entries'],1)
    def test_artifact_symlink_rejected(self):
        p=Path(self.temp.name)/'link'; p.symlink_to(self.target)
        with self.assertRaises(safety.ReaError): safety.private_dir(p)

class ProcessTests(unittest.TestCase):
    def run_code(self, code, timeout=3, budget=10000):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            result=run_bounded([sys.executable,'-I','-c',code],cwd=p,env={'PATH':'/usr/bin:/bin'},stdout=p/'out',stderr=p/'err',timeout=timeout,budget=budget)
            return result,(p/'out').read_bytes(),(p/'err').read_bytes()
    def test_streams(self):
        r,out,err=self.run_code("import sys; print('ok'); print('err',file=sys.stderr)")
        self.assertEqual((r['returncode'],out,err),(0,b'ok\n',b'err\n'))
    def test_output_budget(self):
        r,out,err=self.run_code("import os; os.write(1,b'x'*1000000)",budget=1234)
        self.assertTrue(r['output_limited']); self.assertLessEqual(len(out)+len(err),1234)
    def test_stderr_budget(self):
        r,out,err=self.run_code("import os; os.write(2,b'x'*1000000)",budget=1234)
        self.assertTrue(r['output_limited']); self.assertLessEqual(len(out)+len(err),1234)
    def test_timeout(self):
        start=time.monotonic(); r,_,_=self.run_code('import time; time.sleep(10)',timeout=.1)
        self.assertTrue(r['timed_out']); self.assertLess(time.monotonic()-start,3)
    def test_group_kill_descendant_holds_pipe(self):
        r,_,_=self.run_code('import os,time; p=os.fork(); time.sleep(10) if p==0 else None',timeout=.15)
        self.assertTrue(r['timed_out'])
    def test_nonzero(self): self.assertEqual(self.run_code('raise SystemExit(3)')[0]['returncode'],3)
    def test_spawn_error(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            with self.assertRaises(safety.ReaError): run_bounded(['/not/a/command'],cwd=p,env={},stdout=p/'out',stderr=p/'err')

class FakeAgent:
    last=None
    def __init__(self,**kwargs):
        self.kwargs=kwargs; self.tools=[]; self.valid_tool_names=set(); self._fallback_chain=[]
        self._fallback_model=None; self._fallback_activated=False; self.provider=kwargs['provider']; self.model=kwargs['model']; self.closed=False
        FakeAgent.last=self
    def run_conversation(self,prompt):
        self.prompt=prompt
        return {'completed':True,'final_response':'Review with evidence citation.','messages':[], 'api_calls':1}
    def close(self): self.closed=True

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.request={'role':'security','question':'Q','evidence':{'sha256':'abc','json_text':'UNTRUSTED_SENTINEL'}}
        self.resolver=Mock(return_value={'provider':'minimax-oauth','api_mode':'anthropic_messages','api_key':'FIXTURE_NOT_REAL','base_url':'https://fixture.invalid'})
    def test_exact_route_tools_fallback_caps(self):
        r=worker.analyze(self.request,FakeAgent,self.resolver)
        a=FakeAgent.last
        self.assertEqual(r['provider'],'minimax-oauth'); self.assertEqual(r['model'],'MiniMax-M3')
        self.resolver.assert_called_once_with(requested='minimax-oauth',target_model='MiniMax-M3')
        for k,v in {'enabled_toolsets':[],'fallback_model':[],'skip_context_files':True,'skip_memory':True,'skip_background_review':True,'max_iterations':1,'max_tokens':2048,'run_budget_seconds':90}.items(): self.assertEqual(a.kwargs[k],v)
        self.assertTrue(a.closed); self.assertIn('UNTRUSTED DATA',a.prompt)
    def test_refuses_wrong_resolver_route(self):
        self.resolver.return_value['provider']='openrouter'
        with self.assertRaises(RuntimeError): worker.analyze(self.request,FakeAgent,self.resolver)
    def test_refuses_tools_before_call(self):
        class Bad(FakeAgent):
            def __init__(self,**kw): super().__init__(**kw); self.tools=['terminal']
            def run_conversation(self,prompt): raise AssertionError('MUST NOT CALL')
        with self.assertRaisesRegex(RuntimeError,'tools_not_disabled'): worker.analyze(self.request,Bad,self.resolver)
    def test_refuses_fallback_before_call(self):
        class Bad(FakeAgent):
            def __init__(self,**kw): super().__init__(**kw); self._fallback_chain=[{'provider':'other'}]
            def run_conversation(self,prompt): raise AssertionError('MUST NOT CALL')
        with self.assertRaisesRegex(RuntimeError,'fallback_not_disabled'): worker.analyze(self.request,Bad,self.resolver)
    def test_refuses_partial_empty_error_wrong_type(self):
        for value in ({'completed':False,'final_response':'partial'},{'completed':True,'final_response':''},{'completed':True,'final_response':'x','error':'bad'},'wrong'):
            with self.subTest(value=value):
                class Bad(FakeAgent):
                    def run_conversation(self,prompt): return value
                with self.assertRaises(RuntimeError): worker.analyze(self.request,Bad,self.resolver)
    def test_refuses_tool_result(self):
        class Bad(FakeAgent):
            def run_conversation(self,prompt): return {'completed':True,'final_response':'x','messages':[{'role':'assistant','tool_calls':[{}]}]}
        with self.assertRaises(RuntimeError): worker.analyze(self.request,Bad,self.resolver)
    def test_invalid_role(self):
        self.request['role']='execute'
        with self.assertRaises(RuntimeError): worker.analyze(self.request,FakeAgent,self.resolver)
        self.resolver.assert_not_called()

class OrchestrationTests(TargetTests):
    def setUp(self):
        super().setUp()
        for obj,name,value in ((core,'DATA',Path(self.temp.name)/'private'),(core,'check_pins',Mock(return_value={'build_sha256':'PIN','version':'6.7.0'})),(core,'worker_command',Mock(return_value=['fixture-worker']))):
            p=patch.object(obj,name,value); p.start(); self.addCleanup(p.stop)
        self.calls=[]
    def fake_process(self,argv,**kw):
        self.calls.append((argv,kw))
        if argv[0]=='fixture-worker':
            req=json.loads(Path(argv[-2]).read_text())
            output={'ok':True,'role':req['role'],'provider':'minimax-oauth','model':'MiniMax-M3','text':'PRIVATE_MODEL_SENTINEL','tools':[],'fallback':[]}
            safety.write_private(Path(argv[-1]),json.dumps(output))
            safety.write_private(kw['stdout'],''); safety.write_private(kw['stderr'],'')
        else:
            safety.write_private(kw['stdout'],json.dumps({'evidence_id':'fixture','normalized_result':{'text':'PRIVATE_EVIDENCE_SENTINEL'}}))
            safety.write_private(kw['stderr'],'PRIVATE_STDERR_SENTINEL')
        return {'returncode':0,'timed_out':False,'output_limited':False,'bytes':100}
    def test_team_three_roles_shared_evidence_private_returns(self):
        with patch.object(core,'run_bounded',side_effect=self.fake_process): result=core.inspect(str(self.target),'javascript',question='Q')
        self.assertTrue(result['ok']); self.assertEqual(result['roles_completed'],3); self.assertEqual(len(self.calls),4)
        self.assertNotIn('SENTINEL',json.dumps(result))
        directory=Path(result['artifacts']['directory'])
        requests=[json.loads((directory/(role+'-request.json')).read_text()) for role in worker.ROLES]
        self.assertEqual(requests[0]['evidence'],requests[1]['evidence']); self.assertEqual(requests[1]['evidence'],requests[2]['evidence'])
        for argv,kw in self.calls:
            self.assertNotIn('NODE_OPTIONS',kw['env']); self.assertNotIn('API_KEY',kw['env']); self.assertEqual(kw['env']['PATH'],'/usr/bin:/bin')
        self.assertEqual(self.calls[1][1]['env']['HERMES_HOME'],str(pins.REASONER))
        for f in directory.iterdir(): self.assertEqual(f.stat().st_mode&0o777,0o600)
    def test_deterministic_replay_no_paid_duplicate(self):
        with patch.object(core,'run_bounded',side_effect=self.fake_process):
            a=core.inspect(str(self.target),'javascript',question='Q'); b=core.inspect(str(self.target),'javascript',question='Q')
        self.assertEqual(a['run_id'],b['run_id']); self.assertEqual(len(self.calls),4)
    def test_preview_no_subprocess(self):
        with patch.object(core,'run_bounded') as proc:
            result=core.inspect(str(self.target),'javascript',question='Q',prepare=True)
        self.assertTrue(result['preview']); proc.assert_not_called()
    def test_inspect_no_model(self):
        with patch.object(core,'run_bounded',side_effect=self.fake_process): result=core.inspect(str(self.target),'javascript')
        self.assertTrue(result['ok']); self.assertEqual(len(self.calls),1); core.worker_command.assert_not_called()
    def test_global_lock(self):
        with core.team_lock():
            with self.assertRaisesRegex(safety.ReaError,'team_busy'):
                with core.team_lock(): pass
    def test_oversized_question(self):
        with self.assertRaises(safety.ReaError): core.inspect(str(self.target),'javascript',question='x'*4097)
    def test_rea_failure_stops_models(self):
        def fail(argv,**kw):
            self.fake_process(argv,**kw); return {'returncode':1,'timed_out':False,'output_limited':False}
        with patch.object(core,'run_bounded',side_effect=fail): result=core.inspect(str(self.target),'javascript',question='Q')
        self.assertFalse(result['ok']); self.assertEqual(len(self.calls),1)
    def test_worker_failure_stops_remaining_roles(self):
        def fail(argv,**kw):
            done=self.fake_process(argv,**kw)
            if argv[0]=='fixture-worker': done['returncode']=1
            return done
        with patch.object(core,'run_bounded',side_effect=fail): result=core.inspect(str(self.target),'javascript',question='Q')
        self.assertFalse(result['ok']); self.assertEqual(len(self.calls),2)
    def test_rea_invalid_json(self):
        def fail(argv,**kw):
            r=self.fake_process(argv,**kw); safety.write_private(kw['stdout'],'not json'); return r
        with patch.object(core,'run_bounded',side_effect=fail): result=core.inspect(str(self.target),'javascript')
        self.assertEqual(result['error'],'invalid_rea_json')
    def test_rea_timeout(self):
        def fail(argv,**kw):
            r=self.fake_process(argv,**kw); r['timed_out']=True; return r
        with patch.object(core,'run_bounded',side_effect=fail): result=core.inspect(str(self.target),'javascript')
        self.assertEqual(result['error'],'rea_timeout')
    def test_rea_output_limit(self):
        def fail(argv,**kw):
            r=self.fake_process(argv,**kw); r['output_limited']=True; return r
        with patch.object(core,'run_bounded',side_effect=fail): result=core.inspect(str(self.target),'javascript')
        self.assertEqual(result['error'],'rea_output_budget_exceeded')
    def test_status_no_model_or_rea(self):
        with patch.object(core,'run_bounded') as proc: result=core.status()
        self.assertTrue(result['ok']); proc.assert_not_called()
    def test_cli_preview(self):
        with contextlib.redirect_stdout(io.StringIO()) as out, patch.object(core,'run_bounded') as proc:
            self.assertEqual(main(['team',str(self.target),'--kind','javascript','--question','Q','--preview']),0)
        self.assertTrue(json.loads(out.getvalue())['preview']); proc.assert_not_called()

class PluginTests(unittest.TestCase):
    def plugin(self):
        name='integration_plugin_fixture'
        file=Path(__file__).resolve().parents[1]/'__init__.py'
        spec=importlib.util.spec_from_file_location(name,file,submodule_search_locations=[str(file.parent)])
        module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module)
        return module
    def test_exact_public_tools_schema(self):
        p=self.plugin(); ctx=Mock(); p.register(ctx)
        calls=ctx.register_tool.call_args_list
        self.assertEqual([c.kwargs['name'] for c in calls],['rea_inspect','rea_team'])
        for c in calls: self.assertEqual(c.kwargs['toolset'],'rea'); self.assertFalse(c.kwargs['schema']['parameters']['additionalProperties'])
    def test_plugin_does_not_leak_exception(self):
        p=self.plugin(); ctx=Mock(); p.register(ctx)
        with patch.object(p,'inspect',side_effect=Exception('SECRET_EXCEPTION_SENTINEL')):
            result=ctx.register_tool.call_args_list[0].kwargs['handler']({'target':'/bad','kind':'javascript'})
        self.assertNotIn('SENTINEL',result); self.assertFalse(json.loads(result)['ok'])
    def test_plugin_rejects_extra_flag(self):
        p=self.plugin(); ctx=Mock(); p.register(ctx)
        with patch.object(p,'inspect') as run:
            out=ctx.register_tool.call_args_list[0].kwargs['handler']({'target':'/x','kind':'javascript','command':'execute'})
        run.assert_not_called(); self.assertEqual(json.loads(out)['error'],'invalid_arguments')

if __name__=='__main__': unittest.main()
