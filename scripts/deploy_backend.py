#!/usr/bin/env python3
"""Deploy backend code over the current server image without storing server details.

Requires ``python -m pip install paramiko`` on the operator's computer.
See ``docs/backend-deployment.md`` before running.
"""

from __future__ import annotations

import argparse
import base64
from datetime import UTC, datetime
import getpass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
IMAGE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]*$")
CONTAINER_PATTERN = re.compile(r"^[0-9a-f]{12,64}$")
SERVICE_PATTERN = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
IMAGE_LINE_PATTERN = re.compile(r"^(\s+image:\s*)(\S+)(\s*)$")


def build_source_archive(root: Path, destination: Path) -> None:
    """Archive only backend/app source; never package .env, data, or caches."""
    source = root / "backend" / "app"
    if not source.is_dir() or source.is_symlink():
        raise ValueError("backend/app must be a real directory")
    files = []
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"Refusing symlink in backend source: {path}")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix == ".py":
            files.append(path)
    if not files:
        raise ValueError("backend/app contains no files")
    with tarfile.open(destination, "w:gz") as archive:
        for path in sorted(files):
            name = path.relative_to(root / "backend").as_posix()
            info = tarfile.TarInfo(name)
            info.size = path.stat().st_size
            info.mode = 0o644
            info.mtime = 0
            with path.open("rb") as source_file:
                archive.addfile(info, source_file)


def replace_service_images(compose: str, old_image: str, new_image: str) -> str:
    """Change the API and worker images in a Compose override, and nothing else."""
    if not IMAGE_PATTERN.fullmatch(old_image) or not IMAGE_PATTERN.fullmatch(new_image):
        raise ValueError("Invalid Docker image name")
    current_service = None
    seen = {"api": 0, "worker": 0}
    updated = []
    for line in compose.splitlines(keepends=True):
        service = SERVICE_PATTERN.match(line.rstrip("\r\n"))
        if service:
            current_service = service.group(1)
        if current_service in seen:
            body = line.rstrip("\r\n")
            image = IMAGE_LINE_PATTERN.match(body)
            if image:
                if image.group(2) != old_image:
                    raise ValueError(f"Unexpected {current_service} image")
                seen[current_service] += 1
                ending = line[len(body):]
                line = f"{image.group(1)}{new_image}{image.group(3)}{ending}"
        updated.append(line)
    if seen != {"api": 1, "worker": 1}:
        raise ValueError("Compose override must define one image for API and worker")
    return "".join(updated)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _runtime_manifest(root: Path) -> dict[str, str]:
    backend = root / "backend"
    paths = [backend / name for name in ("pyproject.toml", "uv.lock", "alembic.ini")]
    paths.extend(path for path in (backend / "alembic").rglob("*") if path.is_file())
    for path in paths:
        if path.is_symlink():
            raise ValueError(f"Refusing symlink in backend runtime files: {path}")
    return {
        path.relative_to(backend).as_posix(): _sha256(path)
        for path in paths
        if "__pycache__" not in path.parts and path.suffix != ".pyc"
    }


def _git_revision(root: Path) -> str:
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        text=True,
    )
    if status.strip():
        raise ValueError("Git working tree is not clean; commit or stash changes first")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


class Remote:
    def __init__(self, client) -> None:
        self.client = client

    def run(self, command: str, *, timeout: int = 120) -> str:
        _, stdout, _ = self.client.exec_command(command, timeout=timeout)
        stdout.channel.set_combine_stderr(True)
        output = stdout.read().decode("utf-8", errors="replace")
        status = stdout.channel.recv_exit_status()
        if status:
            raise RuntimeError(f"Remote command failed (exit {status}): {output[-2000:]}")
        return output.strip()

    def compose(self, directory: str) -> str:
        try:
            self.run("docker compose version")
            prefix = "docker compose"
        except RuntimeError:
            self.run("docker-compose version")
            prefix = "docker-compose"
        return (
            f"cd {shlex.quote(directory)} && {prefix} "
            "-f compose.yaml -f compose.prod.yaml"
        )


def _container_id(remote: Remote, compose: str, service: str) -> str:
    identifier = remote.run(f"{compose} ps -q {shlex.quote(service)}")
    if not CONTAINER_PATTERN.fullmatch(identifier):
        raise RuntimeError(f"Could not identify running {service} container")
    return identifier


def _remote_runtime_manifest(remote: Remote, container_id: str) -> dict[str, str]:
    script = (
        "import hashlib,json,pathlib; "
        "root=pathlib.Path('/app'); "
        "paths=[root/n for n in ('pyproject.toml','uv.lock','alembic.ini')]; "
        "paths += [p for p in (root/'alembic').rglob('*') if p.is_file()]; "
        "print(json.dumps({p.relative_to(root).as_posix(): "
        "hashlib.sha256(p.read_bytes()).hexdigest() for p in paths "
        "if '__pycache__' not in p.parts and p.suffix != '.pyc'}))"
    )
    output = remote.run(f"docker exec {container_id} python -c {shlex.quote(script)}")
    return json.loads(output)


def _image_for(remote: Remote, container_id: str) -> str:
    image = remote.run(
        f"docker inspect --format {shlex.quote('{{.Config.Image}}')} {container_id}"
    )
    if not IMAGE_PATTERN.fullmatch(image) or "@" in image:
        raise RuntimeError("Current API image is not a supported tagged image")
    return image


def _wait_for_api(remote: Remote, compose: str) -> None:
    for _ in range(30):
        time.sleep(2)
        try:
            api = _container_id(remote, compose, "api")
            health = remote.run(
                f"docker inspect --format {shlex.quote('{{.State.Health.Status}}')} {api}"
            )
            if health == "healthy":
                worker = _container_id(remote, compose, "worker")
                running = remote.run(
                    f"docker inspect --format {shlex.quote('{{.State.Running}}')} {worker}"
                )
                if running == "true":
                    return
        except RuntimeError:
            pass
    raise RuntimeError("API or worker did not become healthy within 60 seconds")


def _remove_app_containers(remote: Remote, compose: str) -> None:
    identifiers = []
    for service in ("api", "worker"):
        identifier = remote.run(f"{compose} ps -q {service}")
        if identifier:
            if not CONTAINER_PATTERN.fullmatch(identifier):
                raise RuntimeError(f"Unsafe {service} container identifier")
            identifiers.append(identifier)
    if identifiers:
        remote.run("docker rm -f " + " ".join(identifiers))


def deploy(remote: Remote, root: Path, directory: str, revision: str) -> str:
    compose = remote.compose(directory)
    api = _container_id(remote, compose, "api")
    worker = _container_id(remote, compose, "worker")
    old_image = _image_for(remote, api)
    if _image_for(remote, worker) != old_image:
        raise RuntimeError("API and worker currently use different images")
    if _remote_runtime_manifest(remote, api) != _runtime_manifest(root):
        raise RuntimeError(
            "Dependencies or Alembic migrations differ from the running image. "
            "This code-only deploy cannot safely apply those changes."
        )

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    repository = old_image.rsplit(":", 1)[0]
    new_image = f"{repository}:{revision[:12]}-{timestamp}"
    remote_context = remote.run("mktemp -d /tmp/portfolio-backend-deploy.XXXXXX")
    if not remote_context.startswith("/tmp/portfolio-backend-deploy."):
        raise RuntimeError("Unexpected temporary deployment directory")
    override = str(PurePosixPath(directory) / "compose.prod.yaml")
    backup = f"{override}.pre-{timestamp}"
    changed_override = False
    try:
        with tempfile.TemporaryDirectory() as local_context:
            archive = Path(local_context) / "source.tar.gz"
            build_source_archive(root, archive)
            sftp = remote.client.open_sftp()
            try:
                sftp.put(str(archive), f"{remote_context}/source.tar.gz")
                with sftp.file(f"{remote_context}/Dockerfile", "w") as dockerfile:
                    dockerfile.write(f"FROM {old_image}\nCOPY app /app/app\n")
                with sftp.file(override, "r") as source:
                    current_override = source.read().decode("utf-8")
                new_override = replace_service_images(
                    current_override, old_image, new_image
                )
                remote.run(
                    f"tar -xzf {shlex.quote(remote_context + '/source.tar.gz')} "
                    f"-C {shlex.quote(remote_context)}"
                )
                remote.run(
                    f"docker build --pull=false -t {shlex.quote(new_image)} "
                    f"{shlex.quote(remote_context)}",
                    timeout=300,
                )
                remote.run(
                    f"docker run --rm {shlex.quote(new_image)} "
                    "python -c " + shlex.quote("from app.main import app"),
                    timeout=60,
                )
                remote.run(f"cp -p {shlex.quote(override)} {shlex.quote(backup)}")
                with sftp.file(f"{override}.next", "w") as destination:
                    destination.write(new_override)
                remote.run(
                    f"mv {shlex.quote(override + '.next')} {shlex.quote(override)}"
                )
                changed_override = True
                remote.run(f"{compose} config --quiet")
                _remove_app_containers(remote, compose)
                remote.run(f"{compose} up -d --no-build api worker", timeout=180)
                _wait_for_api(remote, compose)
            finally:
                sftp.close()
    except Exception:
        if changed_override:
            print("Deployment failed; restoring previous API and worker image.", file=sys.stderr)
            remote.run(f"cp -p {shlex.quote(backup)} {shlex.quote(override)}")
            _remove_app_containers(remote, compose)
            remote.run(f"{compose} up -d --no-build api worker", timeout=180)
            _wait_for_api(remote, compose)
        raise
    finally:
        remote.run(f"rm -rf -- {shlex.quote(remote_context)}")
    return new_image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("DEPLOY_HOST"), required=False)
    parser.add_argument("--user", default=os.getenv("DEPLOY_USER"), required=False)
    parser.add_argument("--port", type=int, default=int(os.getenv("DEPLOY_SSH_PORT", "22")))
    parser.add_argument("--remote-dir", default=os.getenv("DEPLOY_REMOTE_DIR"))
    parser.add_argument("--host-key-sha256", default=os.getenv("DEPLOY_HOST_KEY_SHA256"))
    parser.add_argument("--identity-file", default=os.getenv("DEPLOY_IDENTITY_FILE"))
    parser.add_argument("--use-agent", action="store_true")
    args = parser.parse_args()
    if not all((args.host, args.user, args.remote_dir, args.host_key_sha256)):
        parser.error("host, user, remote-dir, and host-key-sha256 are required")
    if not 1 <= args.port <= 65535:
        parser.error("port must be in 1..65535")
    remote_dir = PurePosixPath(args.remote_dir)
    if not remote_dir.is_absolute() or ".." in remote_dir.parts or str(remote_dir) == "/":
        parser.error("remote-dir must be an absolute application directory")
    revision = _git_revision(ROOT)

    try:
        import paramiko
    except ImportError as exc:
        raise SystemExit("Install Paramiko locally: python -m pip install paramiko") from exc

    expected = args.host_key_sha256.removeprefix("SHA256:").rstrip("=")

    class VerifyHostKey(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            actual = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
            if actual != expected:
                raise paramiko.SSHException(
                    f"SSH host key mismatch for {hostname}; got SHA256:{actual}"
                )

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(VerifyHostKey())
    password = None
    if not args.identity_file and not args.use_agent:
        password = getpass.getpass("SSH password (not saved): ")
    try:
        client.connect(
            args.host,
            port=args.port,
            username=args.user,
            password=password,
            key_filename=args.identity_file,
            allow_agent=args.use_agent,
            look_for_keys=args.use_agent,
            timeout=15,
        )
        image = deploy(Remote(client), ROOT, str(remote_dir), revision)
        print(f"Deployed {image}; API and worker are healthy.")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
