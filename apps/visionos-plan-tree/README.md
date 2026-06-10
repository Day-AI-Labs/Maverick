# Maverick AR plan tree (visionOS scaffold)

A minimal SwiftUI + RealityKit visionOS app rendering a Maverick goal
forest as a 3D plan tree in a volumetric window: each goal is a small
sphere colored by status, parent links are thin connecting bars, and
gazing at a node + pinching shows its title/status card.

It consumes the same endpoint as the dashboard's WebGL `/plan-tree-3d`
page:

```
GET http://<your-host>:8765/api/v1/goal-tree
-> {nodes: [{id, parent_id, title, status, depth, x, y}], edges: [[parent, child]], count}
```

The server already computes a layered layout; this app maps `x`/`y` into
metres on the volume's X/Y plane and uses `depth` for Z so sibling layers
sit in front of one another.

**Build requirements (not possible in this repo's CI):** Xcode 16+ on
macOS with the visionOS SDK; an Apple Vision Pro or the visionOS
simulator. Create a visionOS App target named `MaverickPlanTree`, choose
the *Volume* window style, and add the two Swift files. Set
`MAVERICK_DASHBOARD_URL` (and `MAVERICK_DASHBOARD_TOKEN` if the dashboard
sets one) in the scheme's environment or the in-app settings.

**Honest scope:** this is the scaffold — model + fetch + RealityKit
entity assembly are written; it has not been run on Vision Pro hardware
(none is available to this repository). The geometry mapping and gesture
targets are the parts most likely to need on-device tuning, and they are
marked in the source.

Security model: the app talks only to YOUR dashboard host; include the
`Authorization: Bearer <MAVERICK_DASHBOARD_TOKEN>` header when the
dashboard sets one. Read-only — the app calls no mutating endpoint.
