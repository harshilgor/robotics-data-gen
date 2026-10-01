"""Optional content-addressed S3 payload transport; no bucket provisioning."""
from hashlib import sha256
import json
import re
from task_advisor.core import canonical


class S3ObjectStore:
    version = 's3-objects-1.0'
    media_types = {'application/json','application/octet-stream','image/png','application/x-depth-f32'}
    def __init__(self, *, bucket, prefix='robotics', client=None, allow_external_writes=False):
        if not isinstance(bucket,str) or not bucket or not re.fullmatch(r'[A-Za-z0-9/_-]+',prefix):
            raise ValueError('configured bucket and safe object prefix required')
        if client is None:
            import boto3
            client = boto3.client('s3')
        self.bucket,self.prefix,self.client,self.authorized = bucket,prefix.rstrip('/'),client,allow_external_writes
    def key(self,digest):
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
            raise ValueError('invalid payload digest')
        return self.prefix+'/'+digest[:2]+'/'+digest
    def put(self,value):return self.put_bytes(canonical(value).encode(),media_type='application/json')
    def put_bytes(self,payload, *, media_type='application/octet-stream'):
        if not self.authorized:raise PermissionError('external storage writes require explicit authorization')
        if not isinstance(payload,bytes) or media_type not in self.media_types:
            raise ValueError('unsupported payload encoding')
        digest=sha256(payload).hexdigest()
        key=self.key(digest)
        try:
            self.client.put_object(Bucket=self.bucket,Key=key,Body=payload,ContentType=media_type,IfNoneMatch='*')
        except Exception as exc:
            if getattr(exc,'response',{}).get('ResponseMetadata',{}).get('HTTPStatusCode') != 412:raise
            existing=self.client.get_object(Bucket=self.bucket,Key=key)['Body'].read()
            if existing != payload:raise ValueError('content-addressed object conflict') from exc
        return {'storage_schema':self.version,'sha256':digest,'bytes':len(payload),'media_type':media_type}
    def get(self,reference):
        if reference.get('media_type') != 'application/json':raise ValueError('JSON payload required')
        return json.loads(self.get_bytes(reference))
    def get_bytes(self,reference):
        if set(reference) != {'storage_schema','sha256','bytes','media_type'} or reference['storage_schema'] != self.version or reference['media_type'] not in self.media_types:
            raise ValueError('invalid S3 payload reference')
        payload=self.client.get_object(Bucket=self.bucket,Key=self.key(reference['sha256']))['Body'].read()
        if len(payload) != reference['bytes'] or sha256(payload).hexdigest() != reference['sha256']:
            raise ValueError('payload integrity check failed')
        return payload
