#!/usr/bin/env python3
"""
Render VPS - Turn your Render service into a full VPS
Run this on Render to get SSH access, file management, and more
"""

import os
import sys
import json
import time
import socket
import subprocess
import threading
import hashlib
import base64
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

# ========== CONFIGURATION ==========
PORT = int(os.environ.get('PORT', 8080))
VPS_PASSWORD = os.environ.get('VPS_PASSWORD', 'render123')  # Change this!
VPS_USER = os.environ.get('VPS_USER', 'render')
AUTH_TOKEN = hashlib.sha256(VPS_PASSWORD.encode()).hexdigest()

# ========== COMMAND EXECUTION ==========
def execute_command(cmd, cwd=None):
    """Execute system command and return output"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=30
        )
        return {
            'success': True,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'code': result.returncode
        }
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Command timeout'}
    except Exception as e:
        return {'success': False, 'error': str(e)}

def get_system_info():
    """Get system information"""
    info = {
        'hostname': socket.gethostname(),
        'ip': socket.gethostbyname(socket.gethostname()),
        'platform': sys.platform,
        'python': sys.version,
        'cwd': os.getcwd(),
        'time': datetime.now().isoformat(),
        'env': dict(os.environ),
        'disk': execute_command('df -h').get('stdout', ''),
        'memory': execute_command('free -h').get('stdout', ''),
        'cpu': execute_command('nproc').get('stdout', '').strip(),
        'processes': execute_command('ps aux | head -20').get('stdout', '')
    }
    return info

# ========== WEB INTERFACE ==========
class VPSHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        
        # Authenticate
        auth = self.headers.get('Authorization', '')
        if not self.authenticate(auth):
            self.send_auth_request()
            return
        
        if path == '/':
            self.send_file_browser()
        elif path == '/api/info':
            self.send_json(get_system_info())
        elif path.startswith('/api/ls'):
            dir_path = path[8:] or '.'
            self.send_json(execute_command(f'ls -la {dir_path}'))
        elif path.startswith('/api/cat'):
            file_path = path[9:]
            self.send_json(execute_command(f'cat {file_path}'))
        elif path.startswith('/api/download'):
            file_path = path[14:]
            self.send_file(file_path)
        elif path == '/api/ps':
            self.send_json(execute_command('ps aux'))
        elif path == '/api/df':
            self.send_json(execute_command('df -h'))
        elif path == '/api/uptime':
            self.send_json(execute_command('uptime'))
        elif path.startswith('/api/term'):
            self.send_terminal()
        else:
            self.send_error(404, 'Not Found')
    
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        
        auth = self.headers.get('Authorization', '')
        if not self.authenticate(auth):
            self.send_auth_request()
            return
        
        if path == '/api/exec':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(post_data)
            cmd = data.get('cmd', '')
            cwd = data.get('cwd', None)
            result = execute_command(cmd, cwd)
            self.send_json(result)
        
        elif path == '/api/upload':
            # Handle file upload
            content_type = self.headers.get('Content-Type', '')
            if 'multipart/form-data' in content_type:
                # Parse multipart
                boundary = content_type.split('boundary=')[1].encode()
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length)
                
                # Save file
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, dir='.') as f:
                    f.write(body)
                    filename = f.name
                
                self.send_json({'success': True, 'file': filename})
            else:
                self.send_json({'success': False, 'error': 'Invalid content type'})
        
        elif path == '/api/mkdir':
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            dirname = data.get('name', '')
            result = execute_command(f'mkdir -p {dirname}')
            self.send_json(result)
        
        elif path == '/api/rm':
            data = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            filename = data.get('file', '')
            result = execute_command(f'rm -rf {filename}')
            self.send_json(result)
        
        else:
            self.send_error(404, 'Not Found')
    
    def authenticate(self, auth_header):
        if not auth_header:
            return False
        
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            return token == AUTH_TOKEN
        elif auth_header.startswith('Basic '):
            # Basic auth: base64(username:password)
            try:
                decoded = base64.b64decode(auth_header[6:]).decode()
                username, password = decoded.split(':', 1)
                return username == VPS_USER and password == VPS_PASSWORD
            except:
                return False
        return False
    
    def send_auth_request(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Render VPS"')
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'error': 'Authentication required'}).encode())
    
    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())
    
    def send_file(self, filepath):
        try:
            if os.path.isfile(filepath):
                self.send_response(200)
                self.send_header('Content-type', 'application/octet-stream')
                self.send_header('Content-Disposition', f'attachment; filename="{os.path.basename(filepath)}"')
                self.end_headers()
                
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, 'File not found')
        except Exception as e:
            self.send_error(500, str(e))
    
    def send_file_browser(self):
        """Send HTML file browser interface"""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Render VPS</title>
            <style>
                body {{ background: #0a0a0a; color: #00ff88; font-family: 'Courier New'; margin: 0; padding: 20px; }}
                .container {{ max-width: 1200px; margin: 0 auto; }}
                h1 {{ color: #00f5ff; }}
                .header {{ display: flex; justify-content: space-between; align-items: center; }}
                .terminal {{ background: #1a1a1a; border: 1px solid #333; padding: 15px; height: 300px; overflow-y: auto; font-family: monospace; }}
                .input {{ width: 100%; padding: 10px; background: #1a1a1a; border: 1px solid #00ff88; color: #00ff88; font-family: monospace; }}
                .button {{ background: #00ff88; color: #0a0a0a; border: none; padding: 10px 20px; cursor: pointer; font-family: monospace; }}
                .button:hover {{ background: #00f5ff; }}
                .files {{ background: #1a1a1a; border: 1px solid #333; padding: 10px; margin: 10px 0; }}
                .file {{ padding: 5px; cursor: pointer; }}
                .file:hover {{ background: #333; }}
                .dir {{ color: #00f5ff; }}
                .tab {{ display: inline-block; padding: 10px 20px; background: #1a1a1a; cursor: pointer; }}
                .tab.active {{ background: #333; border-bottom: 2px solid #00ff88; }}
                .tab-content {{ display: none; }}
                .tab-content.active {{ display: block; }}
                .status {{ color: #00ff88; }}
                .error {{ color: #ff4444; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🚀 Render VPS Control Panel</h1>
                
                <div class="header">
                    <div>
                        <span class="status">🟢 Online</span> | 
                        <span id="hostname">Loading...</span>
                    </div>
                    <div>
                        <span id="uptime"></span>
                    </div>
                </div>
                
                <div style="margin: 20px 0;">
                    <div class="tab" onclick="showTab('terminal')">💻 Terminal</div>
                    <div class="tab" onclick="showTab('files')">📁 Files</div>
                    <div class="tab" onclick="showTab('processes')">📊 Processes</div>
                    <div class="tab" onclick="showTab('system')">⚙️ System</div>
                </div>
                
                <!-- Terminal Tab -->
                <div id="terminal-tab" class="tab-content active">
                    <h3>Command Terminal</h3>
                    <div class="terminal" id="terminal"></div>
                    <div style="display: flex; margin-top: 10px;">
                        <input type="text" id="cmd" class="input" placeholder="Enter command..." onkeypress="if(event.key==='Enter') runCommand()">
                        <button class="button" onclick="runCommand()">Run</button>
                        <button class="button" onclick="clearTerminal()" style="margin-left: 5px;">Clear</button>
                    </div>
                    <div style="margin-top: 10px;">
                        <button class="button" onclick="runCommand('ls -la')">📂 List Files</button>
                        <button class="button" onclick="runCommand('pwd')">📌 Current Dir</button>
                        <button class="button" onclick="runCommand('whoami')">👤 Whoami</button>
                        <button class="button" onclick="runCommand('df -h')">💾 Disk Space</button>
                        <button class="button" onclick="runCommand('free -h')">🧠 Memory</button>
                    </div>
                </div>
                
                <!-- Files Tab -->
                <div id="files-tab" class="tab-content">
                    <h3>File Browser</h3>
                    <div style="display: flex; margin-bottom: 10px;">
                        <input type="text" id="filePath" class="input" value="." placeholder="Directory path">
                        <button class="button" onclick="listFiles()">Browse</button>
                        <button class="button" onclick="uploadFile()" style="margin-left: 5px;">📤 Upload</button>
                    </div>
                    <div class="files" id="fileList"></div>
                </div>
                
                <!-- Processes Tab -->
                <div id="processes-tab" class="tab-content">
                    <h3>Running Processes</h3>
                    <button class="button" onclick="showProcesses()">Refresh</button>
                    <pre id="processes" style="background: #1a1a1a; padding: 10px; margin-top: 10px; overflow-x: auto;"></pre>
                </div>
                
                <!-- System Tab -->
                <div id="system-tab" class="tab-content">
                    <h3>System Information</h3>
                    <pre id="systemInfo" style="background: #1a1a1a; padding: 10px;"></pre>
                </div>
            </div>
            
            <script>
                const AUTH = 'Basic ' + btoa('{VPS_USER}:{VPS_PASSWORD}');
                
                function showTab(tab) {
                    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                    document.getElementById(tab + '-tab').classList.add('active');
                    event.target.classList.add('active');
                }
                
                function runCommand(cmd) {
                    const terminal = document.getElementById('terminal');
                    const cmdInput = document.getElementById('cmd');
                    const command = cmd || cmdInput.value;
                    
                    if (!command) return;
                    
                    terminal.innerHTML += `<div>> ${command}</div>`;
                    
                    fetch('/api/exec', {
                        method: 'POST',
                        headers: {
                            'Authorization': AUTH,
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({cmd: command})
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.stdout) {
                            terminal.innerHTML += `<pre style="margin: 5px 0;">${data.stdout}</pre>`;
                        }
                        if (data.stderr) {
                            terminal.innerHTML += `<pre style="color: #ff4444; margin: 5px 0;">${data.stderr}</pre>`;
                        }
                        terminal.scrollTop = terminal.scrollHeight;
                    })
                    .catch(err => {
                        terminal.innerHTML += `<div class="error">Error: ${err}</div>`;
                    });
                    
                    cmdInput.value = '';
                }
                
                function clearTerminal() {
                    document.getElementById('terminal').innerHTML = '';
                }
                
                function listFiles() {
                    const path = document.getElementById('filePath').value;
                    fetch('/api/ls/' + encodeURIComponent(path), {
                        headers: {'Authorization': AUTH}
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.stdout) {
                            const fileList = document.getElementById('fileList');
                            fileList.innerHTML = '<pre>' + data.stdout + '</pre>';
                        }
                    });
                }
                
                function showProcesses() {
                    fetch('/api/ps', {
                        headers: {'Authorization': AUTH}
                    })
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('processes').textContent = data.stdout || data.stderr;
                    });
                }
                
                function uploadFile() {
                    const input = document.createElement('input');
                    input.type = 'file';
                    input.onchange = function(e) {
                        const file = e.target.files[0];
                        const formData = new FormData();
                        formData.append('file', file);
                        
                        fetch('/api/upload', {
                            method: 'POST',
                            headers: {'Authorization': AUTH},
                            body: formData
                        })
                        .then(r => r.json())
                        .then(data => {
                            if (data.success) {
                                alert('File uploaded: ' + data.file);
                                listFiles();
                            }
                        });
                    };
                    input.click();
                }
                
                // Load initial data
                fetch('/api/info', {headers: {'Authorization': AUTH}})
                    .then(r => r.json())
                    .then(data => {
                        document.getElementById('hostname').textContent = data.hostname;
                        document.getElementById('systemInfo').textContent = JSON.stringify(data, null, 2);
                    });
                
                setInterval(() => {
                    fetch('/api/uptime', {headers: {'Authorization': AUTH}})
                        .then(r => r.json())
                        .then(data => {
                            if (data.stdout) {
                                document.getElementById('uptime').textContent = data.stdout;
                            }
                        });
                }, 5000);
            </script>
        </body>
        </html>
        """
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html.encode())
    
    def send_terminal(self):
        """WebSocket-like terminal (simplified)"""
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Web Terminal</title>
            <style>
                body { background: black; color: #00ff00; font-family: monospace; padding: 20px; }
                #output { height: 500px; overflow-y: auto; }
                #input { width: 100%; background: black; color: #00ff00; border: none; outline: none; font-family: monospace; }
            </style>
        </head>
        <body>
            <div id="output"></div>
            <input type="text" id="input" placeholder="$ ">
            
            <script>
                const output = document.getElementById('output');
                const input = document.getElementById('input');
                
                function run(cmd) {
                    output.innerHTML += `<div>$ ${cmd}</div>`;
                    fetch('/api/exec', {
                        method: 'POST',
                        headers: {
                            'Authorization': 'Bearer {AUTH_TOKEN}',
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({cmd: cmd})
                    })
                    .then(r => r.json())
                    .then(data => {
                        if (data.stdout) output.innerHTML += `<pre>${data.stdout}</pre>`;
                        if (data.stderr) output.innerHTML += `<pre style="color:red">${data.stderr}</pre>`;
                        output.scrollTop = output.scrollHeight;
                    });
                }
                
                input.addEventListener('keypress', (e) => {
                    if (e.key === 'Enter' && input.value) {
                        run(input.value);
                        input.value = '';
                    }
                });
            </script>
        </body>
        </html>
        """
        self.wfile.write(html.encode())

# ========== BACKGROUND SERVICES ==========
def start_ssh_service():
    """Simulate SSH service (if available)"""
    try:
        # Check if we can start sshd
        subprocess.run(['which', 'sshd'], check=True)
        
        # Generate host keys if needed
        if not os.path.exists('/etc/ssh/ssh_host_rsa_key'):
            subprocess.run(['ssh-keygen', '-A'])
        
        # Start sshd
        subprocess.Popen(['/usr/sbin/sshd', '-D'])
        print("[✓] SSH service started")
    except:
        print("[!] SSH not available (running in container)")

def start_cron_service():
    """Start cron for scheduled tasks"""
    try:
        subprocess.Popen(['cron', '-f'])
        print("[✓] Cron service started")
    except:
        print("[!] Cron not available")

def start_keep_alive():
    """Keep the service alive"""
    while True:
        try:
            # Light CPU work
            for i in range(1000):
                _ = i * i
            
            # Log heartbeat
            if int(time.time()) % 60 == 0:
                print(f"[Heartbeat] {datetime.now().strftime('%H:%M:%S')}")
            
            time.sleep(30)
        except:
            time.sleep(30)

# ========== MAIN ==========
if __name__ == '__main__':
    print("""
╔════════════════════════════════════╗
║     RENDER VPS v2.0                ║
║     Turn Render into a VPS         ║
╚════════════════════════════════════╝
    """)
    
    print(f"[✓] VPS User: {VPS_USER}")
    print(f"[✓] VPS Password: {VPS_PASSWORD}")
    print(f"[✓] Auth Token: {AUTH_TOKEN[:16]}...")
    print(f"[✓] Port: {PORT}")
    print(f"[✓] Working Dir: {os.getcwd()}")
    print()
    print(f"[✓] Access URL: https://your-app.onrender.com")
    print(f"[✓] Web Interface: https://your-app.onrender.com")
    print(f"[✓] API Endpoint: https://your-app.onrender.com/api/info")
    print()
    print("[*] Starting background services...")
    
    # Start background threads
    threading.Thread(target=start_keep_alive, daemon=True).start()
    threading.Thread(target=start_ssh_service, daemon=True).start()
    threading.Thread(target=start_cron_service, daemon=True).start()
    
    # Start web server
    print(f"[✓] Web server starting on port {PORT}...")
    server = HTTPServer(('0.0.0.0', PORT), VPSHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] Shutting down...")
        server.shutdown()
