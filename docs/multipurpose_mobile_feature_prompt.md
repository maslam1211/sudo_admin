# Show multipurpose QR in the SudoTag app, and let the owner manage it

**Mobile project:** `/Users/muhmammedaslamt/Documents/sudo` (Flutter)  
**Admin project:** `/Users/muhmammedaslamt/Documents/GitHub/sudo_admin` (Django)

Use the existing Firestore collection `multipurpose_qrs`. Do not store these codes in `qrcodes`, and do not open the vehicle contact screen.

> **Goal:** Scanning a multipurpose QR inside the SudoTag app opens an in-app prompt. An unassigned code can be activated onto the signed-in account. An assigned code offers voice call, SMS, and push. The owner manages title and message from **Me → Multipurpose QR**.

---

## Already in place

### Admin (web)

- Generate from **Generate QR → Multipurpose**. Only a count is collected. Each code is saved as `qrType: Multipurpose QR`, `purpose: multipurpose`, `isAssigned: false`, with a unique `qrId`. No owner, contact, title, or message is stored at generation.
- Public web scan: unassigned → `multipurpose_activate.html` (OTP + account). Assigned → voice, message, push.
- `POST /admin/mp/{qrId}/contact/` with `{method: sms|push, message}` sends SMS (MSG91) or FCM. CSRF exempt so the app can call it.
- `POST /admin/api/call/register/` with `{qr_id}` and no `from` / `destination` uses the company caller and the number saved on the tag, then the client opens `tel:+918049649451`.

### Mobile

- Scan cubit treats a URL whose path contains `mp` as multipurpose (`QrCodeScanMultipurpose`).
- `QRScanScreen` opens `MultipurposeConnectScreen` instead of an in-app browser.
- **Me → Multipurpose QR** lists tags where `userID` is the signed-in user and can edit `title` and `note`.
- Push type `multipurpose_alert` is already labeled in notification history.

### Rules

`firestore.rules` on `multipurpose_qrs`:

- Signed-in users can read.
- Owner can edit public fields but cannot change `userID`, `isAssigned`, `contactNumber`, or `purpose`.
- An unassigned tag can be activated by the signed-in user (`isAssigned` false → true, `userID` = auth uid, `contactNumber` exactly 10 digits, `title` and `purpose` unchanged).
- Clients cannot create or delete these documents.

---

## In-app prompt (`MultipurposeConnectScreen`)

File: `lib/customer/multipurpose/multipurpose_connect_screen.dart`

1. Load `multipurpose_qrs/{qrId}`.
2. Missing or `purpose != multipurpose`: short unavailable message.
3. Not assigned:
   - Signed out: ask the user to sign in.
   - Signed in: **Activate with my account** copies the profile `contactNumber` (10 digits) and `fullName` onto the tag and sets `isAssigned: true`, `userID`, `assignedAt`.
4. Assigned:
   - Show title and note. Do not show the saved mobile number.
   - Message box, then **Voice call**, **Message**, **Push notification**.
   - If `userID` is the current user, tell them to edit the tag from **Me → Multipurpose QR**.

Voice call posts `{qr_id}` to `https://sudotag.com/admin/api/call/register/` and then opens `tel:+918049649451`.  
Message and push post `{method, message}` to `https://sudotag.com/admin/mp/{qrId}/contact/`.

---

## Do not

- Do not route multipurpose scans to `CustomerDetailScreen` or the vehicle notify web page.
- Do not write multipurpose tags into `qrcodes` or `vehicles`.
- Do not let the scanner see `contactNumber`.
- Do not let a client change plan-like ownership fields after activation except through the owner-edit rule (title / note).
