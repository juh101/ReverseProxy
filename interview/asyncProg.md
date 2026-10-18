# Asyncio Basics --- Simple Notes and Interview Q&A

> This is a separate file for the latest topic only: `async`, `await`,
> `create_task`, `gather`, locks and FastAPI lifespan.

## 1. Async programming: the basic idea

Imagine starting a washing machine. While it runs, you can do something
else instead of standing and waiting. Async programming has a similar
idea: while a coroutine waits for a network response or a timer, the
event loop can run other ready tasks.

Asyncio usually gives concurrency on one event-loop thread. It does not
automatically mean CPU work runs in parallel on multiple cores.

## 2. What does `async def` mean?

``` python
async def say_hello():
    print("Hello")
```

`async def` defines a coroutine function. Calling it creates a coroutine
object; it does not immediately execute the function body. The coroutine
must be awaited or scheduled as a task.

``` python
await say_hello()
```

This runs it and waits for it to finish.

## 3. What does `await` mean?

`await` means: wait for this awaitable operation to complete before this
coroutine continues.

``` python
import asyncio

async def work():
    print("Started")
    await asyncio.sleep(2)
    print("Finished")
```

During the sleep, the current coroutine pauses. The event loop can run
other ready tasks.

Remember: - `await` pauses the current coroutine. - It does not
automatically stop the whole event loop. - Other tasks run only if there
are other tasks ready. - `await` alone does not automatically create
concurrent work.

## 4. `await` versus `asyncio.create_task()`

### `await`

``` python
await do_work()
print("Next line")
```

The current coroutine waits for `do_work()` to finish before printing
the next line.

### `create_task`

``` python
task = asyncio.create_task(do_work())
print("Next line")
await task
```

`create_task()` schedules the coroutine as a task, allowing the current
coroutine to continue without immediately waiting for the task to
finish. Later, `await task` waits for completion.

A task does not run forever by itself. It finishes when the coroutine
returns, raises an uncaught exception, or is cancelled. `create_task()`
needs a running event loop.

## 5. Why the gateway uses `create_task()`

``` python
async def health_check_loop(app):
    while True:
        await asyncio.sleep(5)
        await backend_pool.update_health(app.state.clients)
```

This loop repeats because it contains `while True`. It waits five
seconds, checks backend health and repeats.

The lifespan code schedules it with:

``` python
health_task = asyncio.create_task(health_check_loop(app))
```

If lifespan instead used `await health_check_loop(app)`, it would wait
for an endless loop and never reach `yield` during normal operation.
`create_task()` schedules the health loop while allowing startup to
continue.

When the gateway shuts down, `health_task.cancel()` requests that the
loop stop.

## 6. What is `asyncio.gather()`?

`asyncio.gather()` runs multiple awaitables concurrently and collects
their results.

Sequential example:

``` python
result1 = await check_backend(backend1)
result2 = await check_backend(backend2)
result3 = await check_backend(backend3)
```

Each check completes before the next starts.

Concurrent example:

``` python
results = await asyncio.gather(
    check_backend(backend1),
    check_backend(backend2),
    check_backend(backend3),
)
```

The checks can overlap. If each takes around one second, three checks
may take around one second in total under suitable conditions, instead
of around three seconds.

In the gateway:

``` python
results = await asyncio.gather(
    *(check(backend) for backend in self.backends)
)
```

-   `check(backend) for backend in self.backends` creates a coroutine
    for every backend.
-   `*` unpacks them into separate arguments.
-   `gather()` runs them concurrently and collects results.
-   `await` waits for those results.

The health-check function catches `httpx.RequestError` and returns
`False` for that failure. An uncaught exception in a gathered coroutine
can otherwise propagate to the caller.

## 7. What is `asyncio.Lock()`?

A lock protects shared data when multiple coroutines may read or update
it.

``` python
lock = asyncio.Lock()

async def update_data():
    async with lock:
        # Critical section: access/update shared data
        ...
```

-   `asyncio.Lock()` creates a lock.
-   `async with lock:` waits until the lock is available.
-   Only one coroutine at a time can enter the protected section using
    that lock.
-   The lock is automatically released when the block exits, including
    if an exception occurs.

In the gateway, the lock protects backend selection/index updates and
the update to the set of healthy backends. An `asyncio.Lock` coordinates
coroutines on the same event loop; it does not share a lock across
separate processes.

## 8. What is FastAPI lifespan?

Lifespan code runs during application startup and shutdown.

``` python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup code
    yield
    # Shutdown cleanup
```

-   Before `yield`: startup code.
-   While the lifespan context is active: FastAPI serves requests.
-   After shutdown: code after `yield` performs cleanup.

The gateway uses lifespan to create HTTP clients, check backend health,
schedule periodic health checks and clean up resources at shutdown.

## 9. Lifespan explained step by step

### A. Create reusable HTTP clients

``` python
app.state.clients = {
    backend: httpx.AsyncClient(timeout=10.0)
    for backend in BACKENDS
}
```

Creates one reusable HTTPX client per backend URL. The dictionary is
stored on the FastAPI application's state so routes can use the clients.

### B. Check backend health at startup

``` python
await backend_pool.update_health(app.state.clients)
```

Runs an initial health check and waits for the results before reaching
`yield`.

### C. Start periodic checks

``` python
health_task = asyncio.create_task(health_check_loop(app))
```

Schedules the repeating health-check loop without making startup wait
forever for it to finish.

### D. Let the app serve requests

``` python
try:
    yield
finally:
    ...
```

The application serves requests while the lifespan context is active.

### E. Stop the task and close clients

``` python
health_task.cancel()

try:
    await health_task
except asyncio.CancelledError:
    pass

for client in app.state.clients.values():
    await client.aclose()
```

`cancel()` requests task cancellation. `await health_task` waits for
cancellation to finish. `CancelledError` is handled because cancellation
is expected during shutdown. Each HTTP client is then closed to release
resources.

## 10. Quick comparison

  -----------------------------------------------------------------------
  Syntax                              Meaning
  ----------------------------------- -----------------------------------
  `async def`                         Defines a coroutine function

  `await`                             Waits in the current coroutine

  `asyncio.create_task()`             Schedules a coroutine as a task

  `asyncio.gather()`                  Runs multiple awaitables
                                      concurrently and collects results

  `asyncio.Lock()`                    Protects a shared section of code

  `asyncio.sleep(5)`                  Waits without blocking the event
                                      loop

  `yield` in lifespan                 Marks the point where the app can
                                      serve requests

  `cancel()`                          Requests task cancellation
  -----------------------------------------------------------------------

## 11. Interview questions and answers

### Q1. What is `async` in Python?

`async def` defines a coroutine function. Calling it creates a coroutine
object that must be awaited or scheduled.

### Q2. What does `await` do?

It waits for an awaitable operation to complete before the current
coroutine continues. Other ready tasks can run while it waits.

### Q3. Does `await` block the whole program?

Not necessarily. It pauses the current coroutine, while the event loop
can run other ready tasks.

### Q4. What is the difference between `await` and `create_task()`?

`await` waits for an operation to finish. `create_task()` schedules a
coroutine as a task so the current coroutine can continue before that
task finishes.

### Q5. Does `create_task()` make a task run forever?

No. It runs until its coroutine finishes, raises an uncaught exception
or is cancelled. The gateway's health loop repeats because it contains
`while True`.

### Q6. Why does the gateway use `create_task()`?

It schedules periodic health checks without stopping lifespan from
reaching `yield` and serving requests.

### Q7. What is `asyncio.gather()`?

It runs multiple awaitables concurrently and collects their results. The
gateway uses it to check several backends without checking them one by
one.

### Q8. What does `*` do in the `gather()` call?

It unpacks generated coroutines into separate positional arguments for
`gather()`.

### Q9. What is an `asyncio.Lock()`?

It coordinates access to shared data so only one coroutine at a time can
enter a protected section using that lock.

### Q10. Why use `async with lock`?

It waits for the lock and releases it automatically when the protected
block exits.

### Q11. Why does the backend pool need a lock?

Concurrent requests can select backends and update the round-robin index
at the same time. The lock protects the selection/update sequence and
health-set updates.

### Q12. What is FastAPI lifespan?

It handles application startup and shutdown, including resource
initialization and cleanup.

### Q13. Why does lifespan use `yield`?

Code before `yield` is startup code. The app serves requests while the
context is active, and code after it runs during shutdown cleanup.

### Q14. Why create HTTP clients in lifespan?

They can be reused across requests and closed cleanly when the
application shuts down.

### Q15. Why cancel the health-check task?

The task contains a repeating loop, so it should be stopped when the
gateway shuts down.

### Q16. Why await the task after calling `cancel()`?

`cancel()` requests cancellation. Awaiting the task lets cancellation
finish before the remaining resources are closed.

### Q17. Is asyncio the same as parallel processing?

No. Asyncio usually provides concurrency by switching between tasks
while they wait. It does not automatically run CPU-heavy work in
parallel across CPU cores.

### Q18. Explain the gateway health-check lifecycle.

"At startup, the gateway creates reusable HTTPX clients and checks
backend health. It schedules a periodic health-check task and reaches
`yield`, allowing FastAPI to serve requests. During shutdown, it cancels
the task and closes the clients."

## One-line revision

-   `async`: define a coroutine function.
-   `await`: wait in the current coroutine without necessarily blocking
    the event loop.
-   `create_task`: schedule work so the current coroutine can continue.
-   `gather`: run multiple awaitables concurrently and collect results.
-   `Lock`: protect shared data from overlapping coroutine updates.
-   `lifespan`: initialize resources at startup and clean them up at
    shutdown.
