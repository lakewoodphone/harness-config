# 158 - VERIFICATION: did the website-comms-push-cron port work?

Captured automatically at 2026-10-11T21:45:01Z by a one-shot job, because the session that
made the port could not stay to watch its first tick.

## 1. did the ported job run?
```
2026-10-11T21:39:01Z	website-comms-push-cron	1	90	
```

## 2. did the monitor it was blocking go green?
```
2026-10-11T19:45:01Z	production-comms-freshness	1	2	
2026-10-11T20:00:01Z	production-comms-freshness	1	3	
2026-10-11T20:15:02Z	production-comms-freshness	1	1	
2026-10-11T20:30:01Z	production-comms-freshness	1	2	
2026-10-11T20:45:01Z	production-comms-freshness	1	2	
2026-10-11T21:00:02Z	production-comms-freshness	1	2	
2026-10-11T21:15:01Z	production-comms-freshness	1	1	
2026-10-11T21:30:02Z	production-comms-freshness	1	4	
```

## 3. its own log, if the first run created one
```
```

## VERDICT - read the two ledger blocks above
- pusher row present with rc=0 AND monitor rc=0  -> PORT VERIFIED.
- pusher rc=0 but monitor still rc=1             -> the diagnosis in 155 is INCOMPLETE; reopen it.
- pusher absent or rc!=0                         -> read block 3; rollback is
  crontab /root/crontab.before-website-comms-push-20261011T212901Z

# 158 - VERIFICATION: did the website-comms-push-cron port work?

Captured automatically at 2026-10-11T22:45:01Z by a one-shot job, because the session that
made the port could not stay to watch its first tick.

## 1. did the ported job run?
```
2026-10-11T21:39:01Z	website-comms-push-cron	1	90	
2026-10-11T22:09:02Z	website-comms-push-cron	1	90	
2026-10-11T22:39:01Z	website-comms-push-cron	0	9	
```

## 2. did the monitor it was blocking go green?
```
2026-10-11T20:45:01Z	production-comms-freshness	1	2	
2026-10-11T21:00:02Z	production-comms-freshness	1	2	
2026-10-11T21:15:01Z	production-comms-freshness	1	1	
2026-10-11T21:30:02Z	production-comms-freshness	1	4	
2026-10-11T21:45:01Z	production-comms-freshness	1	2	
2026-10-11T22:00:02Z	production-comms-freshness	1	3	
2026-10-11T22:15:02Z	production-comms-freshness	1	2	
2026-10-11T22:30:01Z	production-comms-freshness	1	3	[no stderr; rc=1 -- reason is on stdout or in the job's own log]
```

## 3. its own log, if the first run created one
```
```

## VERDICT - read the two ledger blocks above
- pusher row present with rc=0 AND monitor rc=0  -> PORT VERIFIED.
- pusher rc=0 but monitor still rc=1             -> the diagnosis in 155 is INCOMPLETE; reopen it.
- pusher absent or rc!=0                         -> read block 3; rollback is
  crontab /root/crontab.before-website-comms-push-20261011T212901Z

