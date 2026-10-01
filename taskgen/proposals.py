"""Explicit opt-in hosted declarative proposals, with identical offline checks."""
import json
import os
import urllib.request
from copy import deepcopy
from .core import validate


def validate_proposals(value, *, limit=8):
    if not isinstance(value, dict) or set(value) != {'tasks'} or not isinstance(value['tasks'],list) or len(value['tasks']) > limit:
        raise ValueError('proposal response requires bounded tasks array only')
    for task in value['tasks']:
        checked = task
        if task.get('schema_version') == 'semantic-1.0':
            from semantics.execution import lower
            checked = lower(task)
        report = validate(checked)
        if not report.structurally_valid:
            raise ValueError('unsafe/invalid proposal: '+str(report.errors))
        from task_compiler.bindings import parameter_schema
        parameter_schema(checked)
    return deepcopy(value['tasks'])


class FixtureProposalProvider:
    def __init__(self, response):
        self.response = deepcopy(response)
    def propose(self, request, vocabulary):
        return validate_proposals(self.response)


class HostedProposalProvider:
    def __init__(self, *, endpoint, model, api_key_env, allow_external_inference=False, timeout=30, transport=None):
        if not endpoint.startswith('https://'):
            raise ValueError('hosted proposal endpoint must use HTTPS')
        self.endpoint,self.model,self.api_key_env = endpoint,model,api_key_env
        self.authorized,self.timeout,self.transport = allow_external_inference,timeout,transport
    def propose(self, request, vocabulary):
        if not self.authorized:
            raise PermissionError('hosted inference requires explicit authorization')
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ValueError('configured hosted proposal credential unavailable')
        body = {'model':self.model,'response_format':{'type':'json_object'},'messages':[
            {'role':'system','content':'Return only JSON {"tasks": [...]} with at most 8 TaskSpecs. Use only the supplied schema, skills, assets and typed parameters. No code or unknown fields.'},
            {'role':'user','content':json.dumps({'request':request,'vocabulary':vocabulary},allow_nan=False)}]}
        raw = json.dumps(body,allow_nan=False).encode()
        if self.transport:
            response = self.transport(self.endpoint,raw,{'Authorization':'Bearer '+key},self.timeout)
        else:
            req = urllib.request.Request(self.endpoint,data=raw,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=self.timeout) as stream:
                response = stream.read(2_000_001)
        if len(response) > 2_000_000:
            raise ValueError('proposal response exceeds size bound')
        parsed = json.loads(response)
        content = parsed['choices'][0]['message']['content']
        return validate_proposals(json.loads(content))
