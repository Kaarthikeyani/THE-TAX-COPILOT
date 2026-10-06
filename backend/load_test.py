"""Concurrent load test against the running server.  Run:  python load_test.py   (no arguments).
Optional env vars: BASE_URL, CONCURRENCY (default 10), REQUESTS (default 100). Writes load_test_result.json."""
import asyncio
import json
import os
import statistics
import time

import httpx

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8811")
CONCURRENCY = int(os.environ.get("CONCURRENCY", "10"))
REQUESTS = int(os.environ.get("REQUESTS", "100"))
SMS = "Rs.{a}.00 debited from A/c XX4821 on 02-10-26 to VPA swiggy@ybl (UPI Ref 1). Bal Rs 90,000"


async def timed(client, method, path, **kw):
    t = time.perf_counter()
    r = await client.request(method, BASE + path, **kw)
    return (time.perf_counter() - t) * 1000, r.status_code


async def worker(client, sem, method, path, results, **kw):
    async with sem:
        results.append(await timed(client, method, path, **kw))


def p95(vals):
    vals = sorted(vals)
    return round(vals[int(len(vals) * 0.95) - 1], 1) if vals else 0


async def main():
    out = {}
    async with httpx.AsyncClient(timeout=60) as client:
        for name, method, path, make in [
            ("/sms/ingest", "POST", "/sms/ingest", lambda i: {"json": {"text": SMS.format(a=100 + i)}}),
            ("/dashboard", "GET", "/dashboard", lambda i: {}),
            ("/dashboard/multi_period", "GET", "/dashboard/multi_period", lambda i: {}),
        ]:
            sem, results = asyncio.Semaphore(CONCURRENCY), []
            t0 = time.perf_counter()
            await asyncio.gather(*[worker(client, sem, method, path, results, **make(i)) for i in range(REQUESTS)])
            lat = [r[0] for r in results]
            out[name] = {"requests": REQUESTS, "concurrency": CONCURRENCY,
                         "errors": sum(1 for r in results if r[1] >= 400),
                         "mean_ms": round(statistics.mean(lat), 1), "p95_ms": p95(lat),
                         "rps": round(REQUESTS / (time.perf_counter() - t0), 1)}
    with open("load_test_result.json", "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
