# Volcengine OSWorld v1 Image Guide

This guide builds the Ubuntu guest used by the `osworldv1` profile from a public,
pinned OSWorld image. It intentionally publishes a reproducible process rather than a
download link to a GADE-owned binary image.

> **Cost and safety:** the workflow creates TOS, snapshot, EIP, disk, and ECS resources.
> Review current Volcengine pricing and quotas first. Never bake model keys, cloud keys,
> browser sessions, proxy credentials, or benchmark account credentials into an image.

## Locked inputs

GADE CUA Evolve is tested with the unmodified
[`GADE-Tech/OSWorld`](https://github.com/GADE-Tech/OSWorld) fork at:

```text
b7db4d8c85d9e95e0b1db44de5bec954cf37f0cf
```

The fork commit is an upstream OSWorld commit with no GADE-specific source changes. Pinning
it prevents later benchmark and environment changes from silently altering a reproduction.

The guest image is the public
[`Ubuntu.qcow2.zip`](https://huggingface.co/datasets/xlangai/ubuntu_osworld/blob/9600484566f238a9ce57ea32c33567c6044e41d8/Ubuntu.qcow2.zip)
from `xlangai/ubuntu_osworld`:

```text
Hugging Face revision: 9600484566f238a9ce57ea32c33567c6044e41d8
SHA-256: b795b6cd4c69b252c1b4f10150a347795555032501b60fd031751ed09b896712
Archive size: 12,273,896,463 bytes
```

## 1. Prepare the host checkout

Use Python 3.12 and install both repositories in the same environment:

```bash
git clone https://github.com/GADE-Tech/OSWorld.git
git -C OSWorld checkout b7db4d8c85d9e95e0b1db44de5bec954cf37f0cf

git clone https://github.com/GADE-Tech/GADE-CUA-Evolve.git
cd GADE-CUA-Evolve
uv sync --extra google --extra dev
uv pip install -e ../OSWorld
export OSWORLD_ROOT="$(cd ../OSWorld && pwd)"
```

The pinned OSWorld provider reads Volcengine settings from process environment variables or
`.env`. Keep `.env` local and untracked.

## 2. Create cloud prerequisites

In one Volcengine region, enable ECS, snapshots, and TOS. Create a VPC, a subnet, and an ECS
security group. The TOS bucket used for image import must be in the same region as the target
ECS image.

Grant only the permissions needed to manage the relevant ECS, image, snapshot, EIP, subnet,
security-group, and TOS resources. The first ECS image import also requires explicitly
authorizing the ECS service account to read the TOS object. Follow Volcengine's
[`Import a custom image`](https://www.volcengine.com/docs/6396/69081?lang=zh) prerequisites.

### Network rules

The runtime host must be able to reach the guest over the VPC network:

| Port | Source | Purpose |
| --- | --- | --- |
| TCP 5000 | Runtime host security group or private CIDR | OSWorld control API |
| TCP 9222 | Runtime host security group or private CIDR | Chrome DevTools proxy |
| TCP 5910 | Optional trusted operator IP only | noVNC debugging |
| TCP 22 | Optional trusted operator IP only | Image provisioning |

Do not expose 5000 or 9222 to the public internet. Chrome port 1337 remains inside the VM and
must not be added to the security group. Remove optional SSH/noVNC access after image setup if
it is not required for operations.

### Default disposable-run topology

The repository's validated path creates one isolated VM per task. The runtime host owns model
calls, task scheduling, recording, evaluation, and cleanup; OSWorld owns the desktop lifecycle.

```mermaid
flowchart LR
    USER["CLI / batch runner"] --> LOOP["GADE AgentLoop"]
    LOOP --> MODEL["Model endpoints<br/>Planner · Grounder · Coder · ARM"]
    LOOP -->|"private TCP 5000 / 9222"| VM["Disposable OSWorld VM<br/>one task"]
    VM -->|"task egress, when required"| EIP["Per-worker EIP"]
    LOOP --> OUT["Local trajectory<br/>screenshots · JSONL · result"]
    LOOP -->|"finally"| DELETE["Delete VM and EIP"]
```

Keep the runtime host in a network that can address the guest privately. TCP 5000 and 9222 are
control-plane ports, not general internet endpoints.

## 3. Download, verify, and upload the official QCOW2

Install `curl`, `unzip`, `qemu-img`, and Volcengine
[`tosutil`](https://www.volcengine.com/docs/6349/152752?lang=en). Initialize `tosutil` with a
credential source outside this repository.

Use a volume with at least 40 GiB free:

```bash
./scripts/prepare_volcengine_image.sh \
  --work-dir /data/osworld-image \
  --upload \
  --tos-bucket YOUR_PRIVATE_BUCKET \
  --tos-key osworld-v1/Ubuntu.qcow2
```

The script resumes partial downloads, verifies the locked SHA-256, runs `qemu-img info` and
`qemu-img check`, uploads with TOS checksum verification, and prints the object URL for the ECS
import wizard. Use `--dry-run` to inspect all locked inputs without downloading anything.

Do not make the bucket or object public. ECS uses the service-account authorization from the
previous step.

## 4. Import the base image

In **ECS → Images → Custom images → Import image**:

1. Select the same region as the TOS bucket.
2. Paste the object URL printed by the preparation script.
3. Select Linux/Ubuntu and the OS version matching the guest. Do not guess a different kernel.
4. Import it as a system-disk image and enable image detection.
5. Wait until both the import task and image detection finish.

The accepted source formats, size limits, TOS authorization, and UI fields are maintained in
the official [custom-image import guide](https://www.volcengine.com/docs/6396/69081?lang=zh).

## 5. Provision the Coder dependencies

Create one temporary ECS instance from the imported image. Connect through a trusted private
path, ECS console, or temporarily restricted SSH rule. Inside the guest checkout, run:

```bash
./scripts/provision_osworld_coder.sh
```

This installs the bounded Coder's common command-line and document-processing dependencies and
checks the OSWorld service plus guest ports 5000 and 9222. Fix any failure before continuing.

Inspect the guest manually as well:

```bash
systemctl status osworld_server.service
curl --fail http://127.0.0.1:5000/probe
curl --fail http://127.0.0.1:9222/json/version
```

An OSWorld server version may not expose `/probe`; in that case, an HTTP response from port 5000
and the host-side `gade-cua env probe` below are the authoritative checks.

## 6. Sanitize and create the final image

Before finalization, remove all task artifacts and manually inspect browser profiles, home
directories, `/root`, and temporary storage. Never use a guest that has held real benchmark
accounts as a public reproduction base.

Run the guarded finalizer:

```bash
./scripts/provision_osworld_coder.sh --finalize
```

It refuses to continue when it finds common `.env`, OAuth credential, or SSH private-key files;
then it clears shell histories, Coder temporary files, pip cache, and Cloud-Init instance state.
Review its output, shut down the instance, and create a system-disk custom image by following
Volcengine's [`Create a custom Linux image`](https://www.volcengine.com/docs/6396/71393?lang=zh)
guide. Stopping the instance first avoids filesystem inconsistency.

Record, but do not commit, the resulting image ID.

## 7. Scaling for training and rollout collection

For large-scale inference, reinforcement-learning rollout collection, or supervised trajectory
generation, avoid assigning one public EIP to every OSWorld worker. Put runner hosts and guest
VMs in the same VPC, address guests by private IP, and centralize only the required HTTP(S)
egress through one or more hardened Squid gateways.

This repository produces trajectories that can feed an external training pipeline; it does not
implement the model trainer itself. Horizontal capacity comes from deterministic batch shards,
multiple runner processes or hosts, and an external scheduler or queue.

```mermaid
flowchart TB
    SCHED["Job scheduler / rollout queue"] --> RUNNERS["GADE runner pool<br/>shards · retries · cleanup"]
    RUNNERS --> MODEL["Inference endpoint pool"]
    RUNNERS -->|"private TCP 5000 / 9222"| W1["OSWorld worker 01<br/>no EIP"]
    RUNNERS -->|"private TCP 5000 / 9222"| W2["OSWorld worker 02<br/>no EIP"]
    RUNNERS -->|"private TCP 5000 / 9222"| WN["OSWorld worker N<br/>no EIP"]
    W1 -->|"explicit HTTP(S) proxy"| SQUID["Squid egress gateway<br/>ACL · logs · rate limits"]
    W2 -->|"explicit HTTP(S) proxy"| SQUID
    WN -->|"explicit HTTP(S) proxy"| SQUID
    SQUID -->|"one controlled EIP or NAT"| INTERNET["Allowlisted external services"]
    RUNNERS --> TOS["Durable trajectory storage<br/>TOS / dataset pipeline"]
    RUNNERS -->|"finally"| CLEANUP["Delete every worker"]
```

The Squid gateway is an **egress proxy**, not the jump path for OSWorld control traffic. Runners
must still reach worker private addresses directly. Never proxy or publish guest TCP 5000/9222,
and never expose Squid as an unauthenticated public proxy.

### Required infrastructure changes

The pinned `GADE-Tech/OSWorld` checkout is unmodified, and the current repository has no
`--no-eip` switch. Treat this as an operator deployment topology: the cloud/provider lifecycle
layer must allocate workers without public addresses, return reachable private addresses to the
runner, and preserve deletion semantics for partial failures.

1. Place runner hosts, workers, and Squid in private subnets with explicit security-group edges.
2. Permit runner security group → worker TCP 5000 and 9222 only.
3. Permit worker security group → Squid TCP 3128 only; restrict Squid administration separately.
4. Give Squid the controlled public path through one EIP or a managed NAT gateway.
5. Permit runners to model endpoints and TOS through private endpoints where available.
6. Persist every completed trajectory before acknowledging the queue item and deleting its VM.
7. Enforce per-account VM, disk, API, subnet-IP, proxy-bandwidth, and model-QPS quotas.

An explicit proxy baseline inside a worker can use:

```dotenv
HTTP_PROXY=http://squid.service.private:3128
HTTPS_PROXY=http://squid.service.private:3128
NO_PROXY=127.0.0.1,localhost,.service.private
```

Configure equivalent lowercase variables when required by guest applications. Chromium and
desktop applications may require system or application-specific proxy policy; environment
variables alone do not guarantee that GUI traffic uses Squid. Validate benchmark setup and
evaluation traffic before scaling.

A minimal Squid policy should allow TCP 3128 only from the worker security group/private CIDR,
restrict CONNECT to approved ports, use a destination allowlist where the workload permits it,
redact sensitive URL data from exported logs, and end with `http_access deny all`. For higher
availability, deploy at least two gateways behind an internal TCP load balancer and test failure
behavior before running long rollout jobs.

### Scaling the runner layer

Keep one task per disposable VM and use the existing deterministic sharding interface across
runner hosts:

```bash
gadecua batch --env osworldv1 \
  --manifest "$OSWORLD_ROOT/evaluation_examples/test_nogdrive.json" \
  --shard-index 0 --num-shards 8 --workers 4 \
  --resume --infra-retries 2 --evaluate \
  --output-dir results/rollouts/shard-00
```

Run shard indices `0..7` from separate supervised runners. Size `--workers` from the lowest
effective limit among subnet addresses, ECS instances, disks, model QPS, proxy throughput, and
budget. A production queue should use task IDs as idempotency keys and distinguish task failure
from infrastructure failure, matching the batch runner's retry semantics.

## 8. Configure GADE CUA Evolve

Copy `.env.example` to `.env` and fill in the placeholders:

```dotenv
GEMINI_AK=...
GEMINI_MODEL=gemini-3.5-flash-lite

VOLCENGINE_ACCESS_KEY_ID=...
VOLCENGINE_SECRET_ACCESS_KEY=...
VOLCENGINE_REGION=...
VOLCENGINE_ZONE_ID=...
VOLCENGINE_IMAGE_ID=...
VOLCENGINE_INSTANCE_TYPE=...
VOLCENGINE_SUBNET_ID=...
VOLCENGINE_SECURITY_GROUP_ID=...
VOLCENGINE_DEFAULT_PASSWORD=...
```

`VOLCENGINE_DEFAULT_PASSWORD` is resolved only at runtime and is passed consistently to
OSWorld, the Planner, and the Coder redactor. It must not be placed in YAML or committed.

## 9. Smoke-test and clean up

The probe allocates an instance, captures a screenshot, runs harmless Python and Bash inside
the guest, and deletes the instance in a `finally` block:

```bash
gade-cua env probe \
  --config configs/volcengine_gta15_gemini.yaml \
  --check-code --check-services \
  --output probe.png
```

Then run one short benchmark task:

```bash
gadecua --env osworldv1 \
  --task chrome/2ae9ba84-3a0d-4d4c-8338-3a1478dc5fe3 \
  --set loop.max_steps=3 --verbose
```

After every interrupted or failed run, verify in the Volcengine console that temporary ECS
instances and EIPs were deleted. Preserve the custom image and its backing snapshot, but remove
the temporary provisioning instance and the private TOS object when they are no longer needed.

## Reproduction record

For each published experiment, record the GADE CUA Evolve commit, pinned OSWorld commit, image
source revision and checksum, final private Volcengine image ID, region, instance type, model IDs,
task manifest, configuration overrides, and whether ARM/Coder were enabled. Never include secret
values in that record.
