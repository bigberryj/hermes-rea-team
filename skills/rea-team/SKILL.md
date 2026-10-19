---
name: rea-team
description: "Use when analyzing an authorized app with REA. Run static evidence and a bounded MiniMax review team."
---

# REA static-analysis team

Use only on artifacts Byron owns or is authorized to analyze. The installed integration is deliberately static-only, not the full REA MCP catalog.

## Invocation

- Tool `rea_inspect`: target (absolute staged path), kind `javascript` or `binary`, optional preview.
- Tool `rea_team`: the same plus question; makes three bounded MiniMax-M3 calls using the existing reasoner profile. No automatic provider fallback.
- Existing sessions without the new tools: run `~/.local/bin/hermes-rea-team` through terminal. Do not invent `/rea` or `/rea-team` slash commands.
- Terminal example: `hermes-rea-team team /home/byron/projects/rea-targets/my-app --kind javascript --question 'Explain search and its evidence-supported risks.'`

## Input and permission boundary

1. Ask for the precise artifact and investigation question if missing. Do not copy a working repository wholesale: .git, node_modules, secrets, symlinks and archives are not appropriate inputs.
2. Inputs must already be staged under `/home/byron/projects/rea-targets`. JavaScript input is an unpacked directory. No automatic browsing or network capture is enabled.
3. Review the files selected for analysis; filenames alone cannot detect secrets embedded in source. Explain that team mode sends bounded evidence to MiniMax. `inspect` mode is local; summarizing its evidence in the current chat also sends it to the current model.
4. Use preview/prepare first for real targets. Limits: 16 MiB/file, 64 MiB/tree, 2,000 entries, 32 levels. No symlinks/hardlinks/special files/secret-looking filenames/packed archives.
5. Execute the appropriate tool. Never bypass a rejection using raw REA, rename secret files to evade screening, or expand the allowlist without Byron's explicit approval.
6. Read the returned private `report.json` and role report artifacts with file tools, then summarize architecture, security and verification findings. Tool summaries deliberately omit source and model text.
7. Cite evidence IDs/paths; distinguish observed facts, hypotheses, and missing evidence. Models cannot prove runtime behavior. A completed team is three independent reviews, not a consensus or an autonomous implementation.

## Errors and lifecycle

- `binary_ready:false`: binary-layout provider dependencies are intentionally not installed; do not claim native decompilation works.
- Runs are content/question-addressed and cached; repeating the exact target/question does not silently spend another three calls. Failed/incomplete runs require operator-reviewed recovery; do not delete caches to retry automatically.
- One team at a time. Limits are three roles, one model iteration per role, up to 2,048 output tokens per role, bounded wall time. Authentication refresh/retry behavior inside Hermes/provider transport is distinct from role count; do not promise an exact billable-request count.
- REA/Node/Hermes API hashes are pinned. Upgrades deliberately fail closed until compatibility and hashes are reviewed; never regenerate pins just to suppress an error.
- These are application-level controls, not an OS sandbox or a guarantee that arbitrary parser input is harmless. No network listener, debugging, injection, device access, target execution, or automatic modification/deployment is provided.
