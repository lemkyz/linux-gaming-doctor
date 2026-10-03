# P05 — Display + Wayland Diagnostic Engine

P05 maps the Linux gaming display path without changing compositor, monitor or game configuration.

The same symptom can come from very different boundaries: a physical DRM mode, KDE/GNOME logical scaling, XWayland, a native Wayland client, Gamescope, HDR/VRR state or a game selecting the wrong output. P05 therefore records these layers separately instead of treating “display” as one setting.

P05 is strictly read-only.

## Collected evidence

- session type and desktop family without emitting raw environment values;
- Wayland/X11 socket-presence booleans and XWayland process presence;
- physical DRM connectors, connection/enabled state and advertised modes;
- EDID presence only — EDID payloads and display serials are never collected;
- KDE output state from `kscreen-doctor` when available;
- XRandR state as a fallback/secondary view;
- active resolution, refresh, scale and fractional-scaling state when the compositor exposes them;
- HDR/VRR state when exposed by the compositor;
- Gamescope presence/version;
- compositor version when safely queryable.

## Important interpretation rule

Fractional scaling, mixed refresh rates, HDR and VRR are **context**, not automatic faults. P05 does not label a valid multi-monitor setup as broken just because outputs differ.

A finding is emitted only for evidence such as an implausibly low active refresh, an impossible scale, a session/socket contradiction, or missing compositor-level output observability.

## Example findings

- `WAYLAND_SESSION_WITHOUT_SOCKET`
- `X11_SESSION_WITHOUT_DISPLAY`
- `DISPLAY_REFRESH_IMPLAUSIBLY_LOW`
- `DISPLAY_SCALE_IMPLAUSIBLE`
- `WAYLAND_COMPOSITOR_OUTPUT_STATE_UNAVAILABLE`

No P05 finding mutates the machine.
