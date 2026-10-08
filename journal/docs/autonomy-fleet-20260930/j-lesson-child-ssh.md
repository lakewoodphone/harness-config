Measured 2026-09-30 from a mesh child placed on ZABZ-TECH, and independently confirmed by nine children
that failed the same way in one wave.

THE MEASUREMENT. A probe child was told to run exactly:
    ssh -o BatchMode=yes -o ConnectTimeout=10 secratary-ts hostname
Result, verbatim: it printed "secratary" — so the remote command RAN and its output came back — and then
the process did not exit. The tool call was killed at 45 seconds. [exit 1]

THE CORROBORATION. Nine children in the same wave (every audit whose brief needed the authority) died
with `the remote one-shot exited 4294967295 and produced no final message`, and their recorded stderr
tails are a diary of the same fight: one child wrote "hostname printed, then it hung"; another "Tailscale
shows secratary active with direct connection. But ssh hangs"; another started inventing alternative
hosts and IPs to get around it. Not one of them produced a report, and the four children whose briefs
needed NO remote access all produced complete reports. The correlation is total.

WHY IT MATTERS. It is not an ssh or network fault: the remote command executed and answered. The ssh
client fails to terminate inside this profile's shell, which behaves like the documented stdio boundary
for confined shells. Whatever the mechanism, the operational fact is what counts.

THE PATTERN THAT WORKS. Never brief a child to reach the authority itself.
    The manager collects the evidence with its own ssh calls, writes it to a file, and the child
    analyses the file.
Manager-side ssh is unaffected (this session has run dozens of them, foreground and batched, with no
hang). A child reading a file is unaffected. A child ssh-ing is dead in the water.

Also worth knowing from the same probe: a child CAN read a file at an absolute Windows path with its
read tool and with Get-Content, so handing a child a dump file is cheap. This is the first thing to check
on a new machine before planning any fleet that touches a remote host.
