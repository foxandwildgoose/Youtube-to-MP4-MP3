"""B14/B15/X01/I03/I12: actual ASGI boundaries and pinned thumbnail framing."""
import asyncio
import io
import json
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.main import create_app
from app.request_limits import RequestBodyLimit
from app.services import safe_http
from app.services.url_policy import parse_target
from app.errors import AppError

@pytest.mark.parametrize('url', [
    'https://[broken/watch?v=dQw4w9WgXcQ',
    'https://youtube.com:bad/watch?v=dQw4w9WgXcQ',
    'https://[::1]/watch?v=dQw4w9WgXcQ',
    'https://youtubé.com/watch?v=dQw4w9WgXcQ',
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=abcdefghijk',
    'https://www.youtube.com/watch/extra?v=dQw4w9WgXcQ',
    'https://www.youtube.com/shorts/dQw4w9WgXcQ/extra',
    'https://www.youtube.com/watch?v=dQw4w9WgXcQ\x00',
])
def test_url_errors_are_structured(url):
    with pytest.raises(AppError) as error:
        parse_target(url)
    assert error.value.status == 400

@pytest.mark.parametrize('declared', [None, b'999999', b'broken'])
def test_actual_asgi_request_limit_before_app(declared):
    consumed=[];sent=[];called=[]
    async def app(scope,receive,send): called.append(True)
    async def receive():
        consumed.append(True)
        return {'type':'http.request','body':b'x'*20000,'more_body':True}
    async def send(message): sent.append(message)
    headers=[] if declared is None else [(b'content-length',declared)]
    asyncio.run(RequestBodyLimit(app)({'type':'http','path':'/api/v1/analyses','headers':headers},receive,send))
    assert not called
    assert next(m['status'] for m in sent if m['type']=='http.response.start') == (400 if declared==b'broken' else 413)
    assert len(consumed) == (4 if declared is None else 0)
    body=json.loads(next(m['body'] for m in sent if m['type']=='http.response.body'))
    assert body['error']['code'] in {'LIMIT_EXCEEDED','BAD_REQUEST'}

def test_asgi_with_dishonest_length_is_bounded(client):
    response=client.post('/api/v1/analyses',content=b'x'*70000,headers={'content-length':'1'})
    assert response.status_code==413
    assert response.json()['error']['code']=='LIMIT_EXCEEDED'

def test_bootstrap_capability_and_cli_default(settings):
    cfg=replace(settings,allow_http_bootstrap=False)
    with TestClient(create_app(cfg),base_url='http://127.0.0.1:8000') as client:
        session=client.get('/api/v1/auth/session').json()
        assert session['authenticated'] is False
        assert session['bootstrap_allowed'] is False
        assert session['bootstrap_method']=='cli'
        response=client.post('/api/v1/auth/bootstrap',json={'password':'correct-password'},headers={'Origin':'http://127.0.0.1:8000','X-Requested-With':'seorap'})
        assert response.status_code==403

def test_auth_origins_and_bootstrap_once(api):
    api.ready()
    assert api.client.post('/api/v1/auth/bootstrap',json={'password':'other-password'},headers=api.headers()).status_code==409
    assert api.client.post('/api/v1/analyses',json={'url':'https://youtu.be/fixH264aacA'},headers={**api.headers(),'Origin':'https://evil.example'}).status_code==403
    assert api.client.post('/api/v1/analyses',json={'url':'https://youtu.be/fixH264aacA'},headers={**api.headers(),'X-CSRF-Token':''}).status_code==403
    assert api.client.get('/api/v1/jobs',headers={'Host':'evil.example'}).status_code==403
    assert api.client.post('/api/v1/auth/logout',headers=api.headers()).status_code==200
    assert api.client.get('/api/v1/jobs').status_code==401

class FakeTLS:
    def __init__(self,data): self.data=data
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def sendall(self,data): pass
    def settimeout(self,timeout): assert timeout>0
    def makefile(self,mode): return io.BytesIO(self.data)

@pytest.mark.parametrize('chunked',[False,True])
def test_standards_http_framing_decodes_equal_images(monkeypatch,chunked):
    output=io.BytesIO();Image.new('RGB',(2,2),'red').save(output,format='PNG');image=output.getvalue()
    body=(f'{len(image):x}\r\n'.encode()+image+b'\r\n0\r\n\r\n') if chunked else image
    header=b'Transfer-Encoding: chunked' if chunked else f'Content-Length: {len(image)}'.encode()
    wire=b'HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n'+header+b'\r\n\r\n'+body
    tls=FakeTLS(wire)
    monkeypatch.setattr(safe_http.socket,'create_connection',lambda *a,**k:FakeTLS(b''))
    context=MagicMock();context.wrap_socket.return_value=tls
    monkeypatch.setattr(safe_http.ssl,'create_default_context',lambda:context)
    data,status,headers=safe_http._read('8.8.8.8',443,'i.ytimg.com','/image',1,2000)
    assert status==200 and data==image
    assert safe_http._image_valid(data,headers['content-type'])
    context.wrap_socket.assert_called_once()
    assert context.wrap_socket.call_args.kwargs['server_hostname']=='i.ytimg.com'

def test_thumbnail_private_mixed_dns_redirect_and_bad_image(monkeypatch):
    monkeypatch.setattr(safe_http.socket,'getaddrinfo',lambda *a,**k:[(0,0,0,'',('8.8.8.8',443)),(0,0,0,'',('127.0.0.1',443))])
    with pytest.raises(AppError):safe_http._resolve('i.ytimg.com',443)
    monkeypatch.setattr(safe_http,'_resolve',lambda *a:['8.8.8.8'])
    monkeypatch.setattr(safe_http,'_read',lambda *a:(b'',302,{'location':'https://127.0.0.1/private'}))
    with pytest.raises(AppError):safe_http.fetch_thumbnail('https://i.ytimg.com/test-redirect')
    assert not safe_http._image_valid(b'\x89PNG\r\n\x1a\n' + b'x'*100,'image/png')
    with pytest.raises(AppError):safe_http.fetch_thumbnail('https://i.ytimg.com:444/nope')

def test_thumbnail_size_and_truncated_framing(monkeypatch):
    for wire,code in [(b'HTTP/1.1 200 OK\r\nContent-Length: 99999\r\n\r\n','LIMIT_EXCEEDED'),(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nabc','SOURCE_UNAVAILABLE')]:
        monkeypatch.setattr(safe_http.socket,'create_connection',lambda *a,**k:FakeTLS(b''))
        context=MagicMock();context.wrap_socket.return_value=FakeTLS(wire)
        monkeypatch.setattr(safe_http.ssl,'create_default_context',lambda:context)
        with pytest.raises(AppError) as exc:safe_http._read('8.8.8.8',443,'i.ytimg.com','/x',1,1000)
        assert exc.value.code==code

def test_concurrent_browser_bootstrap_cannot_replace_first_password(client, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app import security
    barrier = threading.Barrier(2)
    original = security.hash_password
    def synchronized_hash(password):
        value = original(password)
        barrier.wait(timeout=5)
        return value
    monkeypatch.setattr(security, 'hash_password', synchronized_hash)
    headers={'Origin':'http://127.0.0.1:8000','X-Requested-With':'seorap'}
    def submit(password):
        return client.post('/api/v1/auth/bootstrap',json={'password':password},headers=headers).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,['fixture-password-one','fixture-password-two']))
    assert sorted(results)==[200,409]

def test_thumbnail_dns_uses_aggregate_deadline_without_unbounded_queue(monkeypatch):
    import threading
    import time
    release = threading.Event()
    monkeypatch.setattr(safe_http, '_resolve', lambda *args: (release.wait(2), ['8.8.8.8'])[1])
    started=time.monotonic()
    try:
        for _ in range(3):
            with pytest.raises(AppError) as error:
                safe_http._resolve_with_deadline('i.ytimg.com',443,.02)
            assert error.value.status==504
        assert time.monotonic()-started<.5
    finally:
        release.set()

@pytest.mark.parametrize('title', ['CON.txt','aux.data','LPT1.video','COM9 .mp4'])
def test_download_name_escapes_windows_device_stems(title):
    from app.services.storage import safe_download_name
    assert safe_download_name(title,'mp4','job12345').startswith('_')

def test_spa_per_request_style_nonce_preserves_script_policy(client):
    import re
    from app.main import render_spa_index
    one=client.get('/')
    two=client.get('/')
    policy=one.headers['content-security-policy']
    nonce=re.search(r"'nonce-([A-Za-z0-9_-]+)'",policy).group(1)
    assert nonce not in two.headers['content-security-policy']
    assert "'unsafe-inline'" not in policy
    assert "script-src 'self' https://grok.com" in policy
    rendered=render_spa_index('<html><head></head><body></body></html>',nonce)
    assert f'name="csp-style-nonce" content="{nonce}"' in rendered
    if one.status_code==200:
        assert f'content="{nonce}"' in one.text
        assert one.headers['cache-control']=='no-store'

@pytest.mark.parametrize('variable', ['REQUIRE_PASSWORD','ALLOW_HTTP_BOOTSTRAP','ENABLE_TRANSCODING'])
def test_invalid_boolean_flags_fail_closed_without_silently_disabling_auth(monkeypatch, variable):
    from app.config import load_settings
    monkeypatch.setenv(variable,'ture')
    with pytest.raises(SystemExit, match=variable+' must be a boolean'):
        load_settings()
