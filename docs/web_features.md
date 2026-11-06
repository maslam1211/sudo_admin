# SudoTag web features

**Project:** `/Users/muhmammedaslamt/Documents/GitHub/sudo_admin` (Django)  
**Site:** public pages at `/`, admin dashboard at `/admin/`

This file lists what the web app does today. Customer subscribe, drivers, and day-to-day vehicle ownership stay in the Flutter app.

---

## Public website

| Feature | Path | What it does |
|---------|------|----------------|
| Landing | `/` | Home, About, Features, contact, and Buy Now |
| Scan QR / plate | `/#find-vehicle` | Camera or photo scan, or typed QR id / plate. Looks up the vehicle and opens notify or activate |
| How it works | `/how-it-works/` | Explains scan, contact, and activation |
| Terms | `/terms/` | Terms of use |
| Privacy | `/privacy/` | Privacy policy |
| Referral invite | `/r/{CODE}` | Opens the invite shared from the app |
| Feedback | `/admin/feedback/` | Public feedback form; approved items can show on the site |

---

## Buy QR stickers

| Feature | Path | What it does |
|---------|------|----------------|
| Buy Now | `/buy/` | Product checkout (price and coupons come from admin settings) |
| Create order | `POST /admin/api/checkout/create-order/` | Starts Razorpay |
| Verify payment | `POST /admin/api/checkout/verify-payment/` | Confirms payment and records the order |
| Validate coupon | `POST /admin/api/checkout/validate-coupon/` | Checks a web coupon before pay |
| Result pages | `/buy/success/`, `/buy/failed/`, `/buy/cancelled/`, `/buy/pending/` | Payment outcome |

---

## Scan and contact (no login)

Vehicle tags and multipurpose tags are separate. Vehicle scans do not open the multipurpose screen, and multipurpose scans do not open the vehicle contact screen.

### Vehicle QR

| Step | Path | What it does |
|------|------|----------------|
| Scan | `/admin/send-notification/{qr_id}/` | Assigned tag opens the contact screen. Unassigned tag goes to activate |
| Notify | `/admin/send-notification-final/{qr_id}/` | Sends the owner a message (push / SMS path already wired) |
| Live status | `…/live-status/` | Reads the owner’s current status for the scanner |
| Activate | `/admin/activate-id/{qr_id}/` | OTP, then links the sticker to an account and vehicle |
| Plate / QR lookup | `POST /admin/api/public-lookup-vehicle/` | Used by the landing Scan QR / plate box |

Contact options on an assigned vehicle tag: masked voice, SMS, and push. The scanner does not see the owner’s personal number. Voice posts to call register, then the phone dials the company number.

### Multipurpose QR (Smart Tag)

| Step | Path | What it does |
|------|------|----------------|
| Scan | `/admin/mp/{qr_id}/` | Unassigned: OTP and activate onto an account. Assigned: voice, message, push |
| Contact | `POST /admin/mp/{qr_id}/contact/` | `{method: sms\|push, message}` sends SMS (MSG91) or FCM |
| Activate OTP | `/admin/mp/{qr_id}/otp/send|resend|verify/` | Phone verification during activation |

Stored in Firestore `multipurpose_qrs`, not in `qrcodes`.

### Masked voice

1. `POST /admin/api/call/register` stores who should be reached for this caller.
2. The PBX calls `POST /admin/api/call` and gets that destination.
3. Fleet shifts and family temp-assign reuse the vehicle’s effective contact number.

---

## Admin dashboard

Login is at `/admin/login/` (OTP). `/admin/` redirects there. Sidebar screens:

### QR

| Screen | Path | What it does |
|--------|------|----------------|
| Generate QR | `/admin/generate-qr/` | Batch-create vehicle QR or multipurpose QR. Multipurpose only asks for a count |
| Download PDF | `/admin/download-qr-pdf/` | Print sheet for generated codes |
| QR Codes | `/admin/manage-qrs/` | List, search, regenerate, delete vehicle codes |
| Smart Tags | `/admin/manage-multipurpose-qrs/` | List and open multipurpose codes |
| Assign QR | `/admin/assign-qr/` | Attach a vehicle QR to a user and vehicle |
| Assign Smart Tag | `/admin/assign-multipurpose-qr/` | Attach a multipurpose code to a registered user |

### Orders and money

| Screen | Path | What it does |
|--------|------|----------------|
| Orders | `/admin/view-orders/` | List orders, update status, export with QR |
| Payments | `/admin/view-payments/` | Payment records |
| Product Price | `/admin/manage-product-price/` | Sticker price used by Buy Now |
| Web Coupons | `/admin/manage-checkout-coupons/` | Coupons and checkout settings for the website |

### People, vehicles, fleet

| Screen | Path | What it does |
|--------|------|----------------|
| Dashboard | `/admin/dashboard/` | Users, orders, earnings, vehicle QR, Smart Tag, active fleets |
| Users | `/admin/manage-users/` | Registered accounts |
| Vehicles | `/admin/manage-vehicles/` | Vehicle list and per-vehicle detail |
| Live Status | `/admin/manage-live-status/` | Owner availability shown to scanners |
| Daily Usage | `/admin/manage-daily-usage/` | Usage counts |
| Wallet | `/admin/rewards/` | Wallets, issue reports, redemptions, reward catalog |
| Referrals | `/admin/referrals/` | Referral list, detail, referrer history, CSV export |
| SudoTag Fleet | `/admin/fleets/` | Fleet subscriptions: plan, drivers, offline activate / extend / cancel, CSV export |

Fleet plans (INR): Starter ₹999 / ₹9,999, Business ₹2,999 / ₹29,999, Enterprise ₹7,999 / ₹79,999. Drivers and shift assign stay in the app. Admin can activate a plan after an offline GST payment.

### Content and safety

| Screen | Path | What it does |
|--------|------|----------------|
| Feedback | `/admin/view-feedback/` | Review, edit, approve, or delete feedback |
| Ads | `/admin/manage-ads/` | Banner, marquee, and popup ads. Public read: `/admin/api/active-ads/{ad_type}/` |
| Push notification | `/admin/promotion-notification/` | Send a promotion push |
| Archived data | `/admin/archived/data/` | Users and vehicles removed from the live app, with CSV export |
| Delete data | `/admin/delete-data/` | PIN-gated delete of Firestore collections and Auth users |

### Server hooks (not sidebar)

| Hook | Path | What it does |
|------|------|----------------|
| Archive user | `POST /admin/api/archive-deleted-user/` | Stores a deleted account for the archive screen |
| Lost Mode on | `POST /admin/api/lost-mode-enabled/` | Sends the existing vehicle-issue SMS to the owner |

---

## Related docs

- `docs/fleet_admin_web_feature_prompt.md` — fleet admin rules and Firestore shape
- `docs/multipurpose_mobile_feature_prompt.md` — Smart Tag behavior shared with the app
