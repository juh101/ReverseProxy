# Rev Proxy --- Latest Interview Questions and Answers

These questions cover the latest work: a separate backend `/admin`
endpoint protected by gateway JWT/RBAC checks, and an in-memory Token
Bucket rate limiter.

## 1. What is the role of the gateway in this project?

The gateway is the entry point for client requests. It validates JWTs,
checks authorization for protected routes, applies rate limiting,
forwards allowed requests to the backend, and handles upstream errors
such as connection failures and timeouts.

## 2. Why did you create `/admin` in the backend as well as the gateway?

The backend's `/admin` endpoint contains the demo functionality and
returns the admin response. The gateway's dedicated `/admin` handler
performs authentication and authorization first, then forwards the
authorized request to the backend. This demonstrates the gateway acting
as a security layer in front of a backend service.

## 3. What happens when an admin calls `/admin`?

The client sends a Bearer JWT to the gateway. The gateway validates the
token, verifies that its role is `admin`, checks the rate limit, and
then calls the backend's `/admin` endpoint. The backend response is
returned through the gateway to the client.

## 4. What is the difference between authentication and authorization?

Authentication checks who the requester is, or whether their
credentials/token are valid. Authorization checks what that
authenticated requester is allowed to do. In this project, JWT
validation is authentication, and checking `role == "admin"` for
`/admin` is authorization.

## 5. What is the difference between HTTP 401 and 403?

-   `401 Unauthorized`: the token is missing, invalid, or expired.
-   `403 Forbidden`: the token is valid, but the role does not have
    permission for the requested operation.

For example, a normal user's valid token gets `403` when accessing
`/admin`.

## 6. Why is `/admin` a separate gateway route?

It makes the protected route and its authorization logic explicit. It is
declared before the catch-all route so FastAPI can match `/admin` to the
dedicated handler. Other paths can continue to use the catch-all proxy
handler.

## 7. What is a catch-all route?

A catch-all route such as `/{path:path}` can match many paths. In this
project it allows the gateway to handle paths like `/whoami` and
`/api/data` without defining a separate gateway route for every backend
path. It authenticates the request, applies the rate limit, and forwards
allowed requests.

## 8. What is a Token Bucket rate limiter?

It is an algorithm for controlling request rates. Each client has a
bucket containing a limited number of tokens. An allowed request
consumes one token. Tokens are replenished over time. If no token is
available, the request is rejected until a token is replenished.

## 9. What is the rate-limiter configuration in this project?

The current configuration has a capacity of 10 tokens, starts a new
client bucket with 10 tokens, and replenishes one token every 10
seconds. Each allowed request consumes one token. If the bucket is
empty, the gateway returns `429 Too Many Requests`.

## 10. Why use a bucket capacity of 10?

It allows a short burst of up to 10 requests for a new client while
still limiting sustained traffic. This is a configurable demo value, not
a universal production limit.

## 11. What happens after the first 10 requests?

If the client consumes all 10 tokens before any refill occurs, the next
request is rejected with `429`. One token becomes available after each
completed 10-second refill interval, up to the maximum capacity of 10.

## 12. Why use `time.monotonic()`?

The limiter needs elapsed time to calculate token refills.
`time.monotonic()` is designed for measuring elapsed durations and is
not affected by changes to the system wall clock.

## 13. Why use `asyncio.Lock`?

Multiple asynchronous requests can try to inspect and modify the same
bucket at nearly the same time. The lock ensures that only one coroutine
at a time performs the bucket update within that Python process, helping
prevent incorrect token counts.

## 14. What does `allow_request()` return?

It returns `True` when a token is available and consumed, and `False`
when the bucket is empty. The gateway uses that result to decide whether
to continue processing or return HTTP 429.

## 15. Why use `min(capacity, tokens + tokens_to_add)`?

It ensures the bucket never holds more tokens than its configured
capacity. Even if enough time passes for many tokens to be replenished,
the token count is capped at 10.

## 16. Why identify clients by IP address?

The initial implementation uses `request.client.host` as a simple way to
separate clients. This is easy to test locally. However, users sharing a
public IP may share a bucket, and proxy deployments may need trusted
proxy configuration or a different identity key.

## 17. Is this rate limiter production-ready?

Not yet. Buckets are in memory, so restarting the gateway resets them.
Separate worker processes or gateway replicas don't share state. A
production deployment may use a shared store such as Redis, carefully
configured client identity, and monitoring. The login endpoint is also
not currently rate-limited.

## 18. What does HTTP 429 mean?

`429 Too Many Requests` means the client exceeded the rate limit. In
this project, it means the client's bucket had no tokens available, so
the gateway rejected the request before forwarding it to the backend.

## 19. What is the purpose of the `Retry-After` header?

It tells the client how long to wait before retrying. The current
implementation sends a fixed value of 10 seconds. This is a simple hint
and does not calculate the exact time remaining until the next token is
available.

## 20. How do 502 and 504 differ?

-   `502 Bad Gateway`: the gateway could not communicate with the
    backend, for example due to a connection failure.
-   `504 Gateway Timeout`: the backend request exceeded the gateway's
    configured timeout.

These errors are returned by the gateway when an upstream request fails.

## 21. Does the gateway forward requests that fail authentication, authorization, or rate limiting?

No. A missing/invalid token gets rejected during authentication, a
non-admin token gets rejected for `/admin`, and a request with an empty
rate-limit bucket gets `429`. These rejected requests do not reach the
backend.

## 22. Does the project support database-backed multiple users?

Not currently. Database implementation was deferred. The current login
mechanism uses configured demo credentials. Supporting many independent
accounts would require an account store and secure password-hash
verification.

## 23. What are the current limitations?

The rate limiter is in-memory and per process, keys buckets by client
IP, does not limit `/auth/login`, and uses a fixed `Retry-After` value.
The admin endpoint is a demo endpoint. WAF filtering, multi-backend load
balancing, health checks/failover, structured logging, metrics,
automated tests, and Docker Compose are still planned.

## 24. Give a concise project explanation for an interview.

"I built a FastAPI reverse-proxy gateway that validates JWTs, applies
role-based access control to an admin route, and forwards authorized
requests to a backend service. I also implemented an in-memory Token
Bucket rate limiter with a capacity of 10 tokens and a refill rate of
one token every 10 seconds. Requests without available tokens receive
HTTP 429, while upstream connection failures and timeouts are handled
with 502 and 504 responses."

## 25. What would you implement next?

The planned next steps are WAF/request filtering, load balancing across
multiple backend instances, health checks and failover, structured
logging and metrics, automated tests, and Docker Compose. These are not
yet implemented.
