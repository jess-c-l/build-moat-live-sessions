#!/usr/bin/env bash
for i in $(seq 1 11); do
 curl -s -o /dev/null -w "%{http_code}\n" \
   -X POST http://localhost:8000/api/qr/create \
   -H 'Content-Type: application/json' \
   -d '{"url":"https://example.com/'$i'"}'
done