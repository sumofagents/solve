# solve

Verifier-mediated bounded generation over real verified corpora.

The self-extending grammar experiment: point the architecture proven in [`manifold-destiny`](https://github.com/sumofagents/manifold-destiny) at a large verifiable corpus (mathlib) and produce verified theorems a human hadn't written.

## Status

Experimental. Architecture plan drafted in [`ARCHITECTURE.md`](ARCHITECTURE.md).

The trust boundary is strict:

```text
Language may propose / rank / explain / configure.
Language may not verify or retain truth.
Lean replay receipts are the retention gate.
```
