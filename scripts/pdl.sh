#!/bin/bash
# Parallel ranged HTTP download (used for the large public Amazon S3 files).
# Usage: scripts/pdl.sh URL OUT SIZE PARTS
URL=$1; OUT=$2; SIZE=$3; P=${4:-8}
CH=$(( (SIZE + P - 1) / P ))
for i in $(seq 0 $((P-1))); do
  S=$((i*CH)); E=$((S+CH-1)); [ $E -ge $SIZE ] && E=$((SIZE-1))
  ( until curl -s -f -r $S-$E -o "$OUT.part$i" "$URL" && [ "$(stat -c %s "$OUT.part$i")" -eq $((E-S+1)) ]; do sleep 2; done ) &
done
wait
cat $(for i in $(seq 0 $((P-1))); do echo "$OUT.part$i"; done) > "$OUT" && rm -f "$OUT".part*
echo "$OUT $(stat -c %s "$OUT") expected $SIZE"
