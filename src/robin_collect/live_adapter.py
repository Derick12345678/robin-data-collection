"""Pinned Docker/MCP metadata transport. No raw source data crosses this boundary."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import subprocess
from .deployment import docker_binary, project_path
from .observations import validate_outcome


def script_module(root, name):
    spec=importlib.util.spec_from_file_location('collection_'+name,root/'scripts'/(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MCPDockerTransport:
    def __init__(self, root):
        self.root=Path(root)
        self.docker=docker_binary()
        self.image=json.loads((self.root/'deploy/robin.lock.json').read_text(encoding='utf-8'))['image']
        self.health_module=script_module(self.root,'robin_health')

    def health(self):
        return self.health_module.diagnose(self.root,self.docker)

    def cleanup(self,name):
        if not re.fullmatch(r'robin-capture-[0-9a-f]{32}',name):raise ValueError('Unsafe container name')
        try:
            result=subprocess.run([self.docker,'rm','--force',name],capture_output=True,timeout=20)
            if result.returncode==0:return True
            # A stopped/nonexistent container also has no outstanding source work.
            probe=subprocess.run([self.docker,'ps','--all','--filter','name=^/'+name+'$','--format','{{.Names}}'],capture_output=True,text=True,timeout=10)
            return probe.returncode==0 and not probe.stdout.strip()
        except (OSError,subprocess.TimeoutExpired):return False

    def collect(self, query, context):
        name=context['container_name']
        if not re.fullmatch(r'robin-capture-[0-9a-f]{32}',name):raise ValueError('Unsafe container name')
        outcome={'status':'failed','code':'transport_failed','observations':[],'returned_count':None}
        try:
            compose=[self.docker,'compose','--project-directory',project_path(self.root,self.docker),'-f',project_path(self.root/'compose.yaml',self.docker)]
            ui=self.health_module.capture(compose+['ps','-q','robin-ui'])
            if not re.fullmatch(r'[0-9a-f]{12,64}',ui):raise RuntimeError('UI unavailable')
            payload=(self.root/'deploy/collect_probe.py').read_text(encoding='utf-8')
            pilot_source=(self.root/'deploy/pilot_probe.py').read_text(encoding='utf-8')
            modules={name:(self.root/'src/robin_collect'/name).read_text(encoding='utf-8') for name in ['__init__.py','normalize.py','sanitize.py','observations.py','limits.py']}
            request={'config':context['config'],'key':context['key'],'entities':context['entities'],
                'query_id':query['id'],'operation_deadline_utc':context['operation_deadline_utc'],
                'modules':modules,'pilot_source':pilot_source,'aggregate_source':self._aggregate_source()}
            self.health_module.capture([self.docker,'create','-i','--name',name,'--network','container:'+ui,
                '--cap-drop','ALL','--security-opt','no-new-privileges:true','--entrypoint','python3',self.image,'-c',payload],timeout=20)
            remaining=(datetime.fromisoformat(context['operation_deadline_utc'])-datetime.now(timezone.utc)).total_seconds()
            if remaining<=0:raise TimeoutError()
            result=subprocess.run([self.docker,'start','--attach','--interactive',name],input=json.dumps(request),text=True,encoding='utf-8',capture_output=True,timeout=remaining+20)
            if result.returncode:raise RuntimeError('Capture process failed')
            outcome=json.loads(result.stdout)
        except (TimeoutError,subprocess.TimeoutExpired):
            outcome={'status':'timed_out','code':'container_deadline','observations':[],'returned_count':None}
        except Exception:
            outcome={'status':'failed','code':'transport_failed','observations':[],'returned_count':None}
        finally:
            cleanup=self.cleanup(context['container_name'])
        outcome['cleanup_confirmed']=cleanup
        return validate_outcome(outcome,context['config']['limits']['results_per_query'],query['id'])

    def _aggregate_source(self):
        # Extract a trusted function from the repository, not from source pages.
        import ast
        source=(self.root/'deploy/pilot_probe.py').read_text(encoding='utf-8')
        tree=ast.parse(source)
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='aggregate')
        return ast.get_source_segment(source,function)
