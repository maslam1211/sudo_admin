# Build SudoTag Fleet Management for Sudo Admin Dashboard (Web)

**Reference project (mobile):** `/Users/muhmammedaslamt/Documents/sudo` (Flutter — SudoTag)  
**Admin project (web):** `/Users/muhmammedaslamt/Documents/GitHub/sudo_admin` (Django `sudo_admin`)

Study and mirror the existing **mobile Fleet + subscription** implementation. Use the **same Firestore schema, plan IDs, prices, and business rules**. Do **not** invent a parallel data model or REST API.

> **Scope:** This prompt is for the **Admin Dashboard (web)** only. Customer subscribe / drivers / shift assign stay in the Flutter app: **Me → SudoTag Fleet**.

> **Goal:** Give admins a control plane for paid fleets: list subscriptions, see drivers, activate or extend a plan after offline GST payment, and cancel subscriptions. QR call/SMS routing still uses vehicle assignment fields from the mobile app.

> **v1 already started in `sudo_admin`.** Extend it — do not rebuild from scratch. Match `manage_referrals` / `manage_vehicles` UI (sidebar, Bootstrap cards, tables, CSRF POSTs).

---

## Context

SudoTag Fleet is a **B2B subscription** on top of personal SudoTag.

- Personal vehicles, family **Temp QR Assign**, and buying QR stickers stay **free / one-time**.
- Fleet is **software**: company name, plan, drivers, shift assignment.
- One fleet per paying owner (`fleets` queried by `ownerId`).
- Drivers are **phone contacts** on the fleet (collection `fleet_drivers`), not a separate driver login in v1.
- While a driver is assigned to a vehicle, QR **voice and SMS** use `Vehicle.effectiveContactNumber` (same denormalized fields as Temp QR Assign). Chat / SOS stay with the owner.

Mobile payment: Razorpay via Cloud Functions `createFleetSubscriptionOrder` + `confirmFleetSubscription` (server-side plan prices in paise). Admin may **activate without Razorpay** (cash / GST invoice).

---

## Plans (must match mobile + Cloud Functions)

Amounts in **INR** for admin display. Functions store Razorpay amounts in **paise**.

| `planId` | Name | Vehicles | Drivers | Monthly | Yearly |
|----------|------|----------|---------|---------|--------|
| `starter` | Starter | 10 | 10 | ₹999 | ₹9,999 |
| `business` | Business | 50 | 50 | ₹2,999 | ₹29,999 |
| `enterprise` | Enterprise | 200 | 200 | ₹7,999 | ₹79,999 |

- `billingCycle`: `monthly` (30 days) or `yearly` (365 days)
- `subscriptionStatus`: `none` | `pending` | `trialing` | `active` | `past_due` | `cancelled`
- **Active in product:** `active` or `trialing`, and `subscriptionExpiresAt` is null **or** in the future

Python helper must match Flutter `Fleet.hasActiveSubscription` and `functions/fleet_subscriptions.js` `FLEET_PLANS`.

---

## Reference files (mobile — source of truth)

### Domain & data

- `lib/domain/entities/fleet.dart` — `FleetPlan`, `Fleet`, `FleetDriver`
- `lib/data/models/fleet_model.dart`
- `lib/data/firestore_services/fleet_store.dart` — collections `fleets`, `fleet_drivers`
- `lib/domain/interfaces/fleet_repository.dart`
- `lib/data/repositories/fleet_repository_impl.dart`
- `lib/domain/entities/vehicle.dart` — `assignedFamilyMember*`, `assignedUntil`, `hasActiveFamilyAssignment`, `effectiveContactNumber`
- `lib/data/firestore_services/vehicle_store.dart` — `updateVehicleAssignment` (use `FieldValue.delete` when clearing)

### UI (mobile — do not port as admin screens)

- `lib/customer/fleet/screens/fleet_home_screen.dart`
- `lib/customer/fleet/screens/fleet_subscribe_screen.dart`
- `lib/customer/fleet/screens/fleet_driver_form_screen.dart`
- `lib/customer/fleet/cubit/fleet_cubit.dart`
- `lib/customer/vehicles/widgets/menu.dart` — **Me → SudoTag Fleet**

### Backend

- `functions/fleet_subscriptions.js`
- `functions/index.js` — exports `createFleetSubscriptionOrder`, `confirmFleetSubscription`
- `firestore.rules` — `fleets`, `fleet_drivers` (clients cannot change plan / status / limits / expiry)
- `firestore.indexes.json` — `fleets.ownerId + createdAt`, `fleet_drivers.fleetId + createdAt`

### Related (QR routing)

- `lib/customer/family_members/` — Temp QR Assign (personal, not fleet)
- `admin_app/family_assignment.py` — already used on public notify / call routing; fleet shifts reuse the **same vehicle fields**

---

## Files already in sudo_admin (extend these)

| File | Role |
|------|------|
| `admin_app/fleet_service.py` | Plans, enrich, list, activate, cancel |
| `admin_app/fleet_views.py` | `manage_fleets`, `manage_fleet_detail` |
| `admin_app/templates/manage_fleets.html` | List + search + status filter |
| `admin_app/templates/manage_fleet_detail.html` | Activate / extend / cancel + drivers table |
| `admin_app/urls.py` | `fleets/`, `fleets/<fleet_id>/` |
| `admin_app/templates/base.html` | Sidebar **SudoTag Fleet** (`fa-truck`) |

Keep admin session gate: `request.session.get('admin')` → else redirect `admin_login`.

---

## Firestore structure (do not change field names)

### 1. `fleets/{fleetId}`

```json
{
  "ownerId": "<firebase_auth_uid>",
  "name": "Kerala Cabs",
  "gstin": "32ABCDE1234F1Z5",
  "city": "Kochi",
  "planId": "starter | business | enterprise",
  "billingCycle": "monthly | yearly",
  "subscriptionStatus": "none | pending | trialing | active | past_due | cancelled",
  "subscriptionExpiresAt": "<Timestamp | omitted>",
  "razorpayPaymentId": "<optional>",
  "razorpayOrderId": "<optional>",
  "vehicleLimit": 10,
  "driverLimit": 10,
  "createdAt": "<Timestamp>",
  "updatedAt": "<Timestamp>"
}
```

**Query (admin):** stream `fleets` (Admin SDK). Sort newest `createdAt` first on the server.

**Writes:**

- **Cloud Functions** after successful Razorpay (create or update by `ownerId`)
- **Django admin** activate / cancel via Admin SDK only
- **Mobile client** may only edit `name`, `gstin`, `city` (rules freeze plan/status/limits)

### 2. `fleet_drivers/{driverId}`

```json
{
  "fleetId": "<fleets doc id>",
  "ownerId": "<same as fleet.ownerId>",
  "name": "Ravi Kumar",
  "contactNumber": "9876543210",
  "note": "Night shift | Driver",
  "createdAt": "<Timestamp>"
}
```

Phone stored as **10-digit** Indian national number (same as family members).

**Admin:** read-only list on fleet detail (v1). Do not invent driver logins.

### 3. Shift assignment (existing vehicle fields)

When the owner saves a shift in the app, vehicles get:

- `assignedFamilyMemberId` = driver doc id  
- `assignedFamilyMemberName`  
- `assignedFamilyMemberContact`  
- `assignedUntil`  

Public QR SMS/voice already follow `family_assignment.py` / `effectiveContactNumber`. **Do not add a second routing path.**

---

## Required admin screens

### A. List — `/admin/fleets/` (`manage_fleets`)

- Search: fleet name, GSTIN, `ownerId`
- Filter: All / Active / Inactive (expired, cancelled, none)
- Columns: Fleet name, owner id, plan + cycle, status badge, expiry, Open
- Pagination (20)
- Empty copy: customers subscribe from the app **Me → SudoTag Fleet**

### B. Detail — `/admin/fleets/<fleet_id>/` (`manage_fleet_detail`)

Show: name, GSTIN, city, ownerId, plan, cycle, limits, status, expiry, last Razorpay ids if present.

**POST actions (CSRF):**

1. **Activate / extend** — `planId` + `billingCycle` → set `subscriptionStatus: active`, `subscriptionExpiresAt` now+30 or +365, copy `vehicleLimit` / `driverLimit` from plan table  
2. **Cancel** — `subscriptionStatus: cancelled` (confirm dialog). Do not delete the fleet or drivers.

Drivers table: name, phone, note.

### C. Sidebar

Label: **SudoTag Fleet**  
Active when path contains `/fleets/` or `/admin/fleets/`.

### D. Optional follow-ups (nice to have)

- Dashboard KPI: count of active fleets  
- CSV export of fleets  
- Link ownerId → `manage_users` / vehicles owned by that uid  
- List vehicles currently assigned to this fleet’s drivers (`assignedFamilyMemberId` in driver ids)

---

## Security

- Admin HTML views: session `admin` required. No public fleet pages.
- Do **not** expose activate/cancel as unauthenticated APIs.
- Mobile clients must not write `subscriptionStatus` / `planId` / limits / expiry (already in `firestore.rules`).
- Clearing assignment on vehicles uses `FieldValue.delete` (Flutter already does). Admin should not write `null` into Firestore `update()`.

---

## Acceptance checklist

- [ ] Sidebar **SudoTag Fleet** visible after admin login  
- [ ] List loads `fleets` from the **same** Firebase project as the app  
- [ ] Active badge uses status + expiry (not status string alone)  
- [ ] Activate sets plan limits and a future `subscriptionExpiresAt`  
- [ ] After activate, the **same owner** opens Me → SudoTag Fleet and sees the paid home (drivers / assign)  
- [ ] Cancel hides paid UI on mobile (`hasActiveSubscription == false`)  
- [ ] Drivers listed match `fleet_drivers` for that `fleetId`  
- [ ] QR notify/call still uses existing family assignment helpers — no duplicate contact logic  
- [ ] Plan IDs and INR prices match `lib/domain/entities/fleet.dart` and `functions/fleet_subscriptions.js`

---

## Do not do

- Do not build GPS / trip / fuel fleet software  
- Do not create a second `companies` collection  
- Do not change QR sticker checkout / `createOrder` coupon flow  
- Do not treat fleet drivers as `family_members` documents (different collection; same **vehicle** assignment fields only)

---

## How to run

1. Deploy mobile backend if not done: from the Flutter repo  
   `firebase deploy --only functions,firestore:rules,firestore:indexes`  
2. Run Django `sudo_admin`, log in, open sidebar **SudoTag Fleet**  
3. Test: subscribe in the app **or** activate from admin, then confirm mobile unlocks
