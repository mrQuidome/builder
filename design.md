# Functional Design: Unwalked Route Planner

## Version 7

------

## Core Purpose

A mobile app that plans walking routes actively avoiding paths the user has walked before, creating long-term route diversity. Supports circular routes and point-to-point routes. Global app, works anywhere in the world.

------

## Users

Walkers who want to explore their surroundings without repeating themselves.

------

## Authentication

Full authentication layer required:

- Registration with email and password, or via social login (Google, Apple)
- Login, logout
- Password reset
- Account deletion: immediate, with a confirmation step that clearly states deletion is immediate and permanent. Removes all user data including walk history, preferences, and payment status. Identical flow for email/password and social login users.

------

## Route Planning

### Route Modes

Three route modes are supported:

1. **Circular:** starts and ends at the same point. Scored for circularity and diversity.
2. **A to B:** starts at one point, ends at another. Diversity scored as normal. Circularity scored where relevant -- naturally fades as the straight-line distance between A and B approaches the requested walking distance.
3. **A to B shortest:** navigates from A to B along roughly the shortest path, within the shortest path margin, preferring unwalked edges within that constraint. Diversity scoring applied.

**Input from user:**

- Route mode
- Requested distance (km)
- Starting point: current GPS position (if available) or any point selected on the map, snapped to the nearest routable path
- End point (A to B and A to B shortest modes only): any point selected on the map, snapped to the nearest routable path
- Margin and shortest path margin are global settings, shown during planning as context

**Output:**

- A route matching the selected mode
- Total distance within requested distance ± margin (circular and A to B), or within shortest path ± shortest path margin (A to B shortest)
- Scored for circularity and diversity as weighted factors (circular and A to B modes), weighting is user-configurable

Planning always runs server-side. If the server is unreachable, the user receives a clear error message and planning is not possible.

**GPS unavailable:** if GPS is unavailable, the user can still plan using a manually selected starting point. During walking mode, no blue dot is shown. The app degrades gracefully.

------

## Circularity

A scoring factor weighted against the diversity penalty for circular and A to B routes. Weighting is controlled by a single slider between two extremes, visible in settings only for the developer account. Used for tuning purposes.

Circularity measures how evenly the route spreads around the geometric center of the route itself -- the center is computed from all waypoints including the starting point. A perfect circle scores maximum circularity. A route that goes out and back scores near zero.

Both circularity and diversity scores are normalized to the same scale before weighting is applied, so the slider has meaningful effect across its full range. Normalization strategy determined in technical design.

------

## No Route Found -- Escalation Strategy

When no valid route exists the planner escalates through these steps:

1. Retry with incrementally wider margin, up to the user's configured margin + 10 percentage points, hard ceiling of 100%. Increment size requires research during technical design.
2. If still no route: attempt a route that doubles back on a single segment once. The doubled segment is penalized as if walked twice. Last resort.
3. If still no route: inform the user clearly, suggest a different distance or starting point.

The user is informed whenever the margin was auto-widened or a turnaround was used.

------

## Route Diversity

The planner tracks every edge (path segment) the user has walked and the number of times.

**Penalty per edge = edge distance × Fibonacci(times walked)**

Fibonacci mapping (index = times walked):

| Times walked | Fibonacci multiplier |
| ------------ | -------------------- |
| 0            | 0                    |
| 1            | 1                    |
| 2            | 1                    |
| 3            | 2                    |
| 4            | 3                    |
| 5            | 5                    |
| 6            | 8                    |
| ...          | ...                  |

The planner minimizes total penalty weighted against circularity score.

------

## Walk Tracking

Every meter the user physically walks is recorded and counts toward history and free tier usage -- regardless of whether the full planned route was completed.

- Tracked on the mobile device via GPS trace, including in the background when the app is not in the foreground
- A walk is considered complete when the user arrives within GPS device accuracy of the starting point (circular) or end point (A to B modes)
- For A to B modes: if the endpoint is not auto-triggered, the user can also manually end the walk
- The user can manually end a walk early at any time after confirmation; the walked portion is fully synced to history
- If the app is interrupted (crash, GPS loss, app close), whatever was recorded up to that point is saved locally and uploaded when the app is opened again. If the app is never reopened, that walk data is lost; this is acceptable.
- Server stores per-user, per-edge walk counts
- Used in all future route planning for that user

**Web platform:** walk tracking is not available on web. The web platform supports planning and map viewing only.

------

## Mid-Walk Re-planning

The user can re-plan at any time during an active walk. The already-walked portion remains in history. The new route is planned from the current position as a fresh request.

All three route modes are available for re-planning. A circular re-plan produces a new loop starting and ending at the current position. An A to B or A to B shortest re-plan ends at a user-selected endpoint. The requested distance for the new route is entered fresh; the app does not suggest a distance based on what was already walked.

------

## App Modes

The app operates in two distinct modes:

- **Planning mode:** route planning, map with history layer visible
- **Walking mode:** active walk in progress, history layer hidden

Switching between modes is explicit. The history heatmap is only available in planning mode and cannot be toggled on during an active walk.

------

## Map Controls

Available in both modes:

- Free pan and zoom
- North reset button (reorients map to north)
- Center on position button (re-centers map on current GPS position)

**During walking mode:**

- Full planned route always visible as a line on the map
- Walked portion shown in a distinct color, unwalked portion ahead in another
- App vibrates once per minute while the user is off-route, based on GPS accuracy at that moment
- No turn-by-turn navigation; route line only

**GPS unavailable:** no blue dot shown; all other map functionality remains available.

------

## Dead Ends

- Configurable per user, default: off (dead ends avoided)
- When off: planner excludes paths leading to dead ends
- **Edge case:** if the starting point is in a dead end, the planner routes out of it regardless of the setting, then applies the dead end constraint for the remainder of the route

------

## User Path Preferences

Managed via a dedicated map dialog, accessible outside of planning mode as a global setting. Users tap paths to set preference.

Two levels:

- **Prefer not:** penalty multiplier of 10, or the user's own maximum single-walk count in their history -- whichever is higher
- **Block:** path treated as non-existent for that user

Both can be undone from the same map dialog. Before any walk history exists, prefer not uses multiplier 10.

------

## Map Visualization

**History layer (planning mode only):** paths colored using heatmap-style coloring by the user's walk count per edge, with a legend explaining the color scale. When no walk history exists, the layer is empty and a snackbar explains what the history layer will show once the user has walked.

**During an active walk:** the full planned route is always visible. The portion already walked is shown in a distinct color, separate from the unwalked portion ahead.

------

## Edge ID Stability

Edge IDs must remain stable across OSM data refreshes so walk history is preserved. Matching strategy determined in technical design. This is a v1 requirement.

------

## Settings Screen

User-configurable settings:

- **Margin:** distance tolerance for circular and A to B routes (0-100%)
- **Shortest path margin:** distance tolerance for A to B shortest routes (0-100%)
- **Dead ends toggle:** whether the planner avoids dead ends (default: off)
- **Circularity/diversity slider:** visible only when logged in with the developer account; used for tuning the weighting between circularity and diversity scoring

------

## Profile / Account Screen

Contains:

- Username
- Payment status and subscription management
- Account deletion

------

## Onboarding

On first run the app requests GPS permission, explaining why it is needed. The app degrades gracefully if permission is denied -- planning and map viewing remain available without a blue dot or GPS-based starting point. Walk tracking requires GPS permission.

------

## Freemium Model

- **Free tier:** planning is allowed as long as total walked distance is below 100km. Any route length is allowed regardless of how much free tier distance remains.
- **Paid tier:** €10/year, unlimited
- Remaining free tier distance is shown during planning mode
- A walk in progress when the limit is crossed can be completed
- After the limit: no new routes planned until payment. When the user opens planning mode after the limit is reached, they are prompted to upgrade.

------

## Global Coverage

Works anywhere in the world. OSM data loaded per region on demand, invisible to the user. Cross-border routing supported when a route crosses a country boundary.

------

## Technical Notes

- Server: Rust/Axum
- Client: Flutter (iOS, Android, web)
- Database: PostgreSQL with PostGIS and pgRouting
- Map data: OpenStreetMap
- Map tile server: self-hosted
- Authentication: JWT-based with social login via OAuth2/OIDC (Google, Apple)
- Payments: Mollie for web; Apple App Store and Google Play in-app purchase for mobile
- Push notifications: none required in v1
- Off-route detection threshold: GPS accuracy × 2 (or similar), to be determined in technical design
- App is English only in v1; codebase should be structured to support multilingual in future
- Planning requests are rate limited with increasing wait time per repeated rapid request
- Server retry behavior on connectivity failure to be determined in technical design

------

## Out of Scope

- Multi-user route sharing
- Walk history export
- Planning without server connection (starting point selection works without connectivity, planning itself requires connectivity)
- Walk tracking on web platform

------

## Open Questions

None.