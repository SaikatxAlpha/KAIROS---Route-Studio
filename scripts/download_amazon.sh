#!/bin/bash
# Download the Amazon Last Mile Routing Research Challenge training inputs
# (public S3 bucket, no AWS account needed; CC BY-NC 4.0). ~2.3 GB.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=data/raw/amazon
mkdir -p "$OUT"
B=https://amazon-last-mile-challenges.s3.us-west-2.amazonaws.com/almrrc2021
T=$B/almrrc2021-data-training/model_build_inputs
curl -fsS -o "$OUT/License.txt" "$B/License.txt"
curl -fsS -o "$OUT/Readme.txt" "$B/Readme.txt"
for f in route_data.json actual_sequences.json; do
  [ -f "$OUT/$f" ] || curl -fS -o "$OUT/$f" "$T/$f"
done
for f in package_data.json travel_times.json; do
  if [ ! -f "$OUT/$f" ]; then
    size=$(curl -sI "$T/$f" | tr -d '\r' | awk 'tolower($1)=="content-length:"{print $2}')
    bash scripts/pdl.sh "$T/$f" "$OUT/$f" "$size" 12
  fi
done
echo "Amazon data ready in $OUT"
