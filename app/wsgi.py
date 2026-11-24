"""WSGI transport for the existing route handlers; Gunicorn owns HTTP parsing."""
import io,json,mimetypes,os,posixpath,sqlite3,logging
from email.message import Message
from http import HTTPStatus
from urllib.parse import unquote,urlsplit
from pathlib import Path
import server
ORIGIN=os.environ.get('PUBLIC_ORIGIN','').rstrip('/')
if not ORIGIN.startswith('https://') or urlsplit(ORIGIN).path:raise RuntimeError('Set PUBLIC_ORIGIN to the exact HTTPS site origin')
SECRET_KEYS={'accepted','choice_scores','lower','upper','explanation','explanation_image','explanation_caption','notes'}
def clean(q):
 q={k:v for k,v in q.items() if k not in SECRET_KEYS};q['accepted']=[];return q
class Request(server.Handler):
 def __init__(self,environ):
  self.command=environ['REQUEST_METHOD'];self.path=environ.get('PATH_INFO','/')+('?' + environ['QUERY_STRING'] if environ.get('QUERY_STRING') else '')
  self.request_version='HTTP/1.1';self.requestline=self.command+' '+self.path;self.client_address=(environ.get('REMOTE_ADDR','unknown'),0)
  self.headers=Message()
  for k,v in environ.items():
   if k.startswith('HTTP_') and k not in ['HTTP_HOST','HTTP_ORIGIN']:self.headers[k[5:].replace('_','-')]=v
  self.headers['Host']=f'localhost:{server.PORT}'
  if environ.get('HTTP_ORIGIN'):self.headers['Origin']=f'http://localhost:{server.PORT}'
  self.headers['Content-Type']=environ.get('CONTENT_TYPE','');self.headers['Content-Length']=environ.get('CONTENT_LENGTH','0') or '0'
  self.rfile=environ['wsgi.input'];self.wfile=io.BytesIO();self.status=200;self.response_headers=[];self.directory=str(server.DIST)
 def send_response(self,code,message=None):self.status=code
 def send_header(self,key,value):
  if key.lower()=='set-cookie':value+='; Secure'
  self.response_headers.append((key,str(value)))
 def end_headers(self):pass
 def log_message(self,*args):pass
 def send_error(self,code,message=None,explain=None):self.send_data(code,{'error':message or HTTPStatus(code).phrase})
 def send_head(self):
  path=posixpath.normpath('/'+unquote(urlsplit(self.path).path).lstrip('/'))
  if path=='/':path='/index.html'
  f=(server.DIST/path.lstrip('/')).resolve()
  if not f.is_relative_to(server.DIST.resolve()) or not f.is_file() or any(x.startswith('.') for x in Path(path).parts):self.send_error(404);return None
  self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(str(f))[0] or 'application/octet-stream');self.send_header('Content-Length',str(f.stat().st_size));return f.open('rb')
 def visible_questions(self):
  qs=super().visible_questions()
  return qs if self.current_user()['role'] in ['admin','editor'] else [clean(q) for q in qs]
 def send_data(self,code,data,kind='application/json',filename=None):
  if kind=='application/json' and isinstance(data,dict) and data.get('mode')=='exam' and not data.get('submitted') and 'questions' in data:
   data=dict(data,questions=[clean(q) for q in data['questions']])
  super().send_data(code,data,kind,filename)
def application(environ,start_response):
 def reject(code,message):
  body=json.dumps({'error':message}).encode();start_response(f'{code} {HTTPStatus(code).phrase}',[('Content-Type','application/json'),('Content-Length',str(len(body)))]);return [body]
 if environ.get('HTTP_HOST')!=urlsplit(ORIGIN).netloc:return reject(403,'Unknown host')
 method=environ['REQUEST_METHOD'];path=environ.get('PATH_INFO','/')
 if path=='/healthz' and method in ['GET','HEAD']:
  start_response('200 OK',[('Content-Type','text/plain')]);return [b'ok' if method=='GET' else b'']
 if method not in ['GET','HEAD','POST','PUT']:return reject(405,'Method not allowed')
 if method in ['POST','PUT']:
  if environ.get('HTTP_ORIGIN')!=ORIGIN:return reject(403,'Request origin not allowed')
  try:length=int(environ.get('CONTENT_LENGTH','0'))
  except ValueError:return reject(400,'Invalid length')
  if not 0<length<=12000000:return reject(413,'Request too large or empty')
 if path=='/api/register':return reject(403,'Public registration is disabled during deployment testing.')
 h=Request(environ)
 try:getattr(h,'do_'+method)()
 except Exception:
  logging.exception('Request failed');return reject(500,'Request failed')
 body=h.wfile.getvalue();headers=[(k,v) for k,v in h.response_headers if k.lower() not in ['connection','transfer-encoding','content-length']]
 headers += [('Content-Length',str(len(body))),('X-Content-Type-Options','nosniff'),('X-Frame-Options','DENY'),('Referrer-Policy','same-origin'),('Cache-Control','no-store')]
 start_response(f'{h.status} {HTTPStatus(h.status).phrase}',headers);return [b'' if method=='HEAD' else body]
if os.environ.get('CLOUD_BACKUPS','1')=='1':
 import cloud_backups
 cloud_backups.start()
