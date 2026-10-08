# Stream C — External research: how other systems actually run many concurrent interactive sessions

**Stream:** C (external research) of the from-scratch harness redesign.
**Written:** 2026-09-18 UTC (author's local session date 2026-09-17).
**Discipline:** this stream writes exactly one file and changes no machine state. No code was run
against any service; every external claim below was read from the vendor's own documentation, the
project's own source/docs tree, or a peer-reviewed paper on the date cited, and the read date is
recorded with each source in §12.

**This document is raw material and verdicts. It deliberately does not design anything** — no
topology, no schema, no interface, no sequencing. That is stream D's job. Where I say a mechanism
"transfers", I mean *the mechanism is available here*, not *adopt it*.

---

## 0. The problem, stated precisely, and the envelope that decides every verdict

One person, four machines on a private network, and a need to run **dozens of concurrent AI agent
sessions**, each with a browser-based UI, interactively, fast and cheap, with agents movable to
whichever machine is least loaded. Today: one browser window per session with its own browser
profile; one engine process per machine; work pushed to other machines by a bespoke broker; and the
machine the person is sitting at becomes the bottleneck.

The envelope, with the measured numbers this research was given or found in the repo (all quoted from
`docs/multi-window/*` and `docs/mesh/*`, read 2026-09-18):

| Fact | Value | Source in this repo |
|---|---|---|
| Machines | Windows laptop (22 logical CPU / 31.6 GB), Windows desktop i9/64 GB, Linux server (4 vCPU), macOS mini | `docs/mesh/10-inventory.md`, `docs/multi-window/PERFORMANCE-MEASURED.md` |
| Network | home and office are separate networks; Tailscale is the only path | session brief; `docs/mesh/*` |
| Users | one owner, plus one employee on the mac mini | `docs/mesh/74-mac-mini.md`, `76-broker.md` §7.2 |
| Engine cost | ~196 MB idle; **~1.4 GB with its five stdio MCP bridges** (26 processes) | `docs/multi-window/ANALYSIS-AND-DECISION.md` §2 |
| Window cost | **~892 MB private per window** with its own browser profile; **~60-296 MB marginal** when the profile is shared | `docs/multi-window/MEMORY-AND-SESSION-LIST.md` §1 |
| Load shape | 10 windows whose agents are *all running* ≈ 7 of 22 cores; commit 28.6-28.8 of 31.61 GB | `docs/multi-window/PERFORMANCE-MEASURED.md` (2026-09-14) |
| Session list | `session/list` = **25.4 / 25.1 / 31.4 s** for 679-685 rows, 1.46 MB | `docs/multi-window/MEMORY-AND-SESSION-LIST.md` §2 |
| One writer | two `dsh web` on one `DSH_HOME` corrupt the session log → one writer process per home | `docs/multi-window/PERFORMANCE-MEASURED.md` |
| Broker | in-memory lease table, TTL 900 s, five tiers, "never refuses a placement" | `docs/mesh/76-broker.md` §2, `packages/mesh-broker/lib/*.js` |
| Governor | budget derived from free memory, ~160 MB per in-flight call, clamped 4-24, queues and never refuses | session brief; `docs/dsh-at-scale/90-plugin-health-governor.md` |

Five properties of this environment decide nearly every "transfers?" verdict below, and it is worth
naming them once rather than repeating them forty times:

- **W single user.** Multi-tenancy, per-user isolation, authentication boundaries and quota-per-tenant
  are not requirements. Anything whose value is *isolation between users* does not transfer, no matter
  how well engineered it is. (This is a large fraction of Kubernetes-adjacent literature.)
- **N no cluster operating system.** No containers, no k8s, no Nomad, no Slurm, no cgroups-on-Windows.
  A mechanism that assumes a scheduler can `bind` a pod and a kubelet can enforce limits transfers
  only as an *idea about arithmetic and ordering*, never as software.
- **Wn Windows-first client.** The UI is Chromium/Edge on Windows. Linux-only mechanisms (tmux, mosh,
  systemd, Firecracker) are not available on the machine where the person sits; where the *idea*
  matters, it must be re-expressed (WebView2, Job Objects, Task Scheduler) or placed on the Linux box.
- **S split network.** Home and office are joined only by Tailscale. Any design that assumes a single
  LAN with low, uniform latency is wrong here; both a 25 s SSH probe and a 7.3 s broker capacity read
  were measured across this split (`docs/mesh/106-desktop-last-mile.md`, `76-broker.md` §10.5).
- **B personal budget.** Per-hour control planes, per-workspace VMs and managed schedulers are
  excluded by cost, not by capability. The measured provider spend in `docs/mesh/65-spend-guard.md`
  ($11.68 for 79 sessions) is the order of magnitude that must be preserved.

---

## How to read each entry

Every system below is recorded as four lines, and I have tried not to let the interesting engineering
substitute for the verdict:

- **Mechanism** — the transferable idea, named as a pattern, not as a product.
- **Cost model** — what the vendor or paper publishes, quoted, if anything.
- **Assumes** — the infrastructure the mechanism silently requires.
- **Verdict** — *transfers* / *transfers in part* / *does not transfer*, with the reason.

---

## 1. Remote and cloud development environments

This whole category exists to solve a version of the house problem: the developer's own machine must
not be where the work runs, and N environments must be addressable at once.

### 1.1 VS Code Remote-SSH, Tunnels, and the VS Code Server

**Mechanism.** Split the editor from the workspace by *role*, not by location. Extensions are declared
as **UI extensions** (run in the local extension host) or **Workspace extensions** (run in a **Remote
Extension Host** inside a small *VS Code Server* on the remote machine), and VS Code picks per
extension ([Supporting Remote Development and GitHub Codespaces](https://code.visualstudio.com/api/advanced-topics/remote-extensions),
read 2026-09-18). Remote-SSH requires only that the local machine can reach `update.code.visualstudio.com`
and `vscode.download.prss.microsoft.com` over outbound HTTPS 443, and the server is installed on the
remote host ([Remote Development using SSH](https://code.visualstudio.com/docs/remote/ssh), read
2026-09-18). Tunnels remove the SSH requirement entirely by dialling **out** through Microsoft dev
tunnels: "Tunneling securely transmits data from one network to another via Microsoft dev tunnels",
and the client needs no inbound path to the remote
([Developing with Remote Tunnels](https://code.visualstudio.com/docs/remote/tunnels), read 2026-09-18).

**Cost model.** Not published. The relevant published *constraint* is licensing and single-user
design, and it is unusually blunt: *"Is the VS Code Server designed for multiple users to access the
same remote instance? **No**, an instance of the server is designed to be accessed by a single user.
Can I host the VS Code Server as a service? **No**, hosting it as a service is not allowed, as
specified in the VS Code Server license."*
([Visual Studio Code Server](https://code.visualstudio.com/docs/remote/vscode-server), read 2026-09-18).

**Assumes.** A remote Unix-ish host (glibc-based; kernel ≥ 3.10, glibc ≥ 2.17, libstdc++ ≥ 3.4.18 —
[Remote SSH prerequisites](https://code.visualstudio.com/docs/remote/ssh)), a local GUI, and — for
Tunnels — a willingness to route through Microsoft's relay.

**Verdict: transfers in part, and one part of it is a warning rather than a model.**
The transferable idea is **role-split, not location-split**: decide per component whether it must run
near the data or near the human, and let the transport be independent of that choice. The Tunnels
mechanism (outbound-only dialling from the remote, no inbound ports) is directly relevant to the
home/office split, and is exactly what Tailscale already provides here. What does **not** transfer is
VS Code's session model: **Microsoft's own server is single-user and forbids running it as a service.**
This is worth saying plainly because the house architecture is *ahead* of VS Code on this axis: one
engine hosting many concurrent sessions, kept running by a supervisor, is precisely the thing the VS
Code Server license forbids. Do not cite VS Code as the mature answer to N concurrent sessions; it
declines to answer.

### 1.2 GitHub Codespaces

**Mechanism.** One isolated environment per unit of work, addressed by URL, with the environment —
not the client — holding the heavy process. *"Each codespace you create is hosted by GitHub in a
**Docker container, running on a virtual machine**"*, selectable from 2 cores / 8 GB / 32 GB up to
32 cores / 128 GB / 128 GB ([What are GitHub Codespaces?](https://docs.github.com/en/codespaces/overview),
read 2026-09-18). Ports are forwarded and become *URLs* — private to you, private to an org, or public
([Forwarding ports in your codespace](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace),
read 2026-09-18), and a port forwarded through the desktop client also appears as `127.0.0.1:4000`.

**Cost model.** Not published as a latency model; it is priced per core-hour with storage, and every
codespace is a whole VM-backed container. The published lifecycle facts are the interesting ones:
containers are stopped on idle and the whole environment is reconstructible from configuration-as-code
("dev container"), which is what makes N of them affordable at all.

**Assumes.** A cloud hypervisor fleet, per-codespace VM provisioning, a global relay for port URLs,
and per-user authentication. Also, in practice, a per-codespace cold start.

**Verdict: mechanism transfers, implementation does not.** The two transferable pieces are
**(a) one addressable environment per unit of work** — the URL *is* the handle, so reopening a session
is a navigation, not a click-through of a sidebar — and **(b) the client holds nothing but the UI**.
What does not transfer is the per-environment VM: 32 cores per environment, priced per hour, for a
single person with a $12-a-month appetite, is the opposite of correct. The house already has the right
substitute (a process tree, not a VM) and should read Codespaces for *addressing and lifecycle*, not
for isolation.

### 1.3 Coder

**Mechanism.** Separate **control plane** from **data plane**, and never let the control plane carry
payload. `coderd` is *"a thin API that connects workspaces, provisioners and users… stores its state
in Postgres and is the only service that communicates with Postgres"*, offering the dashboard, the
HTTP API, **Dev URLs (an HTTP reverse proxy to workspaces)**, workspace web applications, and agent
registration ([Coder architecture](https://coder.com/docs/admin/infrastructure/architecture), read
2026-09-18). At scale you add **workspace proxies**: *"A workspace proxy is a relay connection a
developer can choose to use when connecting with their workspace over SSH, a workspace app, port
forwarding, etc."* — and, importantly, *"Dashboard connections and API calls (e.g. the workspaces
list) are not served over workspace proxies"*
([Workspace Proxies](https://coder.com/docs/admin/networking/workspace-proxies), read 2026-09-18).

**Cost model.** Not published; the architectural claim is the point — the control plane is thin and
Postgres is the single writer, so the control plane can restart without killing any workspace.

**Assumes.** Kubernetes, Terraform provisioning, Postgres, and often a reverse proxy/ingress that
supports WebSockets.

**Verdict: the *separation* transfers and is the single most useful idea in this section; the
*deployment* does not.** Coder's design says: the thing that decides and the thing that carries
bytes are different processes, the thing that owns durable state is a database with one writer, and
the sessions keep running when the control plane restarts. That maps onto this environment without
any of Coder's machinery, and it is the property the house most lacks (today, restarting the engine
is restarting the sessions' owner). Kubernetes/Terraform/Postgres-as-a-cluster do not transfer; a
single writer plus in-memory reservations is the honest scale here.

### 1.4 Gitpod / Ona

**Mechanism. Ephemeral workspaces with an explicit persistence boundary.** *"Workspaces are ephemeral
by design, which means they are temporary and designed to be disposable. When a Workspace is stopped,
content on `/workspace` directory gets backed up and the contents are removed. When you restart a
workspace, the content of `/workspace` is restored to a new ephemeral container."*
([Workspace Lifecycle](https://ona.com/docs/classic/user/configure/workspaces/workspace-lifecycle),
read 2026-09-18).

**Cost model.** Not published here; the historic Gitpod claim was prebuild-driven instant start
(prebuilds per branch), which I did **not** verify from current documentation (§11).

**Assumes.** Kubernetes, an image registry, and a durable volume/backup service.

**Verdict: transfers as a *rule about what must survive*, not as ephemerality.** The rule —
**name the tiny set of paths that must survive and let everything else be disposable** — is exactly
the right frame for sessions, worktrees and agent scratch space, all of which currently mix durable and
disposable state in one tree. Literal ephemerality does **not** transfer: an interactive session with a
human mid-conversation is a bad thing to garbage-collect, and the house's whole complaint is that
sessions are already too easy to lose.

### 1.5 Eclipse Che

**Mechanism. Declare the environment as a document (devfile), run it as a custom resource, and give
every workspace a URL.** Che is *"three groups of components"*: server/dashboard, the **DevWorkspace
Operator** which *"creates and controls the necessary Kubernetes objects to run User workspaces,
including Pods, Services, and PersistentVolumes"*, and the workspaces themselves
([Che architecture](https://www.eclipse.org/che/docs/stable/discover/architecture-overview), read
2026-09-18).

**Cost model.** Not published.

**Assumes.** Kubernetes/OpenShift, an operator, Keycloak or similar for auth.

**Verdict: does not transfer; the *idea* of a declarative environment document is already present in
this repo** (`multi-window/windows.json`, `nodes.json`, `windows.json` roster files are the same shape).
Che adds nothing for a single user on Windows except evidence that "workspace = document + operator +
URL" is the industry's convergent shape.

### 1.6 What this category actually decided

| Decision | Seen in | Transfers here |
|---|---|---|
| The heavy process lives on the remote host; the client is a view | all five | **yes**, already true (engine owns sessions) |
| One addressable handle per environment (URL) | Codespaces, Coder Dev URLs, Che | **yes**, and this is the house's biggest gap |
| Control plane ≠ data plane; payload never crosses the decider | Coder (explicitly) | **yes**, as a rule |
| Durable state in a single-writer store, so the control plane can restart | Coder, JupyterHub | **yes**, as a rule |
| Per-environment container/VM for isolation | Codespaces, Gitpod, Che | **no** — single user, personal budget |
| Declarative environment document | Che, devcontainers, Gitpod | **already the house pattern** |
| One server per user, single-tenant by design/licence | VS Code Server (explicitly) | **no** — the house needs N sessions in one engine |

---

## 2. Notebook and interactive-compute servers

This is the closest published prior art to the actual problem: many interactive sessions, one machine
or a few, a human who wants to reopen exactly the one he left, and a server that must not die because
a browser closed.

### 2.1 Jupyter Server — one process, N kernels

**Mechanism.** The server owns **kernels as separate child processes** and multiplexes them over
WebSocket: *"The Jupyter Server needs to pass messages between kernels and the Jupyter web application.
Kernels use ZeroMQ sockets, and the web application uses a WebSocket"*
([WebSocket kernel wire protocols](https://jupyter-server.readthedocs.io/en/latest/developers/websocket-protocols.html),
read 2026-09-18). The server itself is *"the main Tornado-based application which connects all
components together"* with a config manager and pluggable managers
([Architecture Diagrams](https://jupyter-server.readthedocs.io/en/latest/developers/architecture.html),
read 2026-09-18).

**Cost model.** Not published. The structural claim is what matters: **one connection-multiplexing
front-end process, N executing processes** — the kernel processes are where the CPU and memory go, and
they are individually killable.

**Assumes.** A single Unix-ish host; a browser.

**Verdict: transfers, and it is already the house's shape.** Jupyter Server is the same architecture as
`dsh web`: one server, N independent execution contexts, one WebSocket-ish channel per client, kernels
(= agents) as killable units. Two lessons the house has not applied:
**(a) the front-end process holds no execution state** — killing a kernel never disturbs the server;
**(b) kernels are individually addressable and individually cullable** — Jupyter's `MappingKernelManager`
exposes `cull_idle_timeout` / `cull_interval` (documented for the sibling Enterprise Gateway as
`--RemoteKernelManager.cull_idle_timeout`, *default 0, recommended 43200 s*, with `cull_interval`
defaulting to 300 s — [Culling idle kernels](https://jupyter-enterprise-gateway.readthedocs.io/en/latest/operators/config-culling.html),
read 2026-09-18).

### 2.2 JupyterHub — proxy + Hub + Spawner + named servers + culler

**Mechanism.** This is the single most relevant system in this document. Four parts
([Technical Overview](https://jupyterhub.readthedocs.io/en/latest/reference/technical-overview.html),
read 2026-09-18):

- **Proxy** — *"the public-facing part of JupyterHub that uses a dynamic proxy to route HTTP requests
  to the Hub and Single User Notebook Servers"* (default: configurable-http-proxy, a Node process).
- **Hub** — manages accounts/authn and *coordinates* single-user servers using a Spawner.
- **Spawner** — the abstraction over *where a server runs*: a Spawner *"represents an abstract
  interface to a process"* and must be able to **start, poll and stop** a process; implementations
  range from local processes to Docker/Kubernetes
  ([Spawners](https://jupyterhub.readthedocs.io/en/latest/reference/spawners.html), read 2026-09-18).
- **Single-user server** — started *per user on demand*.

Three further mechanisms matter more than the components:

1. **Named servers — N sessions per person, addressable.** *"By default… each user has exactly one
   server. JupyterHub can, however, have multiple servers per user"*, enabled with
   `c.JupyterHub.allow_named_servers = True`, with a per-user cap
   (`named_server_limit_per_user`), and each server reachable at its own `/user/<name>/<server>` path,
   managed from a user home page
   ([Configuring user environments](https://jupyterhub.readthedocs.io/en/latest/reference/config-user-env.html),
   read 2026-09-18).
2. **Idle culling as a first-class service, driven by the server and the proxy.** The culler *"collects
   information and acts entirely through JupyterHub's REST API"* and decides using *"activity reports
   from the user servers"* plus *"the proxy class for information about user servers' network
   activity"* ([jupyterhub-idle-culler](https://github.com/jupyterhub/jupyterhub-idle-culler), read
   2026-09-18).
3. **The proxy is a separate process from the Hub**, so the front door and the session owner have
   independent lifetimes.

**Cost model.** Not published. Costs are per-spawned-server and are entirely a function of the
Spawner (a local process is ~nothing; a k8s pod is a pod).

**Assumes.** For the plain path: nothing but Python and a Unix host (`SimpleLocalProcessSpawner`
spawns as the same user, i.e. **no isolation at all** — the documented default in a single-user
deployment). Isolation (Docker/k8s/systemd) is optional and pluggable.

**Verdict: transfers — and this is the strongest single comparison in this document.** JupyterHub is a
*documented, maintained* implementation of: a launcher registry, a front-door proxy, per-session
addresses, a spawner abstraction over "where does this run", on-demand start, and an idle culler
driven by observed activity. The house has built every one of those pieces by hand. See §10 item 1.

### 2.3 Binder

**Mechanism.** BinderHub = *build a container from a repo, then launch a per-user JupyterHub for it*.
Relevant only as evidence that "the environment is derived from a source of truth, not hand-made".

**Assumes.** Kubernetes + a registry + a build farm.

**Verdict: does not transfer.** No containers here; and the house's sessions do not need image builds.

### 2.4 SageMaker Studio and Databricks

**Mechanism (SageMaker).** Per-user **applications** (JupyterLab, Code Editor), with **idle shutdown
configured per application type independently**, at domain or user-profile level, where *"User profile
settings override domain settings"*
([Idle shutdown](https://docs.aws.amazon.com/sagemaker/latest/dg/studio-updated-idle-shutdown.html),
read 2026-09-18). A minimum idle timeout of **60 minutes** is reported in an AWS re:Post answer
([re:Post](https://repost.aws/questions/QUM-2l5LfNQXqHcYAZKWQMVg/question-about-shortening-auto-termination-time-in-sagemaker-studio),
read 2026-09-18 — *secondary source, not vendor documentation; I could not fetch a vendor page stating
the minimum*).

**Mechanism (Databricks).** Compute is a *cluster* that notebooks attach to, with autoscaling and
auto-termination on idle; I could not load the vendor page for it (§11), so I state nothing numeric
about it here.

**Verdict: the *policy shape* transfers — a per-application-class idle policy with a user-level
override — the platform does not.** The transferable rule: **idle policy must be per class of work and
overridable at the narrower scope**, because a running agent and an idle conversation window have
wildly different "idle" meanings, and one global timeout will be wrong for both. The published
one-hour floor is a reminder that idle culling on managed platforms is coarse; here, where the owner is
the only user, a much tighter policy is possible and the failure mode of a wrong cull (losing a
conversation) is worse than the cost of a warm process.

---

## 3. Job scheduling and admission control on a small cluster

### 3.1 Kubernetes: requests/limits, QoS, eviction, and binding

**Mechanism — four separable ideas.**

1. **Requests vs limits.** *"When you specify the resource request for containers in a Pod, the
   kube-scheduler uses this information to decide which node to place the Pod on. When you specify a
   resource limit for a container, the kubelet enforces those limits so that the running container is
   not allowed to use more of that resource than the limit you set. The kubelet also reserves at least
   the request amount of that system resource specifically for that container"*
   ([Resource Management for Pods and Containers](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/),
   read 2026-09-18). **Two numbers: one for deciding, one for enforcement.**
2. **QoS classes as eviction order.** Every pod is `Guaranteed`, `Burstable` or `BestEffort`; *"When a
   Node runs out of resources, Kubernetes will first evict BestEffort Pods…, followed by Burstable and
   finally Guaranteed"*, and *"only Pods exceeding resource requests are candidates for eviction"*
   ([Pod Quality of Service Classes](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos), read
   2026-09-18). Eviction thresholds are `[eviction-signal][operator][quantity]`, with soft and hard
   variants ([Node-pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/),
   read 2026-09-18).
3. **Scheduler cycle: feasibility, scoring, binding.** *"The scheduler finds feasible Nodes for a Pod
   and then runs a set of functions to score the feasible Nodes and picks a Node with the highest score
   among the feasible ones… The scheduler then notifies the API server about this decision in a process
   called binding."* If nothing fits, *"the pod remains unscheduled until the scheduler is able to place
   it"* ([Kubernetes Scheduler](https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/),
   read 2026-09-18). **The scheduler is the single writer of the decision, and binding precedes start.**
4. **Two-level placement is optional and deliberate** — Kubernetes **does not gang-schedule by
   default**; all-or-nothing is a separate feature (Kueue, Volcano, Ray placement groups — see §3.2 and
   §3.5). The scoring plugin's default is least-allocated rather than bin-packing; that is widely
   documented but **I did not verify it from a Kubernetes page in this pass** (§11).

**Cost model.** Requests are accounting units, not reservations of physical memory; the scheduler's
decision quality is bounded by the freshness of its view of each node's allocated requests. There is
no published "per-session overhead"; the relevant published *behaviour* is that a pod that does not fit
sits Pending indefinitely, consuming nothing, and is retried.

**Assumes.** etcd, an apiserver, kubelet and cgroups on every node, and a CNI.

**Verdict: the *arithmetic and the ordering* transfer; the platform does not.**
The three transferable pieces are: **(a) decide on a request, enforce on a separate number** (the house
has one number, ~160 MB per in-flight call, doing both jobs); **(b) an explicit, ordered eviction
policy** — the house's governor admits and queues but never *preempts or downgrades* running work, so
the first thing to suffer under pressure is whatever the OS happens to trim; **(c) decide-then-bind
before starting**, which the broker already does correctly (`broker.js`: *"Choose a node and issue its
lease. Synchronous on purpose: the decision and the reservation cannot interleave"*). etcd/kubelet/
cgroups/CNI do not transfer; a `Map` with TTLs is the honest scale here, provided it is not silently
ephemeral.

### 3.2 Kueue: quota reservation *before* admission

**Mechanism.** A separate admission layer in front of the scheduler, with two distinct phases:
**QuotaReservation**, where *"the kueue scheduler locks the resources needed by a workload within the
targeted ClusterQueues ResourceGroups"*, then **Admission**, which *"is the process of allowing a
Workload to start (Pods to be created)"*; a workload is admitted when it holds a quota reservation and
its admission checks are Ready. When quota is short, *"an incoming Workload can trigger preemption of
previously admitted Workloads, based on"* the ClusterQueue's policy
([Kueue concepts](https://kueue.sigs.k8s.io/docs/concepts), read 2026-09-18;
[Cluster Queue](https://kueue.sigs.k8s.io/docs/concepts/cluster_queue), read 2026-09-18).

**Cost model.** Not published. The design claim is that quota accounting is a *separate, cheap
bookkeeping layer* whose state must be authoritative, which is why it lives in an API object with a
single writer.

**Assumes.** Kubernetes + CRDs.

**Verdict: the *phasing* transfers and is the cleanest published statement of what the house's
governor-plus-broker is trying to do.** Reservation and admission are different steps, reservation is
the scarce resource, and it is held by an object with a single writer. The house does this correctly in
the broker for *placement* (leases with TTL) and in the governor for *in-flight tool calls* (a budget),
but the two are separate systems with separate state and neither survives a restart. Kubernetes does
not transfer; the two-phase wording should be stolen verbatim.

### 3.3 Nomad

**Mechanism.** A single-binary scheduler with an **evaluation broker** and a **binpack-default**
placement strategy. The scheduler *"iterates over nodes until it finds a small number of feasible
nodes. The scheduler then scores those feasible nodes to find the best placement"*, and by default
uses bin-packing *"to optimize the resource utilization and density of applications"*, with a `spread`
block to override that per job
([Advanced job scheduling](https://developer.hashicorp.com/nomad/docs/job-scheduling), read 2026-09-18).
Nomad's servers *"run scheduler workers that process evaluations from the leader server, which runs the
evaluation broker"* ([Nomad for Kubernetes practitioners](https://github.com/hashicorp/web-unified-docs/blob/main/content/nomad/v2.0.x/content/docs/k8s-nomad/index.mdx),
read 2026-09-18).

**Cost model.** Nomad's own marketing figure is "10k+ nodes" (secondary), irrelevant here. The
published *mechanism* cost is the cheap one: **iterate until you have a handful of candidates, then
score only those** — placement cost is O(feasible subset), not O(mesh).

**Assumes.** Server agents with Raft + gossip, client agents on every node.

**Verdict: transfers as a *default and a bound*.** Two ideas: **(a) default to packing, not spreading**,
with an explicit per-job override to spread — the house currently spreads purely by free slots, which
on 2-6 heterogeneous machines produces the "laptop is the bottleneck" behaviour from the other side
(the desktop stays idle when the laptop has marginally more free slots and the ranking is stale); and
**(b) cap the candidate set before scoring** — with 4 nodes this is trivial, but the habit matters when
the mesh includes cloud. Nomad itself (Raft, gossip, agents) does not transfer; the house's roster file
plus an HTTP read is the honest equivalent.

### 3.4 Slurm: backfill, atomic allocation, and the real meaning of "gang scheduling"

**Mechanism.** The **backfill scheduler** is loaded by default: *"Without backfill scheduling, each
partition is scheduled strictly in priority order, which typically results in significantly lower system
utilization and responsiveness… Backfill scheduling will start lower priority jobs if doing so does not
delay the expected start time of any higher priority jobs"*, with a default `sched_interval` of 60 s
([Scheduling Configuration Guide](https://slurm.schedmd.com/sched_config.html), read 2026-09-18).

**Honest correction.** Slurm's own "gang scheduling" page is **not** about all-or-nothing allocation. It
describes **timesliced** gang scheduling: *"two or more jobs are allocated to the same resources in the
same partition and these jobs are alternately suspended to let one job at a time have dedicated access
to the resources for a configured period"*
([Gang Scheduling](https://slurm.schedmd.com/gang_scheduling.html), read 2026-09-18). All-or-nothing in
HPC is a consequence of *atomic allocation* — a job requesting N nodes is allocated all N or waits —
which I state here as widely-known behaviour that this page does not itself assert; **I did not verify
it from a Slurm page** (§11).

**Cost model.** Backfill's cost is a reservation table: to start a small job early safely, the scheduler
must know when the resources will be free for the big job — i.e. **the queue must project ahead, not
just measure now.**

**Assumes.** A central scheduler, a queue, and node-level resource accounting.

**Verdict: the *policy* transfers; nothing else does.** The transferable insight is the one the house
most needs: **a scheduler that only ranks by current free capacity will either waste capacity or
queue forever; a scheduler that knows what is already committed and when it will end can fill the gap.**
The house's broker ranks on a *measurement* with a ≤15 s TTL and has no notion of "this node is
committed until T+40 min". Slurm's reservation table is the mechanism; a Map of leases with expected
end times is the honest scale. Slurm's daemons, partitions and QoS machinery do not transfer.

### 3.5 Ray: bottom-up scheduling, spillback, and placement groups

**Mechanism.** Two levels, with **local-first submission and spillback**:

- *"Bottom-up distributed scheduler. Tasks are submitted bottom-up, from drivers and workers to a local
  scheduler and forwarded to the global scheduler only if needed (Section 4.2.2). The thickness of each
  arrow is proportional to its request rate. The global scheduler considers each node's load and task's
  constraints to make scheduling decisions."* — Figure 6, with a Global Control Store holding state
  ([Ray: A Distributed Framework for Emerging AI Applications](https://www.usenix.org/system/files/osdi18-moritz.pdf),
  OSDI'18, read 2026-09-18).
- **Placement groups = gang scheduling, published as such:** they *"allow users to atomically reserve
  groups of resources across multiple nodes, a concept commonly known as gang scheduling"*, with PACK
  and SPREAD strategies
  ([Ray placement groups, source](https://raw.githubusercontent.com/ray-project/ray/master/doc/source/ray-core/scheduling/placement-group.rst),
  read 2026-09-18).

**Cost model.** Not published as a per-node overhead; the load argument is structural — **the global
scheduler sees only the requests that the local scheduler could not satisfy**, which is what keeps it
from being the bottleneck as the node count grows.

**Assumes.** A GCS (a replicated key-value store), a node manager per host, and an object store.

**Verdict: transfers, and it is the best available answer to "the machine he sits at is the
bottleneck".**
Two mechanisms: **(a) try locally, then spill** — a session's child work should be attempted on the
node that owns the session, and only pushed when the local budget is exhausted. The house does the
opposite: the broker is consulted *first*, so the *decision plane* is on the critical path of every
unit of work, across a Tailscale link where a capacity read was measured at **7342 ms**
(`docs/mesh/76-broker.md` §10.5). **(b) Gang admission is a named requirement** — a 12-child fleet must
reserve all 12 or none; the broker's own docs already flag that *"placements cannot each boot an
instance"*, and Ray's placement groups are the published statement of the fix. The GCS and the object
store are unnecessary here; a per-node budget file plus a lease table is the honest scale.

### 3.6 The opposite pattern: work stealing, and the reliable queue

**Work stealing.** The canonical mechanism (Blumofe & Leiserson, *Scheduling Multithreaded Computations
by Work Stealing*, JACM 1999 — [DOI](https://dl.acm.org/doi/10.1145/324133.324234), and the paper text
at [perso.ens-lyon.fr](https://perso.ens-lyon.fr/loris.marchal/docs-data-aware/papers/scheduling-multithreaded-comp-WS.pdf),
read 2026-09-18): every worker owns a **deque**, the owner pushes and pops at one end in **LIFO** order
(for locality), and an idle worker **steals from the other end in FIFO order**, choosing a **random
victim** (to avoid contention on a single hot queue). The theoretical result is near-optimal makespan
with bounded communication — the scheduler does no global bookkeeping and *no worker ever asks a
central authority where to run something*. The LIFO-owner/FIFO-thief/random-victim design is described
in the OSDI'23 work-stealing paper ([BWoS](https://www.usenix.org/system/files/osdi23-wang-jiawei.pdf),
read 2026-09-18) and in current literature; I confirmed the deque disciplines from those secondary
descriptions rather than from the 1999 text itself (§11).

**The reliable queue.** The minimal durable version of the same idea: a single shared list where a
consumer atomically *takes* a job and *pushes it onto a processing list* in one step, so a crash cannot
lose it — *"the consumer fetches the message and at the same time pushes it into a processing list"*
([Redis RPOPLPUSH](https://redis.io/docs/latest/commands/rpoplpush/), read 2026-09-18). The same
semantics at scale are SQS's **visibility timeout**: *"The visibility timeout starts as soon as a
message is delivered to you… If you don't delete it before the timeout expires, the message becomes
visible again in the queue and can be retrieved by another consumer. The default visibility timeout for
a queue is 30 seconds"*, and delivery is explicitly **at-least-once**, so duplicates are possible
([SQS visibility timeout](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html),
read 2026-09-18).

**Verdict: the *pull* pattern transfers and should be the default; stealing itself does not.**
With 2-6 heterogeneous machines the interesting quantity is not "which node is least loaded" (a
measurement that crosses a slow link and is stale on arrival) but "which node has a free slot right
now" (a fact the node itself knows perfectly). **A worker that advertises its own capacity and pulls
work needs no scheduler at all**, and it removes the measured failure mode where four concurrent
placements are ranked off the same ≤15 s-old reading. Work *stealing* between machines is unnecessary
complexity at this scale; work *pulling* is the honest minimum. The lease/visibility-timeout semantics
transfer exactly, and they are what makes pull safe: work is never lost when a worker dies mid-unit.

### 3.7 Minimum viable scheduler for 2-6 heterogeneous machines — the synthesis

Everything above, reduced to what actually transfers, in order of necessity:

| Need | Mechanism | Published source | Cost |
|---|---|---|---|
| Do not lose work when a node dies | lease with TTL that returns the work (SQS visibility timeout; broker leases) | SQS; `mesh-broker/lib/leases.js` | one Map + a clock |
| Do not oversubscribe a node | capacity advertised **by the node**, in slots, from its own free memory | K8s requests/kubelet; Kueue quota | one number per node |
| Decide cheaply, and off the critical path | try local first, spill to a global decider only when overloaded | Ray (OSDI'18 Fig. 6) | a local budget |
| Race-free placement | decide and reserve in one synchronous step; bind before start | K8s binding; `broker.js` | one critical section |
| Fill gaps | rank on committed-until as well as free-now | Slurm backfill | expected end time per lease |
| All-or-nothing for a fleet | gang admission: reserve N slots or queue | Ray placement groups; Kueue preemption | children count in the request |
| Do not queue forever, do not starve | a queue position, and preemption/eviction order | Kueue; K8s QoS | an ordering rule |
| Keep the decider disposable | reservations durable enough to survive the decider's restart | Coder (Postgres as single writer) | a file or a row |

**Verdict: the minimum viable scheduler here is a lease table plus node-advertised slots plus gang
admission — and it is already ~80 % built.** The missing 20 %, in the order I would rank it, is
(a) **durability of reservations** (today the broker's leases are an in-memory `Map`, so a broker
restart forgets every commitment — `76-broker.md` §8 lists "behaviour under a broker restart
mid-flight" as explicitly unverified), (b) **gang admission**, and (c) **committed-until ranking**.
Kubernetes, Nomad, Slurm and Ray all fail the environment test; their *arithmetic and ordering* pass it.

---

## 4. Terminal/session multiplexing and durability

This section answers a narrower but decisive question: **what does it take for a session to be alive
independently of whatever is displaying it?**

### 4.1 tmux

**Mechanism.** Split the *server* that owns the pty from the *client* that draws it: *"In tmux, a
session is displayed on screen by a client and all sessions are managed by a single server. The server
and each client are separate processes which communicate through a socket in /tmp."* Sessions can be
created **detached** (`new-session -d`) and reattached with `tmux attach`; *"tmux may be reattached
using: `$ tmux attach`"*. Control mode (`-C`, `-CC`) exposes the session as a *machine-readable event
stream* rather than an interactive terminal
([tmux(1)](https://man7.org/linux/man-pages/man1/tmux.1.html), read 2026-09-18).

**Cost model.** Not published; effectively one process group per session, with the cost of a terminal,
and the client costs nothing when closed.

**Assumes.** A Unix pty, a socket, and the process outliving the login session (which is why it is
usually wrapped in `systemd-run`/`nohup`).

**Verdict: transfers as the *rule*, and it is the rule the house breaks.**
**The UI must be a client of the session, never the owner of it.** tmux's evidence is that this is
cheap: the session survives the client, a client can be replaced, and control mode shows that the same
session can be *driven by a program* rather than a terminal. Applied here: a window closing must not
change anything about a session's liveness or state, and a session must be able to be *displayed by two
clients at once* (`tmux attach` twice) and moved between displays. tmux itself does not transfer to
Windows (native tmux is not available; WSL would put the session on the wrong side of the boundary),
but the client/server split is exactly what `dsh` already does between the browser and the engine — what
is missing is that **the engine is the session owner and the engine is not movable**.

### 4.2 GNU screen, dtach, abduco

Not researched beyond their existence: they are variations on 4.1 with fewer features. **Not verified**
— I did not fetch their documentation (§11). Their relevance would be to a Linux-only world.

### 4.3 mosh

**Mechanism.** The **State Synchronization Protocol**: synchronise the *object* (the screen), not the
*byte stream*. *"This synchronization is accomplished using a new protocol we call the State
Synchronization Protocol (SSP). SSP runs over UDP, synchronizing the state of an object from one host
to another… Because SSP works at the object layer and can control the rate of synchronization (i.e.
the frame rate), it does not need to send every byte it receives from the application."* It also
supports **roaming** — *"synchronizes client and server state, even across changes"* of client IP —
and **local echo**, which lets the client draw a keystroke before the server has seen it
([Mosh: A State-of-the-Art Good Old-Fashioned Mobile Shell](https://www.usenix.org/system/files/login/articles/winstein.pdf),
read 2026-09-18).

**Published results.** *"Mosh was able to immediately display the effects of 70 % of the user
keystrokes. Over a commercial EV-DO (3G) network, median keystroke response latency with Mosh was less
than 5 ms, compared with 503 ms for SSH."*
([Mosh: An Interactive Remote Shell for Mobile Clients](https://www.usenix.org/conference/atc12/technical-sessions/presentation/winstein),
USENIX ATC'12, read 2026-09-18).

**Assumes.** UDP reachability between the two ends (not available across the home/office split without
a tunnel — Tailscale provides the equivalent), and a terminal.

**Verdict: the *instrumentation* transfers; the transport does not.**
Two things are worth taking. **(a) Synchronise state, not bytes, and cap the rate** — for a UI that
streams agent output to N windows, the natural unit is "current content + delta", and a rate cap is the
answer to a slow or backgrounded client; this is precisely the class of bug the house already has open
(no byte-level backpressure on the WebSocket downlink, `PERFORMANCE-MEASURED.md` §"Still open (PAIN
P16)"). **(b) Local echo of user input, then reconciliation** — the reason a UI feels instant even
when the far end is 500 ms away, which on a Tailscale split is the difference between usable and
unusable. Mosh's own dependency (UDP, a pty, a Unix server) does not transfer to Windows; the
mechanism does, in a UI-shaped form.

### 4.4 What this section says about liveness, in one line

**Ownership of the session must live somewhere that is neither the display nor the person's hands** —
and that owner must be restartable without ending the session, or movable between machines. Today in
this environment the owner is one `dsh web` process bound to one `DSH_HOME` on one machine, and the
single-writer constraint (`PERFORMANCE-MEASURED.md`) makes moving it a correctness problem, not a
copy. Every one of Coder's Dev URLs, JupyterHub's proxy-plus-spawner, and tmux's socket is a solution
to that same problem.

---

## 5. Browser UI at scale on one machine

### 5.1 Chromium's process model, and what a "window" actually costs

**Mechanism.** Chromium allocates renderer processes by **site instance**, and *"Chromium aims to use
separate processes for different instances of web sites when possible. A web site instance is a group
of documents or workers that must share a process with each other to support their needs, such as
cross-document scripting."* The stated trade is explicit: *"For stability, putting web site instances in
separate processes limits the impact of a renderer process crash or hang… For performance, this allows
different web site instances to run in parallel with better responsiveness, **at the cost of some
memory overhead for each process**"*
([Process Model and Site Isolation](https://chromium.googlesource.com/chromium/src/+/main/docs/process_model_and_site_isolation.md),
read 2026-09-18). The default is **process-per-site-instance**; the alternatives are
process-per-site (one process for all instances of one site), process-per-connected-tab-group, or a
single process — *"By default, Chromium uses a separate OS process for each instance of a web site the
user visits"* ([Process Models](https://chromium.googlesource.com/playground/chromium-org-site/+/refs/heads/main/developers/design-documents/process-models.md),
read 2026-09-18).

**Published cost.** The best published number is from the academic evaluation that measured Chrome's
own rollout: *"the Chrome team was willing to accept **9-13 % memory overhead** for the security
benefits of enabling Site Isolation"*, and the observed process-count increase (~50 %) produced a
memory increase *"significantly lower than the 50 % increase in process count might suggest"*
([Reis et al., *Process Separation for Web Sites within the Browser*, USENIX Security '19](https://www.usenix.org/system/files/sec19-reis.pdf),
read 2026-09-18).

**Measurement trap.** Chromium's own guidance is that per-process memory must not be summed:
*"The final algorithm for 'Private' size is: Private Working Set + Shareable Working Set − Shared
Working Set"*, and the total is meant to be read from `about:memory`
([Memory Usage Backgrounder](https://www.chromium.org/developers/memory-usage-backgrounder), read
2026-09-18). This independently confirms the method the house already chose on 2026-09-14 (*"memory is
private bytes, because summing WorkingSet across 90 Chromium processes double-counts shared pages"*).

**Verdict: transfers, and it is the correct lens for the window-count problem.** The cost of a window
is **the cost of the process tree behind it**, and the tree is decided by the **storage boundary**
(user-data-dir / environment), not by the number of windows. See 5.2.

### 5.2 The environment/user-data-folder boundary is where the cost is decided

**Mechanism.** In Microsoft's own words for the runtime that *is* Edge on this machine: *"The
`CoreWebView2Environment` represents a user data folder and the collection of processes associated with
it… If you create multiple `CoreWebView2Environment` objects that are configured the same way (including
sharing the same user data folder), they will represent the same user data folder and the same
associated collection of processes."* And on the cost: *"Each WebView2 browser process consumes
additional memory and disk space. Therefore, avoid running a WebView2 control with too many different
UDFs at the same time."*
([Process model for WebView2 apps](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/process-model),
read 2026-09-18; [Manage user data folders](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/user-data-folder),
read 2026-09-18). Multiple app processes can share one browser process by using the same UDF
([CoreWebView2Environment reference](https://learn.microsoft.com/en-us/fr-fr/microsoft-edge/webview2/reference/winrt/microsoft_web_webview2_core/corewebview2environment?view=webview2-winrt-1.0.1222-prerelease),
read 2026-09-18). Electron's model is the same idea with different wording: one main process, and
*"Each instance of the `BrowserWindow` class creates an application window that loads a web page in a
separate renderer process"* ([Electron Process Model](https://electronjs.org/docs/latest/tutorial/process-model),
read 2026-09-18).

**Verdict: transfers completely, and it is the documentation behind a fix the house already found by
measurement.** `MEMORY-AND-SESSION-LIST.md` §1 measured 9 processes / ~892 MB per window with a private
profile and ~1 process / ~60-296 MB marginal with a shared profile — that is exactly the
"environment = process collection; extra UDFs cost a browser process each" rule, discovered
empirically. The published mechanism confirms it and adds the missing piece of vocabulary: the
per-window *identity* did not need to be a profile; it needed to be something else (the house used a
loopback port alias to get a distinct origin).

### 5.3 One page with N panes, versus N windows

**Mechanism.** Same-site documents that must script each other share a process; cross-site frames can
be split by site isolation. Therefore: **N same-origin panes in one page = one renderer** (plus the
risk that one pane's JS blocks all others), whereas **N windows = N renderer process trees**, and N
*tabs* to the same origin in the default process-per-site-instance model are also separate site
instances.

**Published cost.** No vendor publishes "cost per pane"; the published fact is the process *allocation
rule* above, plus the stability trade (one renderer per window isolates crashes; one page with N panes
does not).

**Verdict: transfers in part.** A single page with N panes is the cheapest possible UI at the browser
level and the most fragile at the human level (one crash or one busy pane takes everything). The middle
path the industry actually uses — **one browser environment, N windows, each keeping its own identity
by origin rather than by profile** — is both published-by-analogy (WebView2) and already measured here.
Building a *multi-pane page* is a separate question and the house's own research concluded the shipped
UI's conversation slot is single and owned, so a multi-pane plugin is not reachable without an engine
change (`docs/multi-window/research-dsh-perf-config.md` §8, as cited in `PERFORMANCE-MEASURED.md`).

### 5.4 Connections per origin — a real constraint, often repeated wrong

**Mechanism.** Chromium's socket pools implement *"connections per proxy, per host, and per process
limits"* ([Network Stack](https://www.chromium.org/developers/design-documents/network-stack), read
2026-09-18), and a Chromium design memo states *"For HTTP, the browser limits itself to 6 connections
per (hostname, port) pair."* ([WebSocket throttling design memo](https://docs.google.com/document/d/1a8sUFQsbN5uve7ziW61ATkrFr3o9A-Tiyw8ig6T3puA/edit),
read 2026-09-18 — a Google-Docs design memo, not a documentation page; treat as indicative). Modern
Chrome's socket pool is per-profile rather than per-host (a 2025 experiment re-sized *"the per-profile
TCP socket pool size from 256"* — [Chrome Status](https://chromestatus.com/feature/5182293874049024),
read 2026-09-18), so the 6-per-host number is best understood as the **HTTP/1.1** rule, superseded for
HTTP/2 by stream multiplexing over one connection.

**Verdict: transfers as a caution, not a design input.** The house's per-window loopback port exists
partly to get distinct origins, and `MEMORY-AND-SESSION-LIST.md` §2 observed the page opening ~6
connections on one origin, consistent with the HTTP/1.1 rule. But **WebSockets are not governed by the
6-per-origin rule**, so "N windows need N origins for connection capacity" would be the wrong lesson;
the real reason the per-origin trick works is **storage partitioning** (`localStorage` is keyed by
origin), not socket capacity. I did not find a vendor page stating the current WebSocket-per-host
limit; the memo above says only *"For WebSocket, only one connection a particular (ip, port) pair may
be in the…"* (truncated in the fetch) — **unverified** (§11).

### 5.5 Measured per-window overhead: published vs measured here

| Source | Figure |
|---|---|
| Chromium (published) | site isolation accepted at 9-13 % memory overhead; ~50 % more processes ([Reis et al.](https://www.usenix.org/system/files/sec19-reis.pdf)) |
| WebView2 (published rule) | one browser process per user data folder; "avoid… too many different UDFs" |
| Electron (published rule) | one main process; one renderer per `BrowserWindow` |
| **This repo (measured 2026-09-18)** | private profile: 9 processes / ~892 MB per window; shared profile: ~1 process / ~60-296 MB marginal (`docs/multi-window/MEMORY-AND-SESSION-LIST.md` §1) |

**Verdict: the published material gives the *rule*; only the house has the *numbers*.** No vendor
publishes a per-window MB figure for N concurrent windows on one desktop, which means this is a place
where the house's own measurement is the primary source and should not be replaced by vendor claims.

### 5.6 Verdict for the whole section

- **Transfers:** the environment/user-data-folder ↔ process-tree rule; site-instance allocation;
  private-bytes accounting; one environment with N windows and per-origin identity.
- **Transfers in part:** one page with N panes (cheapest, most fragile); per-origin partitioning
  (useful, but for storage isolation, not socket capacity).
- **Does not transfer:** WebView2/Electron as *implementations* (they are Windows-desktop app
  frameworks; the house's UI is a browser page), and any claim that a browser can host 16 windows at
  ~60 MB each without a shared environment.

---

## 6. Agent/LLM orchestration: where a unit of work runs, and long-running stateful turns

### 6.1 Temporal — durable execution, disposable workers

**Mechanism.** The workflow's state lives in an **event history** owned by the Temporal service; workers
poll **task queues**; a worker that picks up a workflow task **caches** the workflow's state in memory
for **sticky execution**, and the service *"directs future Workflow Tasks to the same Worker that cached
the Workflow, via a dedicated 'Sticky Queue'"*; if the cache is evicted, *"the Worker must **replay the
Event History** to restore its state before continuing"*
([Workflow Execution](https://docs.temporal.io/workflow-execution), read 2026-09-18). Task queues are
*"a lightweight, dynamically allocated queue that one or more Worker Entities poll for Tasks"*
([Task Queues](https://docs.temporal.io/task-queue), read 2026-09-18).

**Cost model.** Not published as MB; the published trade is explicit and transferable: **stickiness
avoids replay, and replay is the fallback that makes stickiness optional.** The system is designed so
that losing a worker's cache costs *time*, never correctness.

**Assumes.** A Temporal cluster (its own database), worker processes anywhere with network access to it.

**Verdict: the *contract* transfers; the cluster does not.** Three ideas, in order of value:
**(a) a stateful turn is a replayable log, not a process's memory** — so any worker can resume it;
**(b) affinity is an optimisation, not a requirement** — pin a session to the worker that has it warm,
but never *depend* on that pin; and **(c) workers pull from named queues**, so placement is expressed
as "which queue do I poll", which is a far cheaper decision than "which machine is least loaded".
The house already has the raw material for (a) — a per-session JSONL log is an event history in all but
name — and is missing (b) and (c) entirely. Temporal's server/cluster does not transfer.

### 6.2 Queue-backed workers: leases mean at-least-once, always

Covered in §3.6: **SQS visibility timeout** (default 30 s, message returns to the queue if not deleted
— [docs](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html))
and **Redis RPOPLPUSH** into a processing list
([docs](https://redis.io/docs/latest/commands/rpoplpush/)). At-least-once delivery implies **duplicate
execution is normal**, which is why the next item exists.

**Verdict: transfers, and it is the honest semantics for cross-machine agent work here.** The house's
broker leases already behave this way (TTL reclamation "so a dead dispatcher cannot wedge the mesh"),
and the corollary — that a re-dispatched unit may run twice — must be designed for, not hoped away.

### 6.3 Idempotency keys — how at-least-once becomes effectively-once

**Mechanism.** *"The API supports idempotency for safely retrying requests without accidentally
performing the same operation twice. When creating or updating an object…"* the client supplies a key
and the server deduplicates
([Idempotent requests](https://docs.stripe.com/api/idempotent_requests), read 2026-09-18).

**Verdict: transfers as a rule, cheaply.** Any effect that crosses a machine boundary (a file write, a
branch push, a message sent) must carry a key that makes a second application a no-op. This is
*independent* of which scheduler is chosen and is a prerequisite for lease-based dispatch, so it is
strictly cheaper to adopt than any placement change.

### 6.4 LangGraph checkpointers — the minimal version of 6.1

**Mechanism.** *"A checkpoint is a snapshot of the graph state saved at each super-step"*, where *"a
super-step is a single 'tick' of the graph where all nodes scheduled for that step execute"*, keyed by
`thread_id`, enabling *"persistence, human-in-the-loop, and fault-tolerant execution"*
([Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers), read 2026-09-18;
[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence), read 2026-09-18).

**Verdict: transfers, and it is the *achievable* version of 6.1 for this environment.** No server, no
cluster: a durable snapshot per step, keyed by session, written by whoever ran the step. Combined with
(a) replayable logs, it delivers the property the problem statement actually needs — *a session can be
resumed on a different machine*.

### 6.5 Sandbox platforms: Firecracker, E2B, Modal

**Mechanism — pre-warmed, snapshot-restored execution slots.** Firecracker's numbers are the strongest
published in this whole document: *"memory overhead of less than 5 MB per container, boots to
application code in less than 125 ms, and allows creation of up to 150 MicroVMs per second per host"*
([Agache et al., NSDI'20](https://www.usenix.org/system/files/nsdi20-paper-agache.pdf), read
2026-09-18). Modal's published mechanism is the *policy* on top of that: containers stay idle *"for a
short period before shutting down. By default, the maximum idle time is 60 seconds"*, warm up is a
first-class phase (`@modal.enter`), and **memory snapshots** *"capture the state of a container's memory
at user-controlled points after it has been warmed up and reuses that state in future boots"*
([Cold start performance](https://modal.com/docs/guide/cold-start), read 2026-09-18). E2B's public
claims (Firecracker-based microVMs, plan-limited continuous runtime, pause/resume) are vendor marketing
I did not verify from a technical page (§11).

**Verdict: the *policy* transfers, the *isolation* does not.** Windows has no Firecracker/KVM path for
this; and single-user means microVM isolation buys nothing. What transfers intact:
**(a) keep a warm pool, and treat "cold" as a latency budget to be paid in the background** — the house
already knows the engine's expensive boot calls (`settings/describe` 145 ms, `agentPresets/list`
98 ms) and staggers window launches; a warm-pool/prewarmer is the same idea applied to runners;
**(b) an explicit idle timeout with a default that is *short*** (Modal: 60 s) *because restart is cheap* —
which is only true once (a) is true. Prerequisite: cheap cold start. Without it, a short idle timeout is
a worse experience than no timeout.

### 6.6 Verdict for the section

The industry's answer to "where does a unit of agent work run" is **pull from a named queue, with
leases, and idempotent effects**; and its answer to "how do long stateful turns survive" is **a durable
log plus checkpoints plus an optional warm worker**. Both are available here today, without a cluster.
The one thing none of them solves, and the house does need, is **moving a live session between
machines**; the only published systems that do that at all are the dev-environment platforms in §1, and
they do it by *never moving it* — the environment stays where it was created, and the *UI* reattaches
from anywhere. That is an important and rather deflating finding, and I state it as such.

---

## 7. The 25-31 second list path

### 7.1 What was measured, restated precisely

`POST /api/session/list` → `session/list` returned **25,370.8 ms / 25,069 ms / 31,357.1 ms** for
**679-685 rows / 1.46 MB**, while every other RPC on the same page load answered promptly. The cause,
reproduced outside the engine: `listArtifacts()` *"walks every session directory on every call: one
`readdir` per project, one per session, one `stat`, and one first-zstd-line read against each"* —
5,900 ms of raw filesystem work in plain Node, *"linear in the number of stored sessions and there is
no paging parameter to lean on"*. The visible symptom was a sidebar rendering empty with no loading
state ([MEMORY-AND-SESSION-LIST.md](docs/multi-window/MEMORY-AND-SESSION-LIST.md) §2).

That is the classic shape: **an O(N) metadata walk per read where N is the total number of stored
objects and no index exists.** (The repo has a second, independent instance of the same class:
988,332 FTS5 rows scanned per document because `WHERE doc_id=?` on an UNINDEXED column cannot be pushed
down — [68-read-amplification.md](docs/mesh/68-read-amplification.md).)

### 7.2 The standard remedies, from primary sources

| Remedy | Published statement | Cost |
|---|---|---|
| **Pagination, at the outset** | *"RPCs returning collections of data must provide pagination at the outset, as it is a backwards-incompatible change to add pagination to an existing method"* ([AIP-158](https://google.aip.dev/158), read 2026-09-18); `page_size`/`page_token` are mandatory on all list requests ([AIP-132](https://google.aip.dev/132), read 2026-09-18) | changes the API contract; caller must page |
| **Index / covering index** | The universal database answer; in the repo's own FTS5 case the missing index is `chunks_meta.idx_cm_doc`, which already exists (`68-read-amplification.md` §3) | a write-path change and a migration |
| **Materialised view** | *"Materialized views… persist the results in a table-like form"*, refreshed with `REFRESH MATERIALIZED VIEW` ([PostgreSQL 39.3](https://www.postgresql.org/docs/current/rules-materializedviews.html), read 2026-09-18) | refresh cost; *"If the source data is changing at the point when the view is generated, the copy of the data in the view won't be fully consistent"* ([Azure Materialized View pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/materialized-view), read 2026-09-18) |
| **A read model per query (CQRS)** | *"The read model of a CQRS implementation can contain materialized views of the write model data"* ([CQRS pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs), read 2026-09-18) | two models to keep in sync; best paired with events |
| **Serve from cache while revalidating** | *"The stale-while-revalidate HTTP Cache-Control extension allows a cache to immediately return a stale response while it revalidates it in the background, thereby hiding latency (both in the network and on the server) from clients"* ([RFC 5861](https://www.rfc-editor.org/rfc/rfc5861), read 2026-09-18) | staleness window; needs invalidation |
| **Push-based invalidation: the watch cache** | Kubernetes *"has long used a watch cache to optimize read operations. The watch cache stores a snapshot of the cluster state and receives updates"*; from v1.31 the cache could serve **strongly-consistent reads**, which *"enabled filtered collections… to be safely served from the cache instead of etcd, dramatically reducing its load"* ([Kubernetes v1.34: Snapshottable API server cache](https://kubernetes.io/blog/2025/09/09/kubernetes-v1-34-snapshottable-api-server-cache), read 2026-09-18; proposal: [KEP-2340](https://github.com/kubernetes/enhancements/blob/master/keps/sig-api-machinery/2340-Consistent-reads-from-cache/README.md), read 2026-09-18) | an in-memory index **maintained on write**, plus a watch channel for clients |
| **Fix the N+1 / metadata storm structurally** | The N+1 problem and its eager-loading/batching remedy are standard ORM practice; the canonical *non*-database form is "do not `stat` N files to answer a question about N files — keep a manifest" (git's packed-refs, `locate`'s database). I did **not** find a vendor page that states this as a principle; the closest primary sources I verified are the two Kubernetes/Postgres items above and the repo's own FSH analysis (§11) | a write-path change |

### 7.3 Which remedy is right here — the honest verdict

**The house's applied fix is the cache remedy, and it is the weakest of the set.** `dshw-proxy.mjs`
keeps one cached `session/list` response: cold callers pay the walk, warm (<15 s) callers get the cache,
stale callers get stale-while-revalidate with a background refresh, and `dshw ensure` prewarms every
minute. Measured: **25,371 ms → 29 / 29 / 92 ms (n=3)**. The house itself documents the two costs:
*"The 15 s TTL is a judgement, not a measurement"* and *"mutations do not invalidate the cache"*
(`MEMORY-AND-SESSION-LIST.md` §6).

So the correct verdict is not "the fix is wrong" — it is **"the fix is one of six published remedies,
chosen because it required no engine restart, and it is the only one that leaves the pathology in
place"**. Three things are worth saying plainly:

1. **The cost is linear in stored objects and unbounded**, so the cache converts a 30 s read into a
   15 s *correctness* window, and the window grows with usage. RFC 5861's SWR is a legitimate mechanism
   — but it is designed for caches that are *in front of an acceptable* origin, and here the origin is
   the problem.
2. **The remedy that fits the constraint is the watch cache, not the cache**: an in-memory *index* of
   sessions maintained on write (create/rename/delete/append), served at O(1), with a push channel so
   a mutation in one window appears in another immediately rather than within 15 s. Kubernetes'
   watch cache is the published precedent, and the house's own `journal/index/` (a generated index —
   `entries.tsv` 379,837 B plus `journal.db` 10,539,008 B, both present in the repo, observed
   2026-09-18) is the same pattern solved *inside the same codebase*.
3. **Pagination is still required**, because the *response* is 1.46 MB and will keep growing; AIP-158's
   warning that pagination is backwards-incompatible to add later applies exactly.

**Verdict: the mechanism transfers (K8s watch cache / materialised read model); the house's chosen
implementation does not, and the house already knows the right pattern.** See §10 item 4.

---

## 8. What does not transfer — consolidated, with reasons

| Does not transfer | Reason |
|---|---|
| Kubernetes, Nomad, Slurm, Ray, Kueue, Temporal, Coder, Che, BinderHub, Codespaces as *systems* | each requires a cluster OS, a control-plane database, or per-workload VMs; the environment is 4 heterogeneous machines, one user, a personal budget, and two of the four run Windows |
| Multi-tenancy: per-user isolation, authentication boundaries, per-tenant quota, fair sharing between users | one user (plus one employee). Any mechanism whose *value* is isolation between users buys nothing here |
| Docker / containers / Firecracker microVMs | not installed, not wanted on the Windows boxes, and single-user isolation is not a requirement. The *warm pool* and *snapshot* policies on top of them do transfer as process-level analogues |
| Codespaces-style per-workspace VM | cost, and cold start without a prebuild farm |
| `systemd`, `cgroups`, POSIX ptys, UDP-based transports (mosh), `tmux` binaries | Linux-only; the machine the person sits at is Windows. The *client/server split* and *state-sync* ideas transfer; the software does not |
| VS Code Server as a service / as a shared instance | Microsoft's licence forbids both; it is single-user by design |
| Kubernetes gang scheduling | does not exist by default in k8s; gang admission here must be built (Ray placement groups / Kueue are the citable models) |
| Any design that assumes one LAN | home and office are joined only by Tailscale, and both a 25 s ssh probe and a 7.3 s capacity read were measured across it |
| Any design that assumes node state is stable for minutes | measured: capacity readings have a ≤15 s TTL and a desktop answered in 7,342 ms; ranking on them without a reservation races (`76-broker.md` §10.5) |

---

## 9. The five mechanisms most worth stealing

Ordered by (value here) ÷ (prerequisite cost).

### 1. The session must outlive both the UI and the process that owns it — the client/server split (tmux), and the front door that is not the owner (JupyterHub's proxy ≠ Hub; Coder's control plane ≠ data plane)

Every system in §1 and §4 that survives a disconnect does the same thing: **exactly one component owns
the session's liveness; the display is a client of it; the component that decides where things run is
neither of those.** tmux spells it out (*"a session is displayed on screen by a client and all sessions
are managed by a single server… The server and each client are separate processes"*), JupyterHub puts a
proxy in front of a Hub that owns spawning, and Coder is explicit that its control plane can be
multiple replicas because it holds no payload. The house version ties session liveness to one
`dsh web` process whose `DSH_HOME` must have a single writer, which means "keep the session alive",
"restart the engine", and "move the session to another machine" are currently the same three-way
conflict. **Prerequisite:** an explicit session-owner component with a stable identity, a supervisor
that can restart it without ending sessions, and a front door that routes to it by identity —
i.e. the current single-writer engine must become *restartable-in-place* before it can become
*movable*.

### 2. Addressability: one durable handle per session, in the URL (JupyterHub named servers `/user/<name>/<server>`; Codespaces/Coder/Che port URLs)

The house's open owner question — restoring a window to *its* session — exists in the research as a
**solved, boring** problem: JupyterHub lets one user hold multiple named servers and addresses each by
path, with a per-user cap; Codespaces turns every forwarded port into a URL; Coder calls them Dev URLs.
The cost is nothing; the benefit is that a window/session mapping becomes data (a URL) instead of state
in a browser's `localStorage` keyed by origin, which is why *"two windows on the same port share that
one key — last writer wins on reload"* (`ANALYSIS-AND-DECISION.md` §3). **Prerequisite:** a session id
in the route and a router that honours it — currently *"`pushState` / `replaceState` / `popstate` /
`location.hash` / `sessionId` occur zero times across all 65 installed client bundles"*, the server
matches pathname only, and the `?token=` exchange 303-redirects to literal `/`. This may require an
engine change; that is a cost to be priced, not a reason to skip.

### 3. Reservation before admission, with a TTL lease and a queue position — never a refusal (Kueue's QuotaReservation → Admission; SQS visibility timeout; Ray placement groups for the all-or-nothing case)

This is the mechanism that makes "run dozens at once on four machines" safe rather than optimistic:
**reserve the scarce resource atomically, hold it under a TTL so a dead owner's reservation expires,
admit only after the reservation is held, and answer a queued request with a position rather than an
error.** The house has independently arrived at all of it (broker leases, the governor's
queue-never-refuse budget) — and Kueue's two-phase wording plus SQS's visibility-timeout semantics are
the published versions of the same idea, with one thing the house lacks: **gang reservation**, i.e. a
12-child fleet must reserve 12 slots or none, because *"placements cannot each boot an instance"*
(`76-broker.md` §10.x) — Ray calls this gang scheduling and Kueue handles it with quota plus
preemption. **Prerequisite:** every scarce resource must be represented as an integer a single writer
controls (slots, in-flight tool calls, API budget), the reservation must carry an expected end so the
queue can project (Slurm backfill), and — the one real gap — **the reservation table must survive the
decider's restart**, which today it does not (in-memory `Map`).

### 4. Read the list from a write-maintained index, never from a walk of the store (Kubernetes API server watch cache; AIP-158 pagination as the other half)

The 25-31 s `session/list` is not a tuning problem; it is a *missing data structure* problem:
`readdir`+`stat`+first-line-read per stored session, on every call, with no paging parameter. The
published mechanism that fits is the watch cache — an in-memory index of the collection, updated by the
writes themselves, serving reads in O(1) and pushing changes to clients — with cursor pagination for
the response body. Crucially, **the same repository already does this for a different collection**
(`journal/index/`: a generated `entries.tsv` + `journal.db` index over ~2,000 entries, with a
`stamp.json` staleness marker), which means the pattern is understood here and merely not applied to
sessions. **Prerequisite:** the session index must be updated *in the same critical section as the
mutation* (create, rename, delete, append) or it will drift, and a drift-detecting rebuild must exist;
a cache in front of a slow origin (the current proxy) is not a substitute, because it only hides the
cost and adds a staleness window that grows with usage.

### 5. Decouple agent state from the worker that runs it: a durable per-session log, checkpoints per step, and affinity as an optimisation (Temporal event history + sticky queues; LangGraph per-super-step checkpoints)

Everything else in this list makes the current machine usable. This one is what makes the *fleet*
possible: a session whose authoritative state is a durable, replayable log can be resumed by **any**
worker, which is the precondition for "run the agent on whichever machine is least loaded" and for
surviving the loss of the machine the owner was sitting at. Temporal's published design is explicit
that stickiness (the warm worker) is an optimisation on top of replay, not a requirement — *"If the
cached Workflow is evicted… the Worker must replay the Event History to restore its state before
continuing"* — and LangGraph shows the same property without a server: a checkpoint per super-step,
keyed by thread. The house already writes a per-session JSONL log, so the raw material exists; what is
missing is treating it as **the** state (rather than as a record of what a process did) and writing
checkpoints at a defined boundary. **Prerequisite:** the log must be complete enough to reconstruct
state (including tool results and pending tool calls), and the turn boundary must be a defined,
idempotent unit — otherwise replay resumes into a half-applied effect, which is why mechanism 3's
idempotency keys and this one belong together.

---

## 10. Patterns we already reinvented badly

Ranked by how much the known solution would have saved. Each item names the known solution and the
specific cost of the house-built version.

### 1. **`multi-window/dshw.ps1` + `dshw-proxy.mjs` is a hand-rolled, less capable JupyterHub** — the strongest finding in this document

The house has independently built, by hand, and over several painful iterations:

| What `dshw`/`dshw-proxy` is | JupyterHub's name for it |
|---|---|
| A launcher registry per window/workspace (`windows.json`, one row per slot, geometry, profile) | **Spawner configuration** |
| A single front-door process in front of the one engine, routing by origin/port, splicing everything but one call | **The proxy** (configurable-http-proxy) |
| Start / poll / stop a per-slot browser+session, restore registry across reboot | **Spawner: start, poll, stop** |
| `ensure`, run every minute by Task Scheduler | Hub reconciliation / idle-culler service |
| `dshw state.json` + token recovery + `doctor` probes | Hub's spawn/restart state machine |
| Per-window session identity via loopback-port origin, because a window cannot be addressed by URL | **Named servers**: `/user/<name>/<server>` |

The parts JupyterHub solved that the house still lists as open problems:

- **Addressability.** `ANALYSIS-AND-DECISION.md` §3 records that no session is addressable by URL, that
  the `?token=` exchange discards query parameters, and that session choice lives in
  `localStorage["dsh.sessions.current"]` keyed by origin — hence *"restore the window, then click the
  session"*, which is open owner question 3. JupyterHub's named servers make that a URL, and the
  documented per-user cap replaces the house's ad-hoc slot accounting.
- **A lifecycle *policy* rather than a watchdog.** The house has `ensure` (is it up?) and
  `stop <slot>` (a human typed it). JupyterHub has an idle culler fed by *two* signals — server activity
  reports **and** proxy-observed network activity — with a documented timeout. The house has no
  equivalent, which is why "the machine he sits at becomes the bottleneck" is a *policy* gap: nothing
  ever decides that a quiet session should be culled, suspended, or moved.
- **A spawner abstraction over *where*.** JupyterHub's Spawner interface exists precisely so that
  "local process", "container", "another host" are the same three operations (start/poll/stop). The
  house's equivalent is spread across `dshw.ps1` (Windows, one machine), the broker (placement), and
  `plugin-remote-fanout` — three mechanisms for one concept.

**Honest caveat:** JupyterHub's default single-user spawner is *same-user, no isolation*, so its fit is
not "JupyterHub is drop-in"; it is "the concept, the interface and the two policies are already
designed, documented and battle-tested, and the house re-derived a subset of them under deadline
pressure." The reason this is the strongest finding is that it is not a small piece of wheel-reinvention:
launcher + proxy + spawner + registry + culler is the whole control plane, and the missing pieces
(addressability, cull policy) are exactly the two things the house is still blocked on.

### 2. **`packages/mesh-broker` is a bespoke re-implementation of scheduler + quota reservation, missing the parts that make the published versions safe**

The broker is genuinely good engineering: five tiers ending in a never-refusing emergency placement,
leases with TTL reclamation, capability gating (`dispatch.v1`), staleness-bounded readings, and — the
detail most home-built schedulers get wrong — *"Choose a node and issue its lease. Synchronous on
purpose: the decision and the reservation cannot interleave"* (`lib/broker.js`), which is Kubernetes'
bind-before-start. It nonetheless re-derives, less completely, mechanisms with published designs:

- **durable reservation**: leases live in an in-memory `Map` (`lib/leases.js`), so a broker restart
  forgets every commitment. Coder's equivalent puts the single writer's state in Postgres *precisely so
  the control plane can restart*; `76-broker.md` §8 already lists "behaviour under a broker restart
  mid-flight" as unverified. Kueue's QuotaReservation is an API object for the same reason.
- **gang admission**: not implemented; the docs themselves note a 12-child fleet cannot be honoured by
  per-child placements. Ray placement groups and Kueue's preemption are the published answers.
- **pull vs push**: the broker is consulted *first* for every unit of work, putting the decision plane
  on the critical path across a link where a capacity read was measured at 7,342 ms. Ray's bottom-up
  design (try local, spill only when needed) is the published inversion.
- **committed-until ranking**: ranking is on *current* free slots only, i.e. no Slurm-style backfill and
  no projection, so a node with a long-running committed lease ranks identically to an idle one.

### 3. **Per-window browser profiles were a worse implementation of "one environment, N windows"** — and the house proved it against itself

`dshw.ps1` launched every window with its own `--user-data-dir`, which per Microsoft's own documentation
means a separate browser process collection per window, and per Chromium's means a full process tree per
site-instance. Measured: **9 processes / ~892 MB per window**; after switching to a shared profile with
per-slot loopback origins: **~1 process / ~60-296 MB marginal**
(`MEMORY-AND-SESSION-LIST.md` §1). The published rule — *"Each WebView2 browser process consumes
additional memory and disk space. Therefore, avoid running a WebView2 control with too many different
UDFs at the same time"*; *"Multiple app processes can share a browser process by creating their webviews
from a `CoreWebView2Environment` with the same user data folder"* — states the same thing, and would
have pointed at the fix (share the environment; partition identity by something cheaper than a profile)
before any measurement was needed. *This one is already fixed*; it is listed because the mechanism is
the reusable part (and because the same mistake is available to make again with per-session WebView2
hosts or per-session Electron windows).

### 4. **The `session/list` read-through cache is a worse version of the watch cache** — and the codebase already contains the right pattern

The proxy cache converts 25-31 s into 29-92 ms and is honest about its weakness: *"The 15 s TTL is a
judgement, not a measurement"*, *"mutations do not invalidate the cache"*
(`MEMORY-AND-SESSION-LIST.md` §6). A cache in front of an origin that is slow because it walks every
stored object is the one remedy of the five in §7.2 that leaves the pathology intact — the cost remains
linear in stored sessions and unbounded, so the staleness window grows with use. Kubernetes' watch
cache (an index maintained by writes, serving consistent reads, with a watch channel for invalidation)
is the published mechanism, and **the same repository already implements exactly that shape for the
journal** (`journal/index/` with `entries.tsv`, `journal.db`, `stamp.json`). The house is not missing
the idea; it is missing the application.

### 5. **The engine's single-writer + one-process-per-machine constraint is the "session state lives in a process's memory" anti-pattern that durable-execution engines exist to fix**

Measured and recorded: *"a second `dsh web` process on the same `DSH_HOME` wrote duplicate sequence
numbers into one session log and made the whole history unloadable"*, conclusion: *"one writer process
per `DSH_HOME`"* (`PERFORMANCE-MEASURED.md`). That is a correct *local* conclusion, but it makes the
engine un-movable and un-restartable — and the fix in the wider industry is not "one writer per log"
but "**the log is the interface, and the writer is disposable**": Temporal's workers are given sticky
caching and then told that losing it merely costs a replay; LangGraph checkpoints each super-step;
Coder keeps durable state in Postgres and calls the rest thin. The house's own diagnosis (two writers
corrupt the log) names the symptom; the mechanism it is missing is the one that makes a *single*
writer restartable — versioned/sequenced append with idempotent step boundaries — which would turn
"move the session to the least loaded machine" from a correctness hazard into a checkpoint plus a
restart.

### 6. **The admission governor admits but never preempts; Kubernetes's published model is an ordered eviction policy**

The governor's published design (budget from free memory, ~160 MB per in-flight call, clamped 4-24,
queue never refuse) is a sound admission controller, and the "queue, never amputate" rule is the same
instinct as the broker's. What is absent is the second half of Kubernetes' model: **QoS classes and an
eviction order** — *"Kubernetes will first evict `BestEffort` Pods…, followed by `Burstable` and finally
`Guaranteed`"* — so under pressure the *system* decides what to shed, deterministically, rather than the
OS deciding by working-set trimming. In practice, when commit approached 31.61 GB the observed effect
was *"commit pressure trimming working sets"* and whichever window was streaming became slow
(`PERFORMANCE-MEASURED.md`). A named, ordered class for "this may be shed" (an idle window, a prewarmed
runner, a completed session's UI) is a few lines of policy and would replace an emergent behaviour with
a declared one.

### 7. **Smaller, same-shape duplications**

- **The origins proxy is a reinvention of port-forwarding/URL routing** (Codespaces/Coder Dev URLs),
  done at the TCP level because the app has no URL addressability. Same root cause as item 1.
- **`windows.json` + Task Scheduler is a reinvention of a supervisor with lifecycle policy** (systemd
  user units; on Windows, ideally a Job Object with kill-on-close for the process tree). The house
  already hit the Windows-specific landmine (session-0 isolation: a service cannot show UI,
  `ANALYSIS-AND-DECISION.md` §4) and solved it correctly — the remaining gap is the *policy*, not the
  mechanism.
- **`dshw doctor` is a reinvention of readiness/liveness probing** (kubelet probes), and it discovered
  the right failure mode itself (`Test-LaunchUrl` checked a token's *shape* while the engine was serving
  a different pid — a liveness probe that does not exercise the path is not a probe).

---

## 11. What I could not verify

Stated so that no future reader mistakes these for sourced facts.

1. **Slurm's atomic (all-or-nothing) job allocation.** I verified the backfill description and that
   Slurm's "gang scheduling" page actually describes *timeslicing*, not all-or-nothing. I did **not**
   fetch a page asserting the atomic-allocation property that HPC practitioners rely on.
2. **Slurm preemption/QoS mechanics** beyond the sentence quoted on the gang-scheduling page.
3. **Gitpod prebuild mechanics and current product naming** (the vendor page I read is "Gitpod Classic"
   under an `ona.com` domain; I verified only the ephemeral-workspace lifecycle text).
4. **Databricks**: the documentation URL I attempted returned an ad-tracking image instead of content;
   I make no numeric claim about Databricks clusters, autoscaling or auto-termination.
5. **SageMaker Studio's minimum idle timeout (60 minutes)** — from an AWS re:Post answer, not vendor
   documentation.
6. **The current browser limit on WebSocket connections per host.** The Chromium design memo I found is
   a Google Doc and was truncated in the fetch; Chromium's network-stack page confirms socket-pool
   per-host limits exist but gives a different number (32) and is old. Treat the "6 per (hostname, port)"
   figure as HTTP/1.1-specific.
7. **The 1999 Blumofe–Leiserson paper text.** I verified the DOI, the title and the deque discipline
   (LIFO owner / FIFO thief / randomized victim) from the OSDI'23 work-stealing paper and current
   literature, not from the original PDF.
8. **GNU screen / dtach / abduco** — not read at all; mentioned by name only.
9. **E2B's technical claims** (microVM boot times, runtime limits, pause/resume) — marketing pages only.
10. **Modal's `@modal.enter` warm-up phase** is described in the page I read but I did not verify its
    API semantics.
11. **The house's broker restart behaviour mid-flight** is unverified by the house too
    (`76-broker.md` §8); I assert only that its lease table is in-memory, which I read in
    `packages/mesh-broker/lib/leases.js`.
12. **"N same-origin panes share one renderer process"** is my reading of Chromium's site-instance rules
    as documented; the docs state the allocation rule and the memory/stability trade, not the specific
    pane claim.
13. **Kubernetes' default scoring being least-allocated (rather than bin-packing)** — stated in §3.1 and
    not verified from a Kubernetes documentation page in this pass.

---

## 12. Sources, with the date each was read

All reads 2026-09-18 (UTC) unless stated. Primary = vendor/project documentation, source code or a
peer-reviewed paper; secondary = a Q&A, blog or third-party summary, labelled as such.

**Remote / cloud development environments**
- [Visual Studio Code Server](https://code.visualstudio.com/docs/remote/vscode-server) — primary. Single-user, no service hosting.
- [Supporting Remote Development and GitHub Codespaces](https://code.visualstudio.com/api/advanced-topics/remote-extensions) — primary. UI vs Workspace extensions, Remote Extension Host.
- [Remote Development using SSH](https://code.visualstudio.com/docs/remote/ssh) — primary. Server on the remote; client needs outbound 443 only.
- [Developing with Remote Tunnels](https://code.visualstudio.com/docs/remote/tunnels) — primary. Outbound tunnelling, no SSH.
- [What are GitHub Codespaces?](https://docs.github.com/en/codespaces/overview) — primary. Container on a VM; machine types.
- [Forwarding ports in your codespace](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace) — primary. Port → URL.
- [Coder architecture](https://coder.com/docs/admin/infrastructure/architecture) — primary. `coderd` thin API; single Postgres writer; Dev URLs.
- [Coder Workspace Proxies](https://coder.com/docs/admin/networking/workspace-proxies) — primary. Data plane separated from control plane.
- [Workspace Lifecycle (Gitpod Classic / Ona)](https://ona.com/docs/classic/user/configure/workspaces/workspace-lifecycle) — primary. Ephemeral `/workspace` + restore.
- [Che architecture](https://www.eclipse.org/che/docs/stable/discover/architecture-overview) — primary. DevWorkspace CRs, operator, workspace pods.

**Notebook / interactive-compute servers**
- [JupyterHub Technical Overview](https://jupyterhub.readthedocs.io/en/latest/reference/technical-overview.html) — primary. Proxy / Hub / single-user server / Spawner.
- [JupyterHub Spawners](https://jupyterhub.readthedocs.io/en/latest/reference/spawners.html) — primary. start/poll/stop; implementations.
- [JupyterHub Configuring user environments](https://jupyterhub.readthedocs.io/en/2.3.0/reference/config-user-env.html) — primary. Named servers; `allow_named_servers`; per-user limits.
- [jupyterhub-idle-culler](https://github.com/jupyterhub/jupyterhub-idle-culler) — primary (project source). Activity from servers + proxy.
- [Jupyter Server Architecture Diagrams](https://jupyter-server.readthedocs.io/en/latest/developers/architecture.html) — primary.
- [Jupyter Server WebSocket kernel wire protocols](https://jupyter-server.readthedocs.io/en/latest/developers/websocket-protocols.html) — primary. ZeroMQ ⇄ WebSocket bridge.
- [Jupyter Enterprise Gateway — Culling idle kernels](https://jupyter-enterprise-gateway.readthedocs.io/en/latest/operators/config-culling.html) — primary (sibling project). `cull_idle_timeout`, `cull_interval`.
- [SageMaker AI — Idle shutdown](https://docs.aws.amazon.com/sagemaker/latest/dg/studio-updated-idle-shutdown.html) — primary. Per-application-type policy, profile overrides domain.
- [AWS re:Post — SageMaker Studio idle timeout minimum](https://repost.aws/questions/QUM-2l5LfNQXqHcYAZKWQMVg/question-about-shortening-auto-termination-time-in-sagemaker-studio) — **secondary**.

**Scheduling / admission**
- [Kubernetes — Resource Management for Pods and Containers](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) — primary. Requests vs limits.
- [Kubernetes — Pod Quality of Service Classes](https://kubernetes.io/docs/concepts/workloads/pods/pod-qos) — primary. QoS + eviction order.
- [Kubernetes — Node-pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/) — primary. Soft/hard thresholds, signals.
- [Kubernetes Scheduler](https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/) — primary. Feasible → score → bind.
- [Kueue — Concepts](https://kueue.sigs.k8s.io/docs/concepts) — primary. QuotaReservation → Admission.
- [Kueue — Cluster Queue](https://kueue.sigs.k8s.io/docs/concepts/cluster_queue) — primary. Preemption on insufficient quota.
- [Nomad — Advanced job scheduling](https://developer.hashicorp.com/nomad/docs/job-scheduling) — primary. Binpack default; feasible subset then score.
- [Nomad for Kubernetes practitioners](https://github.com/hashicorp/web-unified-docs/blob/main/content/nomad/v2.0.x/content/docs/k8s-nomad/index.mdx) — primary (project docs repo). Evaluation broker.
- [Slurm — Scheduling Configuration Guide](https://slurm.schedmd.com/sched_config.html) — primary. Backfill definition; `sched_interval`.
- [Slurm — Gang Scheduling](https://slurm.schedmd.com/gang_scheduling.html) — primary. Timeslicing (not all-or-nothing).
- [Ray — OSDI'18 paper](https://www.usenix.org/system/files/osdi18-moritz.pdf) — primary (peer-reviewed). Fig. 6 bottom-up scheduler + GCS.
- [Ray — placement groups (source .rst)](https://raw.githubusercontent.com/ray-project/ray/master/doc/source/ray-core/scheduling/placement-group.rst) — primary (project source). Gang scheduling, PACK/SPREAD.
- [Blumofe & Leiserson, *Scheduling Multithreaded Computations by Work Stealing*](https://dl.acm.org/doi/10.1145/324133.324234) — primary (DOI; text not fetched); deque disciplines corroborated by [BWoS, OSDI'23](https://www.usenix.org/system/files/osdi23-wang-jiawei.pdf).
- [Redis — RPOPLPUSH, "Pattern: reliable queue"](https://redis.io/docs/latest/commands/rpoplpush/) — primary.
- [Amazon SQS — Visibility timeout](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html) — primary. TTL lease, at-least-once.

**Session multiplexing / durability**
- [tmux(1)](https://man7.org/linux/man-pages/man1/tmux.1.html) — primary. Client/server over a socket; detached sessions; control mode.
- [Mosh — State-of-the-Art Good Old-Fashioned Mobile Shell (;login:)](https://www.usenix.org/system/files/login/articles/winstein.pdf) — primary. SSP, object-layer rate control.
- [Mosh — USENIX ATC'12 abstract](https://www.usenix.org/conference/atc12/technical-sessions/presentation/winstein) — primary. 70 % local echo; <5 ms vs 503 ms median keystroke.

**Browser UI at scale**
- [Chromium — Process Model and Site Isolation](https://chromium.googlesource.com/chromium/src/+/main/docs/process_model_and_site_isolation.md) — primary. Site-instance allocation; memory/stability trade.
- [Chromium — Process Models](https://chromium.googlesource.com/playground/chromium-org-site/+/refs/heads/main/developers/design-documents/process-models.md) — primary. Default is per-site-instance.
- [Reis et al., *Process Separation for Web Sites within the Browser*, USENIX Security '19](https://www.usenix.org/system/files/sec19-reis.pdf) — primary (peer-reviewed). 9-13 % memory overhead.
- [Chromium — Memory Usage Backgrounder](https://www.chromium.org/developers/memory-usage-backgrounder) — primary. Private = PWS + Shareable − Shared; `about:memory`.
- [WebView2 — Process model](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/process-model) — primary. Environment = UDF + process collection.
- [WebView2 — Manage user data folders](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/user-data-folder) — primary. Extra UDF = extra browser process.
- [CoreWebView2Environment reference](https://learn.microsoft.com/en-us/fr-fr/microsoft-edge/webview2/reference/winrt/microsoft_web_webview2_core/corewebview2environment?view=webview2-winrt-1.0.1222-prerelease) — primary. Multiple app processes share one browser process.
- [Electron — Process Model](https://electronjs.org/docs/latest/tutorial/process-model) — primary. One main process; renderer per `BrowserWindow`.
- [Chromium — Network Stack](https://www.chromium.org/developers/design-documents/network-stack) — primary. Socket-pool per-host limits.
- [Chromium — WebSocket throttling design memo](https://docs.google.com/document/d/1a8sUFQsbN5uve7ziW61ATkrFr3o9A-Tiyw8ig6T3puA/edit) — **weak primary** (design memo, truncated fetch).
- [Chrome Status — Re-Sizing TCP Connection Pool](https://chromestatus.com/feature/5182293874049024) — primary. Per-profile socket pool.

**Agent / LLM orchestration**
- [Temporal — Workflow Execution](https://docs.temporal.io/workflow-execution) — primary. Sticky cache, eviction → replay.
- [Temporal — Task Queues](https://docs.temporal.io/task-queue) — primary. Workers poll queues.
- [LangGraph — Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers) — primary. Checkpoint per super-step.
- [LangGraph — Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) — primary. Thread-scoped state.
- [Stripe — Idempotent requests](https://docs.stripe.com/api/idempotent_requests) — primary. Deduplicate by key.
- [Firecracker — Agache et al., NSDI'20](https://www.usenix.org/system/files/nsdi20-paper-agache.pdf) — primary (peer-reviewed). <5 MB/microVM, <125 ms boot, 150/s/host.
- [Modal — Cold start performance](https://modal.com/docs/guide/cold-start) — primary. 60 s default idle; memory snapshots; `@modal.enter`.

**List-endpoint pathology**
- [AIP-158 Pagination](https://google.aip.dev/158) and [AIP-132 Standard methods: List](https://google.aip.dev/132) — primary. Pagination mandatory from the outset.
- [RFC 5861 — stale-while-revalidate](https://www.rfc-editor.org/rfc/rfc5861) — primary. SWR definition.
- [PostgreSQL 39.3 — Materialized Views](https://www.postgresql.org/docs/current/rules-materializedviews.html) — primary.
- [Azure Architecture Center — Materialized View pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/materialized-view) — primary. Refresh consistency caveats.
- [Azure Architecture Center — CQRS pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs) — primary. Read model from materialised views.
- [Kubernetes — Snapshottable API server cache (v1.34)](https://kubernetes.io/blog/2025/09/09/kubernetes-v1-34-snapshottable-api-server-cache) — primary. Watch cache serving consistent reads instead of etcd.
- [KEP-2340 — Consistent Reads from Cache](https://github.com/kubernetes/enhancements/blob/master/keps/sig-api-machinery/2340-Consistent-reads-from-cache/README.md) — primary.

**In-repo sources used for the current state and the measurements quoted** (not external; listed so
the numbers above can be traced):
`docs/multi-window/ANALYSIS-AND-DECISION.md`, `docs/multi-window/PERFORMANCE-MEASURED.md`,
`docs/multi-window/MEMORY-AND-SESSION-LIST.md`, `docs/mesh/76-broker.md`, `docs/mesh/68-read-amplification.md`,
`docs/mesh/10-inventory.md`, `packages/mesh-broker/lib/{broker,leases,scoring}.js`;
`journal/index/` contents observed 2026-09-18 (`entries.tsv` 379,837 B, `journal.db` 10,539,008 B,
`stamp.json`).
