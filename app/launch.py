"""Start or reuse the local server, then open the admin page."""
import json
import threading
import time
import urllib.request
import webbrowser

URL = 'http://127.0.0.1:8766'

def ready():
    try:
        with urllib.request.urlopen(URL + '/api/account', timeout=2) as r:
            return 'setup' in json.load(r)
    except Exception:
        return False

if ready():
    print('The question bank is already running. Opening the admin page…', flush=True)
    webbrowser.open(URL + '/admin-home.html')
else:
    import server
    server.PORT = 8766
    server.initialize()
    server.migrate_organization()
    server.initialize_feedback()
    server.initialize_accounts(server.DB)
    server.attempts.initialize(server.DB)
    try:
        http = server.ThreadingHTTPServer(('127.0.0.1', 8766), server.Handler)
    except OSError:
        print('Port 8766 is occupied by another application. Close that application or ask for help before retrying.')
        raise SystemExit(1)
    def open_when_ready():
        for _ in range(20):
            if ready():
                webbrowser.open(URL + '/admin-home.html')
                return
            time.sleep(0.25)
    threading.Thread(target=open_when_ready, daemon=True).start()
    print('Question bank: ' + URL + '/admin-home.html', flush=True)
    print('Keep this window open. Press Control+C to stop.', flush=True)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        print('\nQuestion bank stopped.')
    finally:
        http.server_close()
