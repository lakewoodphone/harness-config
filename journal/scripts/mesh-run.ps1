# mesh-run — the frozen path from docs/mesh/71-mesh-program.md §2.3.
#
# THIS FILE IS A POINTER, NOT THE IMPLEMENTATION. The dispatcher lives at
# packages/plugin-remote-fanout/bin/mesh-run.mjs, where the transport, the
# provider and the node table also live; the package is the deliverable and this
# shim exists so the path the program names works for whoever reads the program.
#
#   -Prompt "<task>" [-Node <name>] [-Children N] [-Workdir PATH] [-Json]
#   [-DshBin <path>] [-TimeoutMs <n>] [-Exclude a,b] [-NoWait]
#
# Exit codes are forwarded verbatim: 0 completed, 10 queued, 1 failed.
#
# Kept to two statements on purpose: anything with logic in it would drift from
# the implementation it points at.
& node (Join-Path $PSScriptRoot '..\packages\plugin-remote-fanout\bin\mesh-run.mjs') @args
exit $LASTEXITCODE
