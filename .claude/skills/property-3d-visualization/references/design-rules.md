# Step 3 — Design rules: functional, realistic, space-efficient

A redesign passes only if someone could actually live in it. Check every layout against these
numbers **in plan view before rendering**. Values are comfortable residential targets; the minimum
is in brackets. Adapt to local accessibility rules (e.g. French PMR) when the brief requires them.

## Locks (never changed by a redesign)

Walls, openings and their positions, ceiling height, beams and columns, radiators, sockets and
switches (unless the brief includes electrical work), plumbing positions (kitchen sink, WC, shower),
windows' clear light. A redesign that needs one of these moved is presented as a separate
**renovation proposal** with the change named, never slipped into a staging image.

## Circulation

| Situation | Clear width |
|---|---|
| Main path through a room (entry → living → kitchen) | 0.90 m (0.80) |
| Secondary path, between furniture | 0.75 m (0.60) |
| In front of a door, on the swing side | the full swing arc clear + 0.10 m |
| Wheelchair turning (if required) | Ø 1.50 m |
| Corridor | 0.90–1.00 m |

## Living room

| Rule | Value |
|---|---|
| Sofa to coffee table | 0.40–0.45 m |
| Coffee table length | ≈ 2/3 of the sofa length |
| Seating distance to TV | 1.2–1.6 × screen diagonal for 4K (a 65" TV → 2.0–2.6 m) |
| TV centre height | ≈ seated eye height, 1.0–1.1 m |
| Conversation group | seats within ~2.5–3.0 m of each other |
| Rug | front legs of all seating on it; 0.20–0.45 m of floor visible to walls |
| Sofa in front of a radiator | leave ≥ 0.15–0.20 m, and prefer not to |

## Dining

| Rule | Value |
|---|---|
| Table edge to wall/obstacle, chairs used | 0.90 m (0.75) |
| Table edge to wall, circulation behind seated person | 1.10–1.20 m |
| Width per diner | 0.60 m |
| Table sizes | 4 p: 1.20 × 0.80 m / Ø 1.00 m; 6 p: 1.80 × 0.90 m |
| Pendant over table | bottom 0.70–0.80 m above the tabletop |

## Kitchen

| Rule | Value |
|---|---|
| Aisle between runs, one cook | 1.00–1.20 m (0.90) |
| Island clearance | 1.00–1.20 m all round |
| Work triangle (sink–hob–fridge) | total 4.0–7.0 m, no leg < 1.2 m |
| Landing space beside hob/sink | ≥ 0.40 m |
| Bar stool | 0.60 m per stool; worktop overhang 0.25–0.30 m |

## Bedroom

| Rule | Value |
|---|---|
| Around the bed, sides used | 0.60–0.70 m (0.50) |
| Foot of bed to wall/furniture | 0.70–0.90 m |
| In front of a wardrobe | 0.90 m (swing doors: door width + 0.30 m) |
| Bed sizes (FR) | 140 × 190/200, 160 × 200, 180 × 200 cm; single 90 × 190 |
| Bedside table top | ≈ mattress top height ± 0.05 m |

## Bathroom and storage

| Rule | Value |
|---|---|
| In front of washbasin / WC / bath | 0.70 m (0.60) |
| WC axis to side wall | ≥ 0.40 m |
| Wardrobe depth | 0.60 m (hangers) |
| Shelving depth | 0.30–0.40 m |
| Desk | 1.20 × 0.60 m min; chair zone 0.90 m behind |

## Windows, radiators, sockets

- Do not block windows with tall furniture; keep blinds and window leaves operable (casement swing ~ half the window width inward).
- Keep ≥ 0.15 m in front of radiators, and nothing tall directly in front of them.
- Place lamps, TV, desks, bedside tables where the sockets actually are (from the dossier), or show the cable.

## Lighting layers (every room)

- **Ambient:** ceiling point, pendant or indirect cove (existing ceiling points first).
- **Task:** reading lamp at the sofa, kitchen under-cabinet strips, desk lamp, bedside lamps.
- **Accent:** picture lights, shelf lighting, a lamp in a dark corner.
- Colour temperature 2700–3000 K for living spaces, 3000–4000 K for kitchen task light. One temperature per room.

## Scale sanity for imported assets

After importing any furniture asset, print its dimensions and compare to the catalogue size:

```python
import bpy
for o in bpy.data.collections["COL_Furniture_Proposed"].all_objects:
    if o.type == "MESH":
        print(o.name, [round(v, 3) for v in o.dimensions])
```

Common real sizes: 3-seat sofa 2.0–2.3 × 0.90–1.00 × 0.80–0.85 m (seat 0.42–0.45 m); armchair
0.75–0.90 m wide; dining chair seat 0.45 m, back 0.80–0.90 m; coffee table 0.40–0.45 m high;
sideboard 0.75–0.85 m high; bookcase shelf spacing 0.30–0.35 m.
