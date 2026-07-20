"""
Concurrent load test for the read-hot dashboard endpoints (/stats etc.).

The dashboard polls /api/v1/incidents/stats every 10s per open tab, so this is
the query the platform runs most often as tenants pile on. This script fires N
concurrent clients for a fixed duration and reports latency percentiles + error
rate, so you can see how the endpoint holds up before onboarding more tenants.

Auth: each simulated client needs a real Clerk session JWT (the backend derives
tenant_id from it). Pass one or more tokens; clients round-robin over them so a
single token can still drive load, or supply one token per tenant to exercise
distinct tenant_id scoping.

Usage (from the backend dir, against the live VM or localhost):
    .venv/bin/python scripts/loadtest_stats.py \
        --base-url https://sentinel-ai-vishxl.centralindia.cloudapp.azure.com \
        --path /api/v1/incidents/stats \
        --token "<clerk_jwt>" [--token "<another>"] \
        --concurrency 50 --duration 30

Requires: httpx (already a backend dep).
"""

import argparse
import asyncio
import time

import httpx


async def _worker(client, url, tokens, idx, deadline, latencies, errors):
    token = tokens[idx % len(tokens)]
    headers = {"Authorization": f"Bearer {token}"}
    while time.monotonic() < deadline:
        start = time.monotonic()
        try:
            resp = await client.get(url, headers=headers, timeout=30.0)
            latencies.append(time.monotonic() - start)
            if resp.status_code != 200:
                errors.append(resp.status_code)
        except Exception as exc:  # noqa: BLE001 — record, don't abort the run
            errors.append(repr(exc))


def _percentile(sorted_vals, pct):
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


async def _run(args):
    url = args.base_url.rstrip("/") + args.path
    latencies: list[float] = []
    errors: list = []
    deadline = time.monotonic() + args.duration

    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    async with httpx.AsyncClient(limits=limits, verify=not args.insecure) as client:
        workers = [
            _worker(client, url, args.token, i, deadline, latencies, errors)
            for i in range(args.concurrency)
        ]
        await asyncio.gather(*workers)

    total = len(latencies) + len(errors)
    ok = len(latencies)
    latencies.sort()
    print(f"\n── load test: {url}")
    print(f"   concurrency={args.concurrency} duration={args.duration}s tokens={len(args.token)}")
    print(f"   requests: {total}  ok: {ok}  errors: {len(errors)}")
    if total:
        print(f"   throughput: {total / args.duration:.1f} req/s")
    if latencies:
        print(f"   latency p50: {_percentile(latencies, 50) * 1000:.0f}ms")
        print(f"   latency p95: {_percentile(latencies, 95) * 1000:.0f}ms")
        print(f"   latency p99: {_percentile(latencies, 99) * 1000:.0f}ms")
        print(f"   latency max: {latencies[-1] * 1000:.0f}ms")
    if errors:
        sample = {}
        for e in errors:
            sample[e] = sample.get(e, 0) + 1
        print(f"   error breakdown: {dict(list(sample.items())[:10])}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", required=True)
    p.add_argument("--path", default="/api/v1/incidents/stats")
    p.add_argument("--token", action="append", required=True, help="Clerk session JWT; repeat for multiple tenants")
    p.add_argument("--concurrency", type=int, default=50)
    p.add_argument("--duration", type=int, default=30)
    p.add_argument("--insecure", action="store_true", help="skip TLS verification")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()
