"""First-launch maintenance page. No files, accounts, or upload endpoints exposed."""
def application(environ, start_response):
    method = environ.get('REQUEST_METHOD', 'GET')
    healthy = environ.get('PATH_INFO') == '/healthz' and method in ('GET', 'HEAD')
    body = b'ok' if healthy else b'DrillSpace is being set up. Please return later.'
    status = '200 OK' if healthy else '503 Service Unavailable'
    start_response(status, [('Content-Type', 'text/plain; charset=utf-8'),
                            ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'),
                            ('X-Content-Type-Options', 'nosniff')])
    return [b'' if method == 'HEAD' else body]
