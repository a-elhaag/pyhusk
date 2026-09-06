# Known limits

Read these before trusting an image.

- **Dynamic imports are invisible.** `importlib.import_module` with a computed string
  and `getattr`-based dispatch cannot be seen statically. Use `--include`.
- **Background and scheduled work is not reachable from the route graph.** An
  APScheduler job registered as `scheduler.add_job("jobs.reports:run")` is a string,
  not an import. Use `--include`, and review the slice for any service whose real work
  happens off the request path.
- **`Depends()` chains are resolved exactly, but only what FastAPI registered at
  import time.** A dependency injected at request time is invisible.
- **Routes added with Starlette's `add_route` get no dependency scan**, because
  FastAPI runs no injection for them. Their handler file is still included.
- **`if TYPE_CHECKING:` imports are included.** pyhusk over-includes rather than
  under-includes when it is unsure.
- **Verification is not integration testing.** It proves the container boots and
  serves the expected routes, nothing more.
- **Size reduction depends on services having genuinely different dependencies.** Run
  `pyhusk build <service> --compare` on your repo and believe the number, not the
  pitch.
