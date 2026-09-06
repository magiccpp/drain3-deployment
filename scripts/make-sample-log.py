"""Print an 800-line synthetic service log with nine message shapes (deterministic)."""
import random

random.seed(0)
comps = ["nginx", "kube-proxy", "etcd", "scheduler", "api-server", "sshd", "systemd"]
msgs = ["connection from {ip}:{port} accepted",
        "request GET /api/v1/pods latency={ms}ms status=200",
        "leader election: renewing lease for node-{n}",
        "warning: disk usage on /var/lib at {pct}% (threshold 85%)",
        "reconciling deployment default/web-{n}: 3 replicas ready",
        "TLS handshake error from {ip}:{port}: EOF",
        "started session {n} of user deploy",
        "health check passed for backend-{n} in {ms}ms",
        "ERROR failed to pull image registry.local/app:{n}: manifest unknown"]
for i in range(800):
    t = f"2026-09-06T10:{(i // 60) % 60:02d}:{i % 60:02d}Z"
    m = random.choice(msgs).format(ip=f"10.0.{random.randint(0, 255)}.{random.randint(1, 254)}",
                                   port=random.randint(1024, 65535), ms=random.randint(1, 900),
                                   n=random.randint(1, 40), pct=random.randint(60, 99))
    print(f"{t} {random.choice(comps)}[{random.randint(100, 9999)}]: {m}")
