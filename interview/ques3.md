# Mini Security Gateway --- New Interview Q&A (Part 2)

> Only questions about the material added after the previous notes: WAF,
> header filtering, multiple backends, round-robin and proposed health
> checks.

### Q1. What is a WAF?

A Web Application Firewall checks HTTP requests and blocks requests that
match suspicious or unwanted rules.

### Q2. What WAF rules did you add?

I added checks for suspicious paths, request bodies larger than 1 MiB,
and simple SQL injection/XSS patterns in query strings and request
bodies.

### Q3. What is the difference between 400, 403 and 413 in your WAF?

`400` means the path or `Content-Length` is invalid, `403` means a
suspicious pattern was detected, and `413` means the request body is too
large.

### Q4. How does the gateway check body size?

It checks the `Content-Length` header when available and then checks the
actual body length after reading the body.

### Q5. What are the limitations of your WAF?

It uses simple pattern matching, so it is not comprehensive. It can miss
attacks or reject valid input. Reading the whole body before checking
its actual size is also not enough for strong production memory
protection.

### Q6. Why remove hop-by-hop headers?

Hop-by-hop headers apply to one connection and should not automatically
be passed to another connection. The gateway filters these headers
before forwarding requests and responses.

### Q7. Why does the gateway remove `Authorization`?

The gateway validates the JWT itself. In the current design, it does not
pass the client's Authorization header to the backend.

### Q8. How many backend instances are configured?

Four: ports 8001, 8003, 8004 and 8005. The gateway runs on port 8002.

### Q9. How does round-robin work?

The gateway selects the next backend in the list, advances the index and
wraps around at the end.

### Q10. Why use an `asyncio.Lock` in the backend pool?

It protects the selection/index update so overlapping coroutines do not
update the shared selection state at the same time.

### Q11. What is a health check?

A request to a backend's `/health` endpoint to see whether it responds
with the expected status.

### Q12. Have health checks and failover been completed?

The health-check design and code update were discussed, but the
implementation and test results have not been confirmed. I would only
claim it as completed after verifying it in the code and testing a
stopped backend.

### Q13. What is the difference between health checking and retry-based failover?

Health checking periodically updates which backends appear healthy.
Retry-based failover handles a request failure by attempting another
backend. One does not automatically guarantee the other.

### Q14. What happens if a backend stops between health checks?

The gateway might still choose it based on stale health information.
That request can fail with `502` or `504`; retrying another healthy
backend would be a further improvement.

### Q15. What did you test for the WAF?

I confirmed that an XSS-style query was blocked with `403` and a request
body larger than 1 MiB was rejected with `413`.

### Q16. What is your next step?

Apply and test health-aware backend selection, then add retry-based
failover, automated tests, logging/metrics and Docker Compose.
