# index/ — generated, never hand-edited

`entries.tsv` is rebuilt from the shards by `python tools/journal.py index`. If it disagrees with a
shard, the shard is right and the index is stale: run the command.

One row per entry, tab-separated:

| column | meaning |
|---|---|
| `kind` | handoff, lessons, pain, decisions, wins |
| `id_full` | the id to cite (may carry a collision suffix: `P46b`, `D41c`) |
| `num`, `suffix` | the same id split, so `sort -t$'\t' -k3,3n` orders by number |
| `date` | the entry's own date, or `-` for the undated old lessons |
| `host` | the machine that wrote it, or `-` |
| `status` | effective status: the marker, overridden by `../state/status.tsv` |
| `heading` | the entry's heading, verbatim |
| `file`, `line_start`, `line_end` | where the entry is, so a read is a slice and never a whole file |
| `hash` | sha1 of heading + body — how `audit` proves a merge lost nothing |

Useful greps:

```
grep -P '\tpain\t' entries.tsv | cut -f2,7            # every pain id and its heading
awk -F'\t' '$3==46' entries.tsv                        # everything numbered 46, in any kind
grep -P '\topen$' entries.tsv                          # (status is column 7) ids with no proof of done
```
