# Acceptance Test Plan: Unwalked Route Planner

**Scope**: End-to-end acceptance testing of the generated Unwalked Route Planner application.
**Executor**: Human tester — no automation required.
**Primary platform**: Web browser. Mobile-specific tests are marked **[MOBILE ONLY]**.

---

## Conventions

- **Check:** inline verification checkpoint — stop and confirm before continuing.
- `fixed-width` = exact value to type or exact command to run.
- Steps are numbered; sub-items under a step are observations to make at that point.
- Prepare the test accounts listed in the Preconditions before starting.

---

## Preconditions

Complete all of the following before starting any test.

### System checks

Run these commands on the server and confirm each result:

```
curl -s http://localhost:3000/health
```
**Check:** response body contains `ok` or `healthy`; HTTP status is `200`.

```
systemctl is-active postgresql
systemctl is-active nginx
systemctl is-active martin
systemctl is-active unwalked-api
```
**Check:** all four print `active`.

```
psql -U unwalked_app -d unwalked -c "SELECT COUNT(*) FROM edges;"
```
**Check:** result is a number greater than zero. If zero, OSM data has not been loaded — load it before continuing.

Open the app URL in a browser.
**Check:** the app loads. A map is visible within a few seconds. No blank screen, no console errors indicating a missing build.

### Test accounts to create

Create these accounts before running tests. Use the registration flow in the app or insert directly via the API.

| Label | Email | Password | Notes |
|---|---|---|---|
| **Account A** | `tester+a@example.com` | `TestPass1!` | Primary test account, starts fresh |
| **Account B** | `tester+b@example.com` | `TestPass2!` | Secondary account for deletion test |
| **Account DEV** | As configured in server env | As configured | Developer account for slider test |

### OSM test area

Identify a geographic area where OSM data is loaded. Pan to it and note approximate coordinates — you will use it as the starting point for route planning tests. A residential neighbourhood with a mix of streets and some dead ends works best.

---

## Test Area 1 — Onboarding

**[MOBILE ONLY]** — run these on a physical iOS or Android device with a fresh install.

---

### T1.1 — Onboarding screen appears on first launch

**Setup:** uninstall any existing version of the app from the device. Confirm the app is not installed.

1. Install the app (deploy the Flutter build to the device).
2. Tap the app icon to launch it.
   - **Check:** the app opens to an onboarding screen — NOT the login or map screen.
3. Read the onboarding screen text.
   - **Check:** the text explains why GPS permission is needed. It mentions walking and/or route tracking specifically. It does not ask for permission yet — it explains first.
4. **Check:** a button is present to proceed (labelled something like "Continue", "Grant Permission", or "Get Started").

**Pass:** onboarding screen appears with explanation and a call-to-action button before any permission dialog.

---

### T1.2 — Denying GPS permission degrades gracefully

**Setup:** continue from T1.1 (still on the onboarding screen).

1. Tap the proceed/grant button on the onboarding screen.
   - **Check:** the OS permission dialog appears (iOS: "Allow [App] to use your location?" / Android: location permission dialog).
2. Tap **Deny** (or "Don't Allow" on iOS).
   - **Check:** no crash. The app does not hang.
3. **Check:** the app navigates forward — either to the login screen or directly to the map screen (depending on whether login is required at this point).
4. If the login screen appears, log in as Account A.
5. Once on the main map screen, look at the map for 10 seconds.
   - **Check:** there is NO blue dot anywhere on the map.
6. Tap somewhere on the map to select a starting point.
   - **Check:** a starting point marker appears where you tapped. No error message about GPS.
7. Select a route mode and distance, then tap Plan.
   - **Check:** route planning proceeds normally. Planning does not require GPS.
8. **Check:** at no point does the app show an error banner or dialog complaining about missing GPS permission.

**Pass:** app works fully for planning without GPS. No blue dot. No error messages.

---

### T1.3 — Granting GPS permission shows the blue dot

**Setup:** uninstall and reinstall the app to reset permission state (or reset location permission in device settings for the app).

1. Launch the app fresh.
2. Proceed through the onboarding screen.
3. When the OS permission dialog appears, tap **Allow** (or "Allow While Using App" on iOS).
   - **Check:** no crash.
4. Log in as Account A if prompted.
5. Once on the map screen, wait up to 30 seconds.
   - **Check:** a blue dot appears on the map. It is positioned near your actual physical location.
6. Physically move a few metres.
   - **Check:** the blue dot moves to track your new position (may take a few seconds).

**Pass:** blue dot appears and tracks position after granting permission.

---

## Test Area 2 — Authentication

Web browser unless noted. Start logged out for each test (use private/incognito windows to avoid session bleed between tests).

---

### T2.1 — Register a new account with email and password

**Setup:** open the app in a private browser window. No account logged in.

1. On the welcome/login screen, find and tap the **Register** link or button.
   - **Check:** you land on a registration form with fields for email, password, and possibly username.
2. Enter:
   - Email: `tester+a@example.com`
   - Password: `TestPass1!`
   - Username (if present): `TesterA`
3. Tap the **Register** / **Create account** button.
   - **Check:** no immediate error appears on the form fields (no "invalid email" or "password too short" for these valid values).
4. Wait for the network request to complete.
   - **Check:** the app navigates away from the registration screen.
   - **Check:** you land on the main planning screen (map is visible).
   - **Check:** you are logged in — a user indicator (username, avatar, or profile icon) is visible somewhere in the UI.

**Pass:** account created, user automatically logged in, lands on planning screen.

---

### T2.2 — Registering with a duplicate email is rejected

**Setup:** continue in the same browser session (logged in as Account A), or open a new private window.

1. Navigate to the registration screen.
2. Enter:
   - Email: `tester+a@example.com` (same email as T2.1)
   - Password: `AnotherPass1!`
3. Tap **Register**.
4. Wait for the response.
   - **Check:** an error message appears. It indicates the email is already registered (e.g. "An account with this email already exists" or "Email already in use").
   - **Check:** you remain on the registration screen — no navigation away.
   - **Check:** no second account was created. Verify by logging in with `TestPass1!` (original password) — it must still work.

**Pass:** duplicate registration rejected with a clear message; original account unaffected.

---

### T2.3 — Log in with correct credentials

**Setup:** open a private browser window, not logged in.

1. On the login screen, enter:
   - Email: `tester+a@example.com`
   - Password: `TestPass1!`
2. Tap **Log in** / **Sign in**.
   - **Check:** the app navigates to the planning screen.
   - **Check:** a user indicator is visible confirming you are logged in as Account A.

**Pass:** login succeeds and lands on planning screen.

---

### T2.4 — Login with wrong password is rejected

**Setup:** logged-out state.

1. On the login screen, enter:
   - Email: `tester+a@example.com`
   - Password: `WrongPassword99!`
2. Tap **Log in**.
   - **Check:** an error message appears (e.g. "Incorrect email or password" or "Invalid credentials").
   - **Check:** you remain on the login screen. You are NOT logged in.
3. Try again with an email that does not exist: `nobody@nowhere.invalid`, password `anything`.
   - **Check:** the same generic error message appears. The error does NOT say "email not found" (to avoid account enumeration). It says the same message as wrong password.

**Pass:** wrong credentials rejected with a generic, non-leaking error message.

---

### T2.5 — Password reset flow

**Setup:** you need access to the email inbox for `tester+a@example.com`. If using a real email address, ensure you can receive emails. If the server is configured with a test SMTP server (e.g. Mailhog at `localhost:8025`), open that interface now.

1. On the login screen, tap the **Forgot password** link.
   - **Check:** you land on a password reset request screen with an email field.
2. Enter `tester+a@example.com` and tap **Send reset link** (or similar).
   - **Check:** a confirmation message appears (e.g. "If an account exists for this email, a reset link has been sent"). The message is shown regardless of whether the email exists.
   - **Check:** you are NOT logged in yet.
3. Enter a non-existent email `noone@invalid.test` and tap send again.
   - **Check:** the exact same confirmation message appears. No "email not found" error.
4. Open the email inbox for `tester+a@example.com`. Find the password reset email.
   - **Check:** the email arrived. It contains a link or token.
5. Click the reset link.
   - **Check:** you land on a "Set new password" screen.
6. Enter new password: `NewPass99!` in both the password and confirm-password fields.
7. Tap **Set password** / **Confirm**.
   - **Check:** a success message appears (e.g. "Password updated. You can now log in.").
8. Navigate to the login screen. Enter:
   - Email: `tester+a@example.com`
   - Password: `NewPass99!`
9. Tap **Log in**.
   - **Check:** login succeeds. You reach the planning screen.
10. Log out. Attempt login with the OLD password `TestPass1!`.
    - **Check:** login fails. The old password no longer works.
11. Reset the password back to `TestPass1!` (repeat steps 1–9) so subsequent tests can use the original credentials.

**Pass:** reset email sent; new password accepted; old password rejected.

---

### T2.6 — Google social login

**Precondition:** `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` are set to real values in the server config. You have a Google account available for testing.

1. Open the app in a private browser window (logged out).
2. On the login screen, find and tap **Continue with Google**.
   - **Check:** the browser opens a Google account selection or OAuth consent screen. You are NOT redirected to a broken URL.
3. Select your Google account and approve the OAuth consent.
   - **Check:** you are redirected back to the app.
   - **Check:** you land on the planning screen, logged in.
   - **Check:** the profile area reflects the Google account name or email.
4. Log out.
5. Tap **Continue with Google** again with the same Google account.
   - **Check:** you are logged in to the same Unwalked account — not prompted to create a new one.

**Pass:** Google login creates an account and allows repeat login to the same account.

---

### T2.7 — Apple social login

**[MOBILE ONLY — iOS only]**

**Precondition:** Apple credentials configured in server. You have an Apple ID available.

1. On the login screen, tap **Continue with Apple**.
   - **Check:** the system "Sign in with Apple" sheet appears (Face ID / passcode prompt on iOS).
2. Authenticate with your Apple ID.
   - **Check:** you return to the app after authentication.
   - **Check:** you are logged in and land on the planning screen.

**Pass:** Apple login works end-to-end on iOS.

---

### T2.8 — Logout

**Setup:** logged in as Account A.

1. Navigate to the **Profile** screen (look for a profile icon, avatar, or "Account" tab in the navigation).
2. Scroll to find a **Log out** button.
3. Tap **Log out**.
   - **Check:** you are navigated to the login/welcome screen immediately.
   - **Check:** you are NOT on the planning screen. No user indicator visible.
4. Close and reopen the browser tab.
   - **Check:** the app shows the login screen again — the session was not persisted after logout.

**Pass:** logout immediately ends the session and returns to the login screen.

---

### T2.9 — Account deletion: immediate, permanent, full data purge

**Setup:** log in as Account B (`tester+b@example.com` / `TestPass2!`). This account will be permanently deleted — do not use Account A for this test.

First, give Account B some history so you can verify purge:

1. While logged in as Account B, plan one circular route (any area, any distance).
   - **Check:** a route appears on the map.

Now delete the account:

2. Navigate to the **Profile** screen.
3. Find the **Delete account** option (may be in a "Danger zone" section or similar).
4. Tap it.
   - **Check:** a confirmation dialog appears. Read it carefully:
     - **Check:** the dialog explicitly states deletion is **immediate**.
     - **Check:** the dialog explicitly states deletion is **permanent** (no recovery).
     - **Check:** the dialog lists what will be deleted: walk history, preferences, payment status (or equivalent wording).
   - **Check:** there are two options: confirm deletion and cancel. Cancel is clearly distinguished.
5. Tap **Cancel**.
   - **Check:** the dialog closes. You are still logged in as Account B. Nothing was deleted.
6. Tap **Delete account** again and this time tap **Confirm** (or the destructive confirmation button).
   - **Check:** the deletion is processed (brief loading indicator is acceptable).
   - **Check:** you are immediately logged out and returned to the login screen. No further interaction required.
7. Attempt to log in with Account B credentials: `tester+b@example.com` / `TestPass2!`.
   - **Check:** login fails. Error says account not found or credentials invalid.
8. Register a new account using the same email `tester+b@example.com`.
   - **Check:** registration succeeds — the email is free to use again.
   - **Check:** the new account has zero walk history. The old walk from step 1 is gone.
9. Delete this freshly re-created account (or keep it — it is now blank).

**Pass:** deletion is immediate; login afterwards fails; same email can be re-registered; no data carries over.

---

## Test Area 3 — Planning Mode UI

Log in as Account A for all tests in this area.

---

### T3.1 — Planning mode is the default after login

1. Log in as Account A.
   - **Check:** after login, you land directly on the planning screen. You are not asked to choose a mode first.
2. Examine the screen:
   - **Check:** a map is visible and fills most of the screen.
   - **Check:** a planning panel or bottom sheet is visible, containing at minimum: a route mode selector, a distance input, and a "Plan" button (or equivalent).
   - **Check:** the heatmap layer is active — either showing coloured edges (if Account A has walk history) or visually empty but present.
   - **Check:** there is no "End walk" button or active-walk UI on screen. Walking mode is not active.

**Pass:** planning mode is the default landing screen.

---

### T3.2 — Heatmap empty-state snackbar for a new account

**Setup:** log in with a fresh account that has no walk history (create one if needed: `tester+fresh@example.com` / `TestPass1!`).

1. Reach the planning screen as the fresh account.
   - **Check:** the map is visible but no coloured edges are shown (heatmap layer is empty).
2. Wait a few seconds or interact with the map (pan slightly).
   - **Check:** a snackbar, banner, or tooltip message appears explaining that the history layer will show walked paths once the user has walked. The message must be visible without the user needing to find it — it surfaces automatically.

**Pass:** empty heatmap state is communicated proactively via a visible message.

---

### T3.3 — Remaining free tier distance is displayed

**Setup:** logged in as Account A (free tier, no or few walks completed).

1. On the planning screen, scan all visible UI elements.
   - **Check:** a free-tier remaining distance indicator is visible. It shows a number in km (e.g. "100.0 km remaining" for a fresh account, or less if some walks are recorded). The unit is clearly labelled.
   - **Check:** the number is plausible given Account A's walk history (should be ≤ 100 km).

**Pass:** remaining free tier distance shown in planning mode.

---

### T3.4 — Map pan and zoom

**Setup:** planning screen with map visible.

1. Click and drag the map to the left.
   - **Check:** the map pans right. New map tiles appear on the left. No lag > 1 second.
2. Drag the map in the opposite direction.
   - **Check:** map pans back. Original area visible again.
3. Drag diagonally in two more directions.
   - **Check:** panning works in all directions.
4. On web: use the scroll wheel to zoom in. On mobile: pinch outward to zoom in.
   - **Check:** the map zooms in smoothly. Street names and details become visible at higher zoom.
5. Scroll/pinch the other way to zoom out.
   - **Check:** the map zooms out to show a wider area.
6. After zooming and panning, wait 3 seconds.
   - **Check:** all visible tiles have loaded (no grey placeholder squares remaining).

**Pass:** pan and zoom work in all directions; tiles load.

---

### T3.5 — North reset button

**Setup:** planning screen.

1. Locate the north reset button on the map. It is typically a compass icon or an "N" button.
   - **Check:** the button is visible.
2. If the map can be rotated (mobile): rotate the map using two fingers so north is no longer up. Then tap the north reset button.
   - **Check:** the map reorients so north is up.
3. If the map cannot be rotated (web — fixed north-up): simply verify the button exists and tap it.
   - **Check:** no error when tapping; the map remains north-up.

**Pass:** north reset button exists and functions.

---

### T3.6 — Center on position button

**Setup:** planning mode with GPS available (mobile with GPS granted, or a location-spoofed browser session).

1. Pan the map far away from your current location (several km away).
2. Locate the "Center on position" button (typically a crosshair or location-pin icon).
3. Tap it.
   - **Check:** the map immediately animates back to center on the blue dot (your current position).
   - **Check:** the blue dot is visible at or near the center of the screen after the animation.

**Pass:** centering button snaps the map back to current GPS position.

---

## Test Area 4 — Route Planning

Log in as Account A throughout. Use the OSM test area you identified in Preconditions as your planning location.

---

### T4.1 — Plan a circular route (happy path)

**Setup:** planning screen, map centered on your OSM test area.

1. In the planning panel, find the route mode selector. Select **Circular**.
   - **Check:** mode is selected (highlighted, checked, or otherwise visually active).
2. In the distance field, clear any existing value and type `3`.
   - **Check:** the field shows `3` (interpreted as km, or verify the unit label next to the field).
3. For the starting point: if on mobile with GPS, select "Use my current location" or equivalent. On web, tap a point on the map in your test area.
   - **Check:** a starting point marker appears on the map at the selected location.
4. Tap **Plan** / **Plan route** / **Find route**.
   - **Check:** a loading indicator appears (spinner, progress bar, or disabled button with loading state). The UI is not frozen.
5. Wait for planning to complete (up to 10 seconds for a cold start).
   - **Check:** the loading indicator disappears.
   - **Check:** a route is drawn on the map as a coloured line.
   - **Check:** the route visually forms a closed loop — it starts and ends at (or very near) the starting point marker.
   - **Check:** the total route distance is displayed (e.g. "3.1 km"). It is within ± margin of 3 km (with default margin, expect roughly 2.5–3.5 km).
   - **Check:** no error message or empty screen.

**Pass:** route drawn as a loop; distance within expected range; no errors.

---

### T4.2 — Plan an A to B route

**Setup:** planning screen, same test area.

1. Select **A to B** mode.
2. Enter distance: `2` km.
3. Set the starting point: tap a location on the map (point A).
   - **Check:** a start marker appears.
4. Set the endpoint: tap a different location on the map roughly 500 m–1 km away in a straight line (point B).
   - **Check:** an end marker appears.
5. Tap **Plan**.
   - **Check:** loading indicator appears.
6. Wait for result.
   - **Check:** a route line is drawn from start marker to end marker.
   - **Check:** the route does NOT loop back — it terminates at the end marker.
   - **Check:** total distance shown is approximately 2 km ± margin.

**Pass:** point-to-point route drawn between two distinct markers.

---

### T4.3 — Plan an A to B shortest route

**Setup:** planning screen.

1. Select **A to B shortest** mode.
2. Set a starting point (tap map).
3. Set an endpoint approximately 800 m away.
4. Tap **Plan**.
   - **Check:** loading indicator appears.
5. Wait for result.
   - **Check:** a route is drawn. It follows roughly the shortest path between the two points — it does not take large detours.
   - **Check:** total distance shown. It should be close to the straight-line distance between A and B (within shortest-path margin).
   - **Check:** if there are alternative (longer) paths nearby, the route does not obviously take them.

**Pass:** shortest-path route drawn, does not take unnecessary detours.

---

### T4.4 — Starting point is snapped to the nearest routable path

**Setup:** planning screen.

1. Find an area on the map that is clearly off-road: a park interior, a building footprint, a river. Zoom in so you can see the roads nearby.
2. Tap exactly on the off-road area to set the starting point.
   - **Check:** a starting point marker appears — note exactly where it appears.
3. **Check:** the marker is NOT sitting exactly on where you tapped. It has been moved ("snapped") to the nearest road or path.
4. Visually confirm the snapped point is on a walkable path shown on the map tiles.
5. Plan a circular route of 2 km from this starting point.
   - **Check:** the route begins from the snapped point, which is on the road network.

**Pass:** starting point snaps to the nearest routable road, not to the raw tapped coordinates.

---

### T4.5 — Plan using manually selected starting point (no GPS)

**Setup:** use the web browser (GPS not available), or mobile with GPS denied.

1. On the planning screen, verify there is no blue dot (GPS unavailable).
2. Tap the map in your test area to select a starting point manually.
   - **Check:** a starting point marker appears. No error about missing GPS.
3. Enter distance `2` km, select Circular mode.
4. Tap **Plan**.
   - **Check:** route planning proceeds and produces a route. No error about GPS being required.

**Pass:** planning works fully without GPS using a manually tapped point.

---

### T4.6 — Server unreachable produces a clear error

**Setup:** run this as a standalone test. Have the API server running to begin with.

1. Plan a successful route first to confirm planning works (quick sanity check — T4.1 suffices).
2. Stop the API server: `systemctl stop unwalked-api`
3. Back in the app, tap **Plan** to request a new route.
   - **Check:** the loading indicator appears briefly.
   - **Check:** an error message appears (e.g. "Could not reach the server", "Network error", "Planning is unavailable"). The message must be visible to the user — not hidden in a log.
   - **Check:** the app does NOT crash. It does NOT hang indefinitely.
   - **Check:** no partial or empty route is drawn.
4. Restart the API server: `systemctl start unwalked-api`
5. Wait 5 seconds, then tap **Plan** again.
   - **Check:** planning succeeds normally. The error was transient.

**Pass:** server error surfaces to the user clearly; app recovers when server is back.

---

### T4.7 — Current margin is shown in the planning UI

**Setup:** logged in as Account A.

1. Navigate to **Settings**.
2. Set **Margin** to `25%` (or whatever specific value the control allows, as close to 25 as possible).
3. Navigate back to the planning screen.
   - **Check:** somewhere in the planning panel (near the distance input, or as a label), the current margin value is shown (e.g. "±25%" or "Margin: 25%"). The user can see it without opening Settings.

**Pass:** the active margin value is visible during planning.

---

### T4.8 — Route diversity: repeated plan from same start avoids previous paths

**Setup:** Account A must have at least one completed walk (if Account A has no walk history, complete T5.3 first, then return here).

1. Open the planning screen. Note which paths in your test area are coloured in the heatmap — those are the walked ones.
2. Select Circular mode, enter `3` km, set starting point to the same location used in the previous walk.
3. Tap **Plan**.
4. When the route appears, compare it visually to the heatmap.
   - **Check:** the new route takes streets that are NOT coloured on the heatmap, or takes fewer coloured streets than a simple shortest-path route would.
   - **Check:** the route is not identical to the previous walk (it uses fresh edges where possible).
5. Plan a second route immediately from the same starting point.
   - **Check:** the second route differs from the first, again preferring streets not yet in the heatmap.

**Pass:** consecutive routes from the same start diverge; algorithm avoids previously walked edges.

---

### T4.9 — Escalation: user is notified when margin was auto-widened

**Setup:** this test requires creating a constrained planning scenario. The easiest way is to block all nearby paths using path preferences (covered in T8) and attempt planning. Alternatively, choose a very rural starting point with few roads.

1. Pick a starting point on the map that has very few nearby roads (outskirts of the loaded OSM area, or a location with limited street network).
2. Enter a distance that is barely achievable — small enough that the planner may struggle to meet it exactly.
3. Tap **Plan**.
4. If a route is returned: look for a notice or banner accompanying the route result.
   - **Check:** if the margin was auto-widened, the app shows a visible notification (e.g. "Route found — margin was widened to fit" or "Distance slightly outside your margin"). This message must be clear and visible without the user looking for it.
5. If no notice appears, try again with a tighter margin (set margin to 0% in Settings) and a more constrained area.

**Pass:** when margin is auto-widened, user is explicitly informed in the UI.

---

### T4.10 — Escalation: user is notified when a turnaround was used

**Setup:** even more constrained than T4.9. The turnaround is a last resort, so it requires an area where forward-only routing cannot complete the loop.

1. Set margin to 0% in Settings.
2. Pick a dead-end street or peninsula on the map where the only exit is the entry road.
3. Set the starting point on that dead end.
4. Request a circular route.
5. If the route is returned with a turnaround:
   - **Check:** the route visibly doubles back on a single segment.
   - **Check:** a notification or message informs the user that a turnaround was used (e.g. "Route includes a U-turn" or "Route doubles back on one segment").

**Pass:** turnaround usage is communicated explicitly to the user.

---

### T4.11 — No route found: clear message with actionable guidance

**Setup:** create an impossible planning request.

1. Zoom the map to the edge of the loaded OSM region where there are almost no roads.
2. Set the starting point to a road node at the very edge of the data.
3. Request a circular route of `50` km (likely impossible in this constrained area).
4. Tap **Plan**.
   - **Check:** no route is drawn on the map.
   - **Check:** a clear message appears (e.g. "No route could be found"). It must be prominent — not a tiny label.
   - **Check:** the message includes actionable guidance: "Try a shorter distance" or "Try a different starting point" or both.
   - **Check:** the app does NOT crash.
   - **Check:** the planning panel is still usable after the failure. You can change the distance and try again.

**Pass:** planning failure is communicated clearly with guidance; UI remains functional.

---

### T4.12 — Rate limiting on rapid repeated requests

**Setup:** planning screen with a valid starting point ready.

1. Tap **Plan** to request a route.
2. Immediately — before the first result returns — tap **Plan** again.
3. Continue tapping **Plan** rapidly 5 more times.
4. Observe what happens:
   - **Check:** the app does not send an unbounded number of simultaneous requests. Either: (a) subsequent taps are ignored while a request is in flight, or (b) the server imposes increasing wait times (progressive back-off).
   - **Check:** if the server imposes a wait, the app shows a visible wait/loading state. It does not present a success result instantaneously.
   - **Check:** the API server does not crash or return 500 errors (check `journalctl -u unwalked-api -n 50` after the test to confirm no error flood).
   - **Check:** after waiting a few seconds, a valid route is eventually returned.

**Pass:** rapid requests are handled gracefully; no server crash; route eventually returned.

---

## Test Area 5 — Walk Tracking

**[MOBILE ONLY]** — all tests in this area require a physical mobile device with GPS.

Complete T4.1 first so a route is already planned. Use a short route (1–2 km) for speed.

---

### T5.1 — Switch to walking mode after planning a route

**Setup:** a route is planned and displayed on the mobile app. You are in planning mode.

1. Look for a **Start walk** button or equivalent (may be in the planning panel, or a FAB button).
2. Tap **Start walk**.
   - **Check:** the UI changes visibly — you are now in walking mode. The planning panel is replaced by a walking panel showing at minimum: current distance walked, an option to end the walk, and possibly an option to re-plan.
   - **Check:** the full planned route is still drawn on the map.
   - **Check:** the walked portion and unwalked portion are in TWO DISTINCT COLOURS. Neither is invisible. They are clearly different (e.g. blue vs light grey, green vs white).
   - **Check:** the heatmap is NOT visible. Walk history is hidden during an active walk.

**Pass:** walking mode activates; route visible; two-colour distinction; heatmap hidden.

---

### T5.2 — Walked portion updates in real time

**Setup:** active walk in progress (from T5.1).

1. Begin physically walking along the route.
2. Walk approximately 200 m along the route path, following the line on screen.
3. Stop and observe the map.
   - **Check:** the portion of the route you just walked has changed colour (the "walked" colour). It is no longer shown in the "unwalked" colour.
   - **Check:** the blue dot is at or very near your current position.
   - **Check:** the distance walked counter (if visible) has increased from zero.
4. Continue walking another 200 m.
   - **Check:** the walked portion has extended further. The colour boundary moves forward.

**Pass:** walked portion updates progressively as you advance along the route.

---

### T5.3 — Walk auto-completes on arrival at the start point (circular)

**Setup:** active walk on a circular route. You need to walk the full loop back to the starting point.

For a short test, use a circular route of 500 m–1 km.

1. Walk the full circular route until you physically arrive back at the starting point.
2. Continue to the starting point until you are within a few metres of it (within typical GPS accuracy — 5–15 m).
   - **Check:** the walk is automatically detected as complete. A completion screen, banner, or dialog appears without you needing to tap anything.
   - **Check:** the completion message is positive (e.g. "Walk complete!", "Great walk!", or similar).
   - **Check:** the app transitions back to planning mode after the completion acknowledgment (either automatically or with a single "Done" tap).
   - **Check:** in planning mode, the heatmap now shows the edges you just walked as coloured (the new walk was recorded).

**Pass:** circular walk auto-completes on arrival; edges appear in heatmap.

---

### T5.4 — Walk auto-completes on arrival at endpoint (A to B)

**Setup:** plan a short A to B route (500 m–1 km). Start the walk.

1. Walk to the endpoint.
2. Arrive within a few metres of the endpoint marker.
   - **Check:** walk auto-completes (same as T5.3).
   - **Check:** completion screen or banner appears.

**Pass:** A-to-B walk auto-completes on endpoint arrival.

---

### T5.5 — Manual walk end for A to B route

**Setup:** active A-to-B walk, partway through.

1. Stop walking before reaching the endpoint (e.g. halfway through the route).
2. In the walking panel, find the **End walk** / **Finish walk** button.
3. Tap it.
   - **Check:** a confirmation dialog appears asking you to confirm ending the walk early. It does NOT immediately end the walk.
4. Tap **Confirm** / **End**.
   - **Check:** the walk ends. A summary or completion screen shows the distance actually walked.
   - **Check:** the app returns to planning mode.
   - **Check:** the heatmap shows the edges you walked before ending (partial walk is saved).

**Pass:** early end requires confirmation; partial walk saved to history.

---

### T5.6 — Walk abandonment with confirmation dialog

**Setup:** active walk (circular or A-to-B).

1. In the walking panel, locate the option to end or abandon the walk.
2. Tap it.
   - **Check:** a confirmation dialog appears. It does NOT immediately terminate the walk.
3. Tap **Cancel** in the dialog.
   - **Check:** the dialog closes. The walk continues. You are still in walking mode.
4. Tap the end option again. This time tap **Confirm**.
   - **Check:** the walk ends with the walked portion saved.

**Pass:** accidental taps cannot end a walk; confirmation is always required.

---

### T5.7 — Walked distance reduces the free tier counter

**Setup:** Account A is on the free tier with some remaining distance.

1. On the planning screen, note the exact remaining free tier distance (e.g. "98.2 km remaining"). Write it down.
2. Complete a walk of at least 500 m (use T5.3 or T5.5 flow).
3. After the walk completes and you are back in planning mode:
   - **Check:** the remaining free tier distance has decreased. The new number is smaller than what you noted.
   - **Check:** the decrease is approximately equal to the distance you walked (within GPS accuracy tolerance, expect ±10%).

**Pass:** walked distance is deducted from free tier balance in real time.

---

### T5.8 — Background tracking continues when app is minimised

**Setup:** active walk in progress.

1. Press the home button (or switch to another app) to send the Unwalked app to the background.
2. Physically walk 200–300 m while the app is in the background.
3. Return to the Unwalked app.
   - **Check:** the walked portion on the map has advanced to reflect the distance covered while in the background. The tracking did not pause when you backgrounded the app.
   - **Check:** the blue dot is at your current position.

**Pass:** GPS tracking is continuous even when app is not in the foreground.

---

### T5.9 — Interrupted walk is recovered after force-close

**Setup:** active walk, 300+ m walked.

1. Note approximately where you are in the route.
2. Force-close the app: on iOS, swipe up from the app switcher; on Android, use "Force stop" in App Info.
3. Reopen the app.
   - **Check:** the app reopens normally (no crash on reopen).
   - **Check:** the app detects that an interrupted walk exists. Either: (a) it automatically uploads the saved GPS trace and shows a notice that the previous walk was recovered, or (b) it prompts you to recover the walk.
4. If a recovery prompt appears, confirm recovery.
   - **Check:** after recovery, the heatmap shows the edges walked before the force-close.

**Pass:** walk data recorded before force-close is preserved and synced on next open.

---

### T5.10 — Off-route vibration fires while off the planned route

**Setup:** active walk. Stand or move clearly off the planned route (at least 20–30 m away from the nearest route edge, more if GPS accuracy is poor).

1. Move off the planned route and stay there.
2. Wait at least 60 seconds.
   - **Check:** the device vibrates once. It is a single vibration pulse, not a long buzz.
3. Remain off-route and wait another 60 seconds.
   - **Check:** the device vibrates again. The pattern is once per minute while off-route.
4. Return to the planned route (within the GPS accuracy radius of the route line).
5. Wait 60 seconds while on the route.
   - **Check:** NO vibration occurs while on the route.

**Pass:** single vibration fires each minute while off-route; stops when back on route.

---

### T5.11 — Walk tracking is not available on web

**Setup:** open the app in a web browser (not mobile).

1. Plan a circular route on web (as in T4.1).
2. When the route appears, examine all visible UI controls.
   - **Check:** there is NO "Start walk" button or equivalent.
   - **Check:** there is NO walk tracking panel.
   - **Check:** the route is displayed for viewing/planning only.
3. Confirm the planning UI is still fully functional: change mode, change distance, plan another route.
   - **Check:** planning works normally. Only walk tracking is absent.

**Pass:** web platform shows no walk tracking controls; planning works normally.

---

## Test Area 6 — Mid-Walk Re-planning

**[MOBILE ONLY]** — requires GPS and an active walk.

---

### T6.1 — Re-plan as circular during an active walk

**Setup:** start a circular walk. Walk at least 200 m along it (so there is some history to preserve).

1. In the walking panel, find a **Re-plan** button or equivalent.
2. Tap **Re-plan**.
   - **Check:** a re-planning panel or modal opens. It presents the same route mode and distance inputs as the main planner.
   - **Check:** the distance field is blank or shows a default — the app does NOT pre-fill a suggested distance based on what you have already walked.
3. Select **Circular** mode.
4. Enter distance: `1` km.
5. Tap **Plan** (within the re-plan flow).
   - **Check:** planning runs server-side (loading indicator appears).
   - **Check:** a new route is drawn starting from your CURRENT POSITION, not from the original walk starting point.
   - **Check:** the new route forms a loop starting and ending at your current position.
   - **Check:** the already-walked portion is preserved in history (visible in the heatmap after the walk ends).

**Pass:** re-plan produces a new circular route from current position; fresh distance entry; prior walk preserved.

---

### T6.2 — Re-plan as A to B during an active walk

**Setup:** active walk (any mode).

1. Tap **Re-plan**.
2. Select **A to B** mode.
3. Tap a point on the map as the new endpoint (different from starting point).
4. Enter a distance (e.g. `1.5` km).
5. Tap **Plan**.
   - **Check:** new route drawn from current position to the tapped endpoint.
   - **Check:** it does NOT loop back to the original start.

**Pass:** A-to-B re-plan works from current position during a walk.

---

### T6.3 — Re-plan as A to B shortest during an active walk

**Setup:** active walk (any mode).

1. Tap **Re-plan**.
2. Select **A to B shortest** mode.
3. Tap a point on the map as the new endpoint.
4. Tap **Plan**.
   - **Check:** a shortest-path route is drawn from current position to endpoint.
   - **Check:** the route is visually direct — no large detours.

**Pass:** A-to-B shortest re-plan works from current position during a walk.

---

## Test Area 7 — Dead End Handling

Log in as Account A. Use an OSM area that contains at least one dead-end street (a cul-de-sac or a road that terminates at a building). Check the map at street level — look for roads that visually terminate without connecting.

---

### T7.1 — Dead ends are excluded from routes by default

**Setup:** planning screen. Confirm in Settings that "Dead ends" toggle is OFF (the default).

1. Open **Settings** and check the dead ends setting.
   - **Check:** the dead ends option is toggled OFF (avoid dead ends). This is the default — if it is ON, toggle it OFF now and navigate back.
2. Set the starting point near a dead-end street in your test area.
3. Plan a circular route of 2 km.
4. When the route appears, trace it on the map carefully.
   - **Check:** the route does NOT enter any dead-end streets. It only uses through-roads and paths that have exits on both ends.
5. Plan two or three more routes from the same starting point.
   - **Check:** none of the routes use dead ends.

**Pass:** routes with dead ends off never enter dead-end streets.

---

### T7.2 — Enabling dead ends allows the route to use them

**Setup:** planning screen, near the same dead-end area.

1. Open **Settings**. Toggle **Dead ends** to ON.
2. Navigate back to planning.
3. Plan a circular route of 2 km from the same starting point used in T7.1.
4. Plan several routes (3–5) until one uses a dead end.
   - **Check:** at least one of the planned routes enters and exits a dead-end street. (The planner may not always choose one, but it may.)
5. Optionally confirm by toggling back to OFF: plan the same route again and verify the dead end is no longer used.

**Note:** this test is probabilistic — with dead ends ON the planner _may_ use them but is not required to. The key check is that they are not categorically excluded.

**Pass:** with dead ends ON, routes can include dead-end streets.

---

### T7.3 — If start is in a dead end, the planner routes out of it regardless

**Setup:** dead ends toggle is OFF (avoid dead ends). Find a clear dead-end street on the map.

1. Set the starting point to a location inside the dead end — past the point where the dead-end street diverges from the main road.
2. Plan a circular route of 2 km.
   - **Check:** planning succeeds. A route is returned.
   - **Check:** the route begins by exiting the dead end (it must travel out along the dead-end street to reach the road network). This is the expected exception — the planner cannot avoid using the dead end's only exit.
   - **Check:** once on the main road network, the remainder of the route does NOT re-enter any dead ends.

**Pass:** planner exits a dead-end starting point and then avoids further dead ends for the rest of the route.

---

## Test Area 8 — User Path Preferences

Log in as Account A. Use the planning screen in an area with identifiable streets.

---

### T8.1 — Open the path preferences dialog

**Setup:** planning screen.

1. Find the path preferences control. It is described as a "dedicated map dialog, accessible outside of planning mode as a global setting." Look for a button labelled something like "Path preferences", a road icon, or a settings overlay button on the map.
2. Open the path preferences dialog.
   - **Check:** the map is still visible (or visible in the background). An overlay or side panel is now shown.
   - **Check:** the mode has changed — you are now in a path-selection mode, not route-planning mode.
3. Tap a road or path on the map.
   - **Check:** a context panel or menu appears for that specific path. It offers at minimum: "Prefer not" and "Block" as options.

**Pass:** path preferences dialog opens; tapping a path shows preference options.

---

### T8.2 — Set "Prefer not" on a path

**Setup:** path preferences dialog open (from T8.1). Choose a path that a route would normally use — pick a short street in the middle of your test area.

1. Tap the target path. Select **Prefer not**.
   - **Check:** the path is visually marked in the dialog (e.g. a different colour or icon on the map overlay indicating a preference is set).
   - **Check:** a confirmation or snackbar appears confirming the preference was saved.
2. Close the path preferences dialog and return to planning mode.
3. Set the starting point adjacent to the "prefer not" path and plan a circular route of 2 km.
4. When the route appears, check whether it avoids the marked path.
   - **Check:** the route does NOT use the "prefer not" path if alternative paths of similar length exist. The planner avoids it (it is penalised heavily, not blocked entirely, so avoidance is expected but not guaranteed if there are no alternatives).
5. Re-open path preferences for the same path.
   - **Check:** the "prefer not" marking is still shown (it persisted; was not reset when you closed the dialog).

**Pass:** "prefer not" preference saved and persisted; route avoids the path.

---

### T8.3 — Set "Block" on a path

**Setup:** path preferences dialog open. Pick a different path than T8.2.

1. Tap a road. Select **Block**.
   - **Check:** the path is visually marked as blocked in the overlay.
   - **Check:** preference is confirmed/saved.
2. Close the dialog. Plan a circular route that would normally pass through or near the blocked path.
3. When the route appears:
   - **Check:** the route does NOT use the blocked path at all. The planner routes around it as if it does not exist.
4. Re-open path preferences.
   - **Check:** the path still shows as blocked (preference persisted).

**Pass:** blocked path is completely excluded from the route.

---

### T8.4 — Remove a path preference

**Setup:** at least one path has a preference set (from T8.2 or T8.3).

1. Open path preferences dialog.
2. Tap the path that has a preference set.
   - **Check:** the context menu shows an option to remove/clear the preference (e.g. "Remove preference", "Clear", or "No preference").
3. Select **Remove**.
   - **Check:** the path's visual marking disappears from the map overlay.
   - **Check:** a confirmation that the preference was removed.
4. Close the dialog. Plan a route that would use this path.
   - **Check:** the route can now use the previously marked path without penalty (it is treated as a normal path again).
5. Re-open path preferences for the same path.
   - **Check:** no preference is shown for this path.

**Pass:** preference removal works; path is treated normally in subsequent planning.

---

### T8.5 — Prefer not uses multiplier 10 before any walk history exists

**Setup:** log in as a fresh account with ZERO walk history. Set a "Prefer not" on a path.

1. Create or use a fresh account (no walks).
2. Open path preferences dialog. Mark a path as **Prefer not**.
3. Plan a route that would normally use that path.
   - **Check:** the route avoids the "prefer not" path. This confirms the multiplier-10 penalty is applied even without walk history (the design states: "Before any walk history exists, prefer not uses multiplier 10").
4. Verify: plan several routes, all should avoid the marked path.

**Pass:** "prefer not" penalty is applied (via multiplier 10) even with zero walk history.

---

## Test Area 9 — Settings Screen

Log in as Account A throughout.

---

### T9.1 — Margin setting is saved and survives navigation

**Setup:** planning screen.

1. Navigate to **Settings** (look for a gear icon, "Settings" tab, or similar in the navigation).
   - **Check:** a settings screen is shown. It contains at minimum: a Margin control and a Dead ends toggle.
2. Find the **Margin** control (slider or input field). Note its current value.
3. Set it to `25%` (or as close as the control allows).
4. Navigate away: press back or go to the planning screen.
5. Re-open **Settings**.
   - **Check:** the Margin value is still `25%`. It did not reset.
6. Navigate away and reopen the app tab (or restart the app on mobile).
7. Re-open **Settings**.
   - **Check:** Margin is still `25%`. The setting survived a full app restart.

**Pass:** margin setting persists through navigation and app restart.

---

### T9.2 — Shortest path margin is saved and survives navigation

**Setup:** Settings screen.

1. Find the **Shortest path margin** control.
2. Set it to `15%`.
3. Navigate away and re-open Settings.
   - **Check:** shortest path margin is still `15%`.
4. Restart the app and check again.
   - **Check:** still `15%`.

**Pass:** shortest path margin persists.

---

### T9.3 — Dead ends toggle is saved and survives navigation

**Setup:** Settings screen.

1. Find the **Dead ends** toggle. Note its current state.
2. Toggle it to the OPPOSITE of its current state.
3. Navigate away and re-open Settings.
   - **Check:** the toggle is in the state you set it to (not reverted).
4. Restart the app and check.
   - **Check:** still in the set state.
5. Toggle it back to the original state (to avoid interfering with other tests).

**Pass:** dead ends toggle persists through navigation and restart.

---

### T9.4 — Circularity/diversity slider is hidden from regular users

**Setup:** logged in as Account A (a regular, non-developer account).

1. Open **Settings**.
2. Scroll through the entire settings screen.
   - **Check:** there is NO circularity/diversity slider, no weighting slider, and no scoring tuning control visible anywhere on the settings screen.
   - **Check:** all other expected settings ARE visible (Margin, Shortest path margin, Dead ends).

**Pass:** the developer-only slider is not visible to regular users.

---

### T9.5 — Circularity/diversity slider is visible for the developer account

**Setup:** log in as the developer account (credentials from server config).

1. Open **Settings**.
2. Scroll through the settings screen.
   - **Check:** a circularity/diversity slider IS visible. It may be labelled "Circularity weight", "Diversity/Circularity", or similar.
   - **Check:** the slider can be moved (it is not disabled or read-only).
3. Move the slider to an extreme (far left or far right).
4. Navigate away and re-open Settings.
   - **Check:** the slider position was saved (it did not reset to default).
5. Log out.
6. Log in as Account A and check Settings.
   - **Check:** slider is not visible for Account A (confirm developer-only visibility still holds).

**Pass:** slider visible and functional for developer account only.

---

## Test Area 10 — Profile / Account Screen

---

### T10.1 — Username is displayed on the profile screen

**Setup:** logged in as Account A.

1. Navigate to the **Profile** screen (look for a "Profile", "Account", or person-icon tab).
   - **Check:** the profile screen loads without errors.
2. Scan the visible information.
   - **Check:** the username or email address of Account A is displayed (`TesterA` or `tester+a@example.com`).
   - **Check:** it is displayed prominently (not hidden in a small footer).

**Pass:** username/email shown on profile screen.

---

### T10.2 — Subscription status "Free" shown for a free-tier account

**Setup:** Account A is on the free tier (no payment made).

1. On the profile screen, find the subscription/payment section.
   - **Check:** the subscription status is clearly labelled as free, unpaid, or "Free tier" — not "Active" or "Premium".
   - **Check:** an upgrade option (button or link to upgrade to paid) is visible.

**Pass:** free tier status clearly shown with upgrade option visible.

---

### T10.3 — Subscription status "Active" shown for a paid account

**Setup:** use an account that has a valid paid subscription. Either complete T11.3 (Mollie upgrade) first, or manually set subscription status in the database:
```
psql -U unwalked_app -d unwalked -c \
  "UPDATE subscriptions SET tier='paid', expires_at = NOW() + INTERVAL '1 year' WHERE user_id = (SELECT id FROM users WHERE email='tester+a@example.com');"
```

1. Log in as the paid account. Navigate to Profile.
   - **Check:** subscription status shows as active/paid (e.g. "Active", "Premium", "Subscribed").
   - **Check:** the expiry date or renewal date is shown (e.g. "Expires 2027-03-02").
   - **Check:** there is NO "upgrade" prompt shown (the user is already paid).

**Pass:** paid subscription status and expiry date shown correctly.

---

## Test Area 11 — Freemium Enforcement

---

### T11.1 — Free tier limit blocks route planning

**Setup:** set Account A's walked distance to 100 km in the database to simulate reaching the limit:
```
psql -U unwalked_app -d unwalked -c \
  "UPDATE subscriptions SET walked_distance_km = 100 WHERE user_id = (SELECT id FROM users WHERE email='tester+a@example.com');"
```

1. Log in as Account A (or refresh the session if already logged in).
2. Navigate to the planning screen.
   - **Check:** instead of the normal planning panel, an upgrade prompt or "limit reached" screen is shown. It is the first thing you see when entering planning mode — you do not get to the planning form.
   - **Check:** the message clearly states the free tier limit has been reached.
   - **Check:** an option to upgrade (button or link) is visible.
3. Attempt to find any route planning control (distance input, Plan button).
   - **Check:** no planning form is accessible. Planning is blocked.

**Pass:** planning is completely blocked at the free tier limit; upgrade prompt shown immediately.

---

### T11.2 — A walk in progress completes even if the limit is crossed mid-walk

**[MOBILE ONLY]** — requires actually walking distance, or testing with a GPS mock.

**Setup:** set Account A's walked distance to 99.5 km (0.5 km below the limit):
```
psql -U unwalked_app -d unwalked -c \
  "UPDATE subscriptions SET walked_distance_km = 99.5 WHERE user_id = (SELECT id FROM users WHERE email='tester+a@example.com');"
```

1. Log in as Account A. Confirm planning is still allowed (99.5 < 100).
2. Plan and start a circular walk of 1 km. This walk will push the total over 100 km partway through.
3. Begin walking. Continue for approximately 600–700 m (past the 100 km total threshold).
   - **Check:** the app does NOT forcibly terminate the walk mid-way. The walk continues normally even after crossing 100 km.
   - **Check:** no blocking dialog interrupts the active walk to demand payment.
4. Complete the walk fully (return to start).
   - **Check:** the walk completes normally. The completion screen appears.
5. Return to planning mode.
   - **Check:** the upgrade prompt now appears (total is now > 100 km). Planning is blocked.

**Pass:** in-progress walk is allowed to complete after crossing the free tier limit.

---

### T11.3 — Upgrade via Mollie restores planning access

**Precondition:** Mollie test API key is configured (`MOLLIE_API_KEY` is a test key from Mollie dashboard). Account A's walked distance is at or above 100 km (from T11.1 or T11.2).

Mollie test card details (use these in the checkout): card number `4543474002249996`, expiry `12/25`, CVV `123`, or use the [Mollie test payment flow](https://docs.mollie.com/docs/testing).

1. Open the app as Account A. The upgrade prompt should be visible.
2. Tap the **Upgrade** / **Subscribe** button.
   - **Check:** you are redirected to a Mollie-hosted checkout page (either in a new tab or an in-app web view). The URL should be a Mollie domain.
   - **Check:** the checkout shows the amount `€10.00` and a description referencing the subscription.
3. Complete the payment using the Mollie test card.
   - **Check:** Mollie shows a payment success screen.
4. Return to the Unwalked app.
   - **Check:** the app receives the payment confirmation (via Mollie webhook). This may take a few seconds.
   - **Check:** the planning screen is now accessible — the upgrade prompt is gone.
5. Plan a circular route.
   - **Check:** route planning succeeds. No free tier restriction.
6. Navigate to the Profile screen.
   - **Check:** subscription status shows as active/paid. Expiry date is approximately one year from today.

**Pass:** Mollie payment flow completes; subscription activated; planning unblocked; profile reflects paid status.

---

## Test Area 12 — Map Visualization

Log in as Account A. Account A should have completed at least two walks (from Test Area 5) with some overlapping streets.

---

### T12.1 — Heatmap shows walk history with colour scale

**Setup:** planning mode, map centred on the area where Account A has walked.

1. Pan to an area where Account A has completed walks.
   - **Check:** streets that were walked are shown in a colour (not the default tile colour). At minimum some paths should be coloured.
2. If some streets were walked multiple times (e.g. returned to the same starting point), look for those streets.
   - **Check:** streets walked more frequently are shown in a different (warmer/brighter) colour than streets walked only once.
3. Locate the heatmap legend on the screen.
   - **Check:** a legend is visible, explaining what the colours mean (e.g. a colour scale from "1 walk" to "5+ walks", or a gradient with labels).

**Pass:** heatmap shows walked edges coloured; higher counts are visually distinct; legend present.

---

### T12.2 — Heatmap is hidden during an active walk

**Setup:** account has walk history; heatmap is currently visible in planning mode.

1. Confirm you can see the heatmap (coloured edges) in planning mode.
2. Start a walk (tap Start walk on mobile, or verify this on mobile only).
   - **Check:** immediately upon entering walking mode, the coloured heatmap edges disappear from the map.
   - **Check:** only the planned route line is shown on the map (no walk history overlay).
3. End the walk (manually or on arrival).
   - **Check:** upon returning to planning mode, the heatmap edges reappear.

**Pass:** heatmap visible in planning mode, hidden in walking mode, reappears after walk.

---

### T12.3 — Route line uses two distinct colours for walked vs unwalked portions

**Setup:** active walk in progress on mobile (see Test Area 5).

1. Walk approximately 30–40% of the route.
2. Stop and look at the map.
   - **Check:** the route line has TWO visually distinct colour segments.
   - **Check:** Segment 1 (the portion you walked): starts at the beginning of the route, ends at approximately your current position. It is in one colour (e.g. darker, saturated).
   - **Check:** Segment 2 (the portion ahead): starts from approximately your current position, ends at the end of the route. It is in a clearly different colour (e.g. lighter, greyed out).
   - **Check:** the two colours are unambiguous — they cannot be confused for each other under normal daylight or screen brightness.
   - **Check:** the boundary between the two segments moves as you walk.

**Pass:** walked and unwalked portions of the route are clearly distinct in colour.

---

## Test Area 13 — Global Coverage

---

### T13.1 — Plan a route in a remote region

**Setup:** you need a second geographic area that (a) has OSM data loaded on the server, or (b) the server loads OSM data on demand when first requested.

If the server loads data on demand: pick any major city (e.g. Berlin, Amsterdam, London) and proceed. The first request may take 30–120 seconds while data loads.

If the server has specific regions pre-loaded: choose a region other than your local test area.

1. In the planning screen, pan the map to the remote city/area.
2. Zoom in to street level to see individual roads.
   - **Check:** map tiles load correctly for this area. Streets are visible.
3. Tap a road to set it as the starting point.
   - **Check:** the starting point marker appears on a road in the remote area.
4. Select Circular mode, enter `2` km.
5. Tap **Plan**.
   - **Check:** a loading indicator appears (if data is loading for the first time, it may show for longer — up to 2 minutes is acceptable for the first load).
   - **Check:** eventually a route is returned. It uses actual streets in the remote area — not a generic or fallback route.
   - **Check:** the route is drawn on the correct city's streets, not the local test area streets.

**Pass:** route planned successfully in a remote area using real OSM street data.

---

## Test Area 14 — Token and Session Management

---

### T14.1 — Login session persists across browser close and reopen

**Setup:** logged in as Account A in a normal browser window (not incognito).

1. Close the browser tab (or the entire browser window).
2. Reopen the browser and navigate to the app URL.
   - **Check:** you are immediately on the planning screen, logged in as Account A. You are NOT redirected to the login screen.
   - **Check:** the username or user indicator confirms you are Account A.

**Pass:** session is preserved after closing and reopening the browser.

---

### T14.2 — Expired or invalid token redirects to login

**Setup:** logged in as Account A.

To simulate token expiry, manually clear the stored token in the browser:

1. Open browser Developer Tools → Application → Storage → Local Storage (or Session Storage / Cookies, depending on where the token is stored). Delete the token entry (look for `access_token`, `jwt`, `auth_token`, or similar).
2. Without refreshing, perform an action that requires authentication: tap **Plan** to request a route.
   - **Check:** the app detects the missing/invalid token.
   - **Check:** the app redirects you to the login screen. It does NOT show an unhandled error or a blank screen.
   - **Check:** after logging in again, the app resumes normally on the planning screen.

Alternative method (if token location is not clear): wait for the token to expire naturally (JWT expiry is set by `JWT_EXPIRY_SECONDS` in config) and then interact with the app.

**Pass:** invalid/expired token causes a clean redirect to login; no crash or unhandled error.

---

### T14.3 — Refresh token keeps the session alive across multiple days

**Setup:** log in as Account A.

1. Log in to the app. Note the time.
2. Use the app lightly (plan a route or two).
3. Come back the next day without logging out and without clearing browser data.
4. Open the app and perform an authenticated action (e.g. plan a route).
   - **Check:** you are still logged in. No re-login was required.
   - **Check:** the action succeeds. The refresh token was silently exchanged for a new access token in the background.

**Pass:** session stays alive across days via refresh token rotation without requiring the user to log in again.

---

## Pass Criteria Summary

Mark each row Pass / Fail / Skip (skip where platform not available).

| Test | Description | Result |
|---|---|---|
| T1.1 | Onboarding screen appears on first launch | |
| T1.2 | GPS denial → graceful degradation, no blue dot, planning works | |
| T1.3 | GPS grant → blue dot appears and tracks position | |
| T2.1 | Register new account → logged in, lands on planning screen | |
| T2.2 | Duplicate email rejected with clear message | |
| T2.3 | Login with correct credentials → planning screen | |
| T2.4 | Wrong password → generic error, no login | |
| T2.5 | Password reset: email sent, new password accepted, old rejected | |
| T2.6 | Google OAuth login works; same account on repeat | |
| T2.7 | Apple sign-in works on iOS | |
| T2.8 | Logout returns to login screen; session cleared | |
| T2.9 | Account deletion: immediate, confirmed, data purged, email reusable | |
| T3.1 | Planning mode is default after login | |
| T3.2 | Empty heatmap snackbar appears for fresh account | |
| T3.3 | Remaining free tier km shown in planning mode | |
| T3.4 | Map pans and zooms; tiles load | |
| T3.5 | North reset button exists and functions | |
| T3.6 | Center on position button centres map on blue dot | |
| T4.1 | Circular route: loop drawn, distance within margin | |
| T4.2 | A-to-B route: line from A to B, distance within margin | |
| T4.3 | A-to-B shortest: visually direct route | |
| T4.4 | Starting point snaps to nearest road | |
| T4.5 | Manual starting point works without GPS | |
| T4.6 | Server-down → clear error; recovers when server back | |
| T4.7 | Active margin value visible in planning UI | |
| T4.8 | Second route avoids previously walked edges | |
| T4.9 | Margin auto-widened → user notified | |
| T4.10 | Turnaround used → user notified | |
| T4.11 | No route found → clear message with guidance | |
| T4.12 | Rapid requests rate-limited; no crash | |
| T5.1 | Walk starts; two-colour route; heatmap hidden | |
| T5.2 | Walked portion updates in real time as you advance | |
| T5.3 | Circular walk auto-completes on arrival at start | |
| T5.4 | A-to-B walk auto-completes on arrival at endpoint | |
| T5.5 | Manual end: confirmation required; partial walk saved | |
| T5.6 | Abandon: confirmation required; walk survives cancel | |
| T5.7 | Walked distance deducted from free tier balance | |
| T5.8 | Background tracking continues when app minimised | |
| T5.9 | Force-close → walk data recovered on next open | |
| T5.10 | Off-route vibration: once per minute; stops when on-route | |
| T5.11 | No walk controls on web platform | |
| T6.1 | Re-plan as circular from current position mid-walk | |
| T6.2 | Re-plan as A-to-B mid-walk | |
| T6.3 | Re-plan as A-to-B shortest mid-walk | |
| T7.1 | Dead ends OFF: route never enters dead ends | |
| T7.2 | Dead ends ON: route may use dead ends | |
| T7.3 | Start in dead end → routed out; rest avoids dead ends | |
| T8.1 | Path preferences dialog opens; tap path shows options | |
| T8.2 | Prefer not: preference saved; route avoids path | |
| T8.3 | Block: path completely excluded from route | |
| T8.4 | Remove preference: path treated normally again | |
| T8.5 | Prefer not multiplier 10 applies with zero walk history | |
| T9.1 | Margin setting persists across navigation and restart | |
| T9.2 | Shortest path margin persists | |
| T9.3 | Dead ends toggle persists | |
| T9.4 | Developer slider hidden from regular users | |
| T9.5 | Developer slider visible and functional for dev account | |
| T10.1 | Username shown on profile screen | |
| T10.2 | Free tier: status and upgrade option shown | |
| T10.3 | Paid tier: active status and expiry date shown | |
| T11.1 | At 100 km limit: planning blocked; upgrade prompt shown | |
| T11.2 | Walk in progress completes after crossing limit | |
| T11.3 | Mollie payment → subscription active; planning unblocked | |
| T12.1 | Heatmap colours walked edges; higher counts visually distinct; legend present | |
| T12.2 | Heatmap hidden in walking mode; reappears in planning | |
| T12.3 | Route line: two distinct colours for walked vs unwalked | |
| T13.1 | Route planned in remote region using real OSM streets | |
| T14.1 | Session persists after browser close and reopen | |
| T14.2 | Invalid/expired token → clean redirect to login | |
| T14.3 | Refresh token keeps session alive across days | |
