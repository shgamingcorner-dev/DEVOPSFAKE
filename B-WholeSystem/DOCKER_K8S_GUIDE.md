# Smart Fire Alert — Docker + Kubernetes Setup Guide (Raspberry Pi)

> **For:** ET0735 Mini Project — Docker (Lab 8 style) + Kubernetes (k3s)
> **Repo:** DEVOPSFAKE (private) — B-WholeSystem is the app

---

## 0. What you need to know first (read this!)

- **No manual Dockerfile edits needed.** The `Dockerfile` in this folder is
  ready to build — it already includes the ARM base image, the `--trusted-host`
  SSL fix from Lab 8, and the GPIO/I2C libs.
- **Check your Pi arch** before building:
  ```bash
  uname -m
  # armv7l  = 32-bit -> base image arm32v7 (already in Dockerfile) ✓
  # aarch64 = 64-bit -> edit Dockerfile line: arm64v8/python:3.7-slim-bullseye
  ```

---

## PART 1 — Docker (Lab 8 style)

### Step 1. Install Docker
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```
Add user to docker group (optional, avoids sudo):
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Step 2. Build the image
```bash
cd ~/DEVOPSFAKE/B-WholeSystem
docker build -t smart-fire-alert:latest .
```
> If you hit "SSL Cert Failed" — **don't edit anything**: the Dockerfile
> already has `--trusted-host` (the Lab 8 fix).

### Step 3. Run it (with hardware access — the critical part)
```bash
docker run -d --name fire-alert \
  --privileged \
  --device /dev/gpiomem \
  --device /dev/i2c-1 \
  --env-file .env \
  smart-fire-alert:latest
```
Check it works:
```bash
docker logs -f fire-alert
```
You should see the same output as `sudo python3 main.py` (env OK, "System asleep", sensors reading).

### Step 4. (Easier) Use docker-compose instead
```bash
cd ~/DEVOPSFAKE/B-WholeSystem
sudo docker-compose up -d --build
sudo docker-compose logs -f fire-alert
```
`docker-compose.yml` already sets `privileged: true` + `.env` — one command, done.

### Step 5. Clean up (Lab 8 style)
```bash
docker container stop $(docker container ls -aq)
docker container rm $(docker container ls -aq)
docker image rm $(docker image ls -aq)
```

---

## PART 2 — Kubernetes (k3s on the Pi)

### Step 6. Install k3s (lightweight K8s built for the Pi)
```bash
curl -sfL https://get.k3s.io | sh -
```
Low-RAM Pi (1GB)? Disable the extras:
```bash
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik --disable servicelb" sh -
```
Verify:
```bash
sudo k3s kubectl get nodes    # raspberrypi should be Ready
```

### Step 7. Deploy the demo web service
```bash
cd ~/DEVOPSFAKE/B-WholeSystem
sudo k3s kubectl apply -f k8s/
sudo k3s kubectl get pods     # wait for Running
sudo k3s kubectl get svc      # note the NodePort
curl http://localhost:<NodePort>
```

### Step 8. (Optional) Run the actual fire-alarm in K8s
```bash
# Load the local image into k3s
sudo k3s ctr images import smart-fire-alert.tar   # or use imagePullPolicy: Never

# Create the env secret
sudo k3s kubectl create secret generic fire-alert-env --from-env-file=../.env

# Apply the privileged deployment
sudo k3s kubectl apply -f k8s/app-deployment.yaml
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `SSL Cert Failed` on build | Old Buster certs | Already fixed in Dockerfile (`--trusted-host`) |
| GPIO/LCD don't work in container | No hardware perms | `--privileged` (Docker) / `privileged: true` (compose) |
| `exec format error` | Wrong arch image | Check `uname -m`, change base image |
| k3s slow / OOM | 1GB Pi | `--disable traefik --disable servicelb` |
| Pod stuck ImagePullBackOff | Local image not in k3s | `imagePullPolicy: Never` + `k3s ctr images import` |

---

## What maps to the course rubric

| Course requirement | What you show |
|---|---|
| Docker container on Pi (Lab 8) | `docker build` + `docker run --privileged` of the fire-alarm app |
| Understand Dockerfile lines | The commented Dockerfile (each line explained) |
| Hardware access in container | `--privileged` + device mounts (GPIO/I2C) |
| Kubernetes on Pi | k3s cluster + Deployment + Service (NodePort) |
| Docs | This guide + comments in the YAML |
