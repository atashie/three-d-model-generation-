# Option 4: rented GPU, checked 2026-11-09

Discussion only: no account created, money spent, machine deployed or images uploaded.

**Owner decision after walkthrough:** GPU rental is unnecessary for now.
MakerLab exports were subsequently supplied and inspected (`MAKERLAB-RESULTS.md`).
The recommendation below records the reasoning at the time of the walkthrough.

A rented GPU is a remote computer on which we install and run the selected model.
It gives control of model versions, parameters and artifacts, but we own setup,
dependency maintenance and shutdown. It is different from paying an API per model.

The local TripoSR experiment already takes 32–35 seconds/image. The reason to rent
would be to evaluate a different GPU-oriented generator, not to solve current
TripoSR latency. Faster hardware alone is not evidence of better output geometry.

Runpod's [current price page](https://www.runpod.io/pricing), updated November 4,
lists a 24 GB RTX 4090 at $0.89/hour. Two hours would therefore be $1.78 in compute;
if that session produced five usable models, compute alone would average $0.356/model.
This is arithmetic, not a measured throughput/cost prediction. Storage, tax, setup,
downloads, failed attempts and any idle time affect actual cost per usable model.
Deployment price and availability must be rechecked before spending.

Runpod uses prepaid credit. Its [billing documentation](https://docs.runpod.io/accounts-billing/billing)
says new users can start with $10 and that credits are non-refundable. Stopped Pods
can retain billable storage. A test needs explicit budget/upload approval and a plan
to download results and terminate temporary resources after verification.

One plausible shape-only test is [Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2):
upstream documents 6 GB VRAM for shape and 16 GB for shape plus textures. A 24 GB GPU
is a candidate based on those requirements, not a verified environment for our run.
Exact checkpoint, software versions, licences and installation must be reviewed
before deployment. This does not extend the memory claim to every Hunyuan version.

Recommendation for discussion: retain rental as a fallback for models/settings
unavailable through a suitable service. Under the owner's approximately $1/model
simplicity rule, first finish the MakerLab walkthrough and assess a hosted comparison.
No backend decision has been made. Whether Oddie's current shape is useful enough
to refine is still a question for the owner; all raw meshes fail topology checks.
