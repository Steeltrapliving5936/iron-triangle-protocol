# Local runtime binding

Status: **unconfigured**. This repository copy contains only the portable protocol and platform mappings. An installer may replace this file inside an installed skill with private local bridge and runtime-config bindings; that generated file must never be committed.

Without a configured binding, the skill may use a target platform's native task/session APIs when they are actually available. It must not substitute screen control, UI clicking, window focus, or typed UI automation for dispatch, delivery acknowledgement, approval, stop, or crash recovery. Unsupported automatic transport is a disclosed degraded mode or **open question**.
