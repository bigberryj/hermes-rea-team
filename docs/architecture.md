# Architecture

Native Hermes plugin and standalone CLI share the static core. The core validates and privately snapshots explicitly staged input, invokes pinned REA with a minimal environment, retains canonical evidence, and optionally launches three sequential tool-free MiniMax worker processes through the installed Hermes runtime and existing reasoner profile. No MCP listener or scheduled daemon. Public tool results contain artifact handles, not source text.
