// The editor and current quiz use the local database through the server.
if (location.protocol === 'file:') {
  const admin = location.pathname.endsWith('admin.html');
  const url = 'http://127.0.0.1:8766/' + (admin ? 'admin' : '');
  document.addEventListener('DOMContentLoaded', () => {
    document.body.replaceChildren();
    const panel = document.createElement('section');
    panel.style.cssText = 'max-width:640px;margin:60px auto;padding:32px;background:white;border:1px solid #dce4ef;border-radius:14px;line-height:1.7';
    panel.innerHTML = '<h1>Open the local question bank</h1><p>This file cannot connect to your saved questions on its own.</p><ol><li>Go back to the <strong>quiz-preview</strong> folder.</li><li>Double-click <strong>Start Admin.command</strong>.</li><li>Keep its Terminal window open while you use the app.</li></ol><p>If the server is already running, use the button below.</p>';
    const link = document.createElement('a');
    link.href = url; link.className = 'primary'; link.textContent = admin ? 'Open admin page' : 'Open quiz';
    panel.append(link); document.body.append(panel);
  });
}
