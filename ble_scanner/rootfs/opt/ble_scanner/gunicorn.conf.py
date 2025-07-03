# Gunicorn configuration for BLE Scanner add-on
import multiprocessing

# Server socket
bind = "0.0.0.0:8099"
backlog = 2048

# Worker processes
workers = 1  # Single worker for this add-on
worker_class = "gthread"
threads = 4  # Number of threads per worker
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 30
keepalive = 2

# Restart workers after this many requests, to help prevent memory leaks
preload_app = True

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log to stderr
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "ble_scanner"

# Server mechanics
daemon = False
pidfile = None
user = None
group = None
tmp_upload_dir = None

# SSL (not used for add-on)
keyfile = None
certfile = None 