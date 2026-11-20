"""Numbers behind the Analytics page and the dashboard growth chart.

`load(db)` pulls the few fields each chart needs from Firestore (cached), and
`compute(data, days, today)` turns them into chart-ready series. `compute` is
pure, so tests feed it plain dicts.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta

import pytz
from django.core.cache import cache

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')
RANGES = {'7': 7, '30': 30, '90': 90, '365': 365, 'all': 0}
DEFAULT_RANGE = '30'
CACHE_KEY = 'analytics_raw_v2'
CACHE_SECONDS = 300
ADMIN_EMAIL = 'sudotagonline@gmail.com'
BRIDGE_PURPOSE = 'multipurpose_call_bridge'
WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
PLATFORM_NAMES = {'ios': 'iOS', 'android': 'Android', 'web': 'Web'}
STATUS_NAMES = {0: 'Pending', 1: 'Processing', 2: 'Shipped', 3: 'Delivered', 4: 'Cancelled',
                5: 'Returned', 6: 'Failed', 7: 'On hold'}

FIELDS = {
    'users': ['createdAt', 'city', 'district', 'appPlatform', 'appVersion', 'isOnline', 'lastSeen',
              'profileComplete', 'accountDeleted', 'purpose', 'emailAddress', 'fullName'],
    'vehicles': ['createdAt', 'ownerId', 'vehicleType', 'make', 'model', 'registrationNumber', 'ownerFullName',
                 'isQrGenerated', 'isLostMode'],
    'qrcodes': ['createdDateTime', 'assignedAt', 'isAssigned', 'userID', 'purpose'],
    'orders': ['timestamp', 'amount', 'paymentStatus', 'orderStatus', 'source', 'placedVia', 'channel', 'fullName'],
    'community_posts': ['createdAt', 'category', 'status', 'moderationStatus', 'reportsCount', 'isDeleted', 'title',
                        'authorName'],
    'multipurpose_qrs': ['createdDateTime', 'assignedAt', 'isAssigned', 'purpose', 'categoryLabel', 'category',
                         'scanCount'],
}


# ---------------------------------------------------------------- loading

def _stream(db, name, fields, limit=10000):
    col = db.collection(name)
    try:
        docs = col.select(fields).limit(limit).stream()
        return [dict(d.to_dict() or {}, _id=d.id) for d in docs]
    except Exception:
        logger.exception('analytics: select() on %s failed, reading full documents', name)
        return [dict(d.to_dict() or {}, _id=d.id) for d in col.limit(limit).stream()]


def load(db, fresh=False):
    """Raw rows per collection. Cached for five minutes; `fresh` skips the cache."""
    if not fresh:
        hit = cache.get(CACHE_KEY)
        if hit is not None:
            return hit
    data = {}
    for name, fields in FIELDS.items():
        try:
            data[name] = _stream(db, name, fields)
        except Exception:
            logger.exception('analytics: could not read %s', name)
            data[name] = []
    data['loaded_at'] = datetime.now(IST)
    cache.set(CACHE_KEY, data, CACHE_SECONDS)
    return data


# ---------------------------------------------------------------- helpers

def to_ist(value):
    """Firestore timestamp / datetime / ISO string -> aware IST datetime, or None."""
    if value is None or value == '':
        return None
    if hasattr(value, 'to_datetime') and not isinstance(value, datetime):
        try:
            value = value.to_datetime()
        except Exception:
            return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value.astimezone(IST) if value.tzinfo else IST.localize(value)
    if isinstance(value, date):
        return IST.localize(datetime(value.year, value.month, value.day))
    return None


def _day(value):
    dt = to_ist(value)
    return dt.date() if dt else None


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _clean(text):
    return ' '.join(str(text or '').split()).strip()


def _title(text):
    t = _clean(text)
    return t[:1].upper() + t[1:] if t else ''


def _place(text):
    """'KOZHIKODE' and 'kozhikode' both become 'Kozhikode' so they count together."""
    t = _clean(text)
    return t.title() if t.isupper() or t.islower() else t


def top_counts(values, n=7, other='Other'):
    """[(label, count)] for the n most common values; the rest folds into Other."""
    counts = Counter(v for v in values if v)
    ranked = counts.most_common()
    head = ranked[:n]
    rest = sum(c for _, c in ranked[n:])
    if rest:
        head.append((other, rest))
    return head


class Buckets:
    """Maps dates onto daily, weekly or monthly bars for the chosen range."""

    def __init__(self, days, today, earliest=None):
        self.days, self.today = days, today
        if days and days <= 90:
            self.unit = 'day'
            self.start = today - timedelta(days=days - 1)
        elif days:
            self.unit = 'week'
            self.start = self._week(today - timedelta(days=days - 1))
        else:
            self.unit = 'month'
            first = earliest or today
            self.start = date(first.year, first.month, 1)
        self.keys = self._keys()
        self.index = {k: i for i, k in enumerate(self.keys)}

    @staticmethod
    def _week(d):
        return d - timedelta(days=d.weekday())

    def _keys(self):
        keys, cur = [], self.start
        while cur <= self.today:
            keys.append(cur)
            if self.unit == 'day':
                cur += timedelta(days=1)
            elif self.unit == 'week':
                cur += timedelta(days=7)
            else:
                cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        return keys

    def key_for(self, d):
        if d is None or d < self.start or d > self.today:
            return None
        if self.unit == 'day':
            return d
        if self.unit == 'week':
            return self._week(d)
        return date(d.year, d.month, 1)

    def labels(self):
        if self.unit == 'month':
            return [k.strftime('%b %y') for k in self.keys]
        return [f"{k.day} {k.strftime('%b')}" for k in self.keys]

    def series(self, days_list, weights=None):
        out = [0] * len(self.keys)
        for i, d in enumerate(days_list):
            k = self.key_for(d)
            if k is not None:
                out[self.index[k]] += weights[i] if weights else 1
        return out


def _in(d, start, end):
    return d is not None and start <= d <= end


def _delta(cur, prev):
    """Percent change, or None when there is nothing to compare against."""
    if not prev:
        return None
    return round((cur - prev) / prev * 100)


# ---------------------------------------------------------------- compute

def _real_users(users):
    return [u for u in users
            if u.get('purpose') != BRIDGE_PURPOSE
            and _clean(u.get('emailAddress')).lower() != ADMIN_EMAIL
            and not u.get('accountDeleted')]


def compute(data, days=30, today=None):
    today = today or datetime.now(IST).date()
    users = _real_users(data.get('users', []))
    vehicles = data.get('vehicles', [])
    qrs = [q for q in data.get('qrcodes', []) if q.get('purpose') != BRIDGE_PURPOSE]
    orders = data.get('orders', [])
    posts = data.get('community_posts', [])
    tags = [t for t in data.get('multipurpose_qrs', []) if t.get('purpose') in (None, 'multipurpose')]

    user_days = [_day(u.get('createdAt')) for u in users]
    vehicle_days = [_day(v.get('createdAt')) for v in vehicles]
    activation_days = [_day(q.get('assignedAt')) for q in qrs if q.get('isAssigned')]
    print_days = [_day(q.get('createdDateTime')) for q in qrs]
    paid = [o for o in orders if o.get('paymentStatus') == 'paid']
    order_days = [_day(o.get('timestamp')) for o in orders]
    paid_days = [_day(o.get('timestamp')) for o in paid]
    paid_amounts = [_num(o.get('amount')) for o in paid]
    post_days = [_day(p.get('createdAt')) for p in posts]

    known = [d for d in user_days + vehicle_days + activation_days + order_days + post_days if d]
    b = Buckets(days, today, earliest=min(known) if known else None)

    # Current vs previous window for the KPI deltas.
    if days:
        cur_start, cur_end = today - timedelta(days=days - 1), today
        prev_start, prev_end = cur_start - timedelta(days=days), cur_start - timedelta(days=1)
    else:
        cur_start, cur_end = b.start, today
        prev_start = prev_end = None

    def window(day_list, weights=None):
        cur = sum((weights[i] if weights else 1) for i, d in enumerate(day_list) if _in(d, cur_start, cur_end))
        if prev_start is None:
            return cur, None
        prev = sum((weights[i] if weights else 1) for i, d in enumerate(day_list) if _in(d, prev_start, prev_end))
        return cur, prev

    def kpi(key, label, icon, day_list, weights=None, money=False, href=None):
        cur, prev = window(day_list, weights)
        return {
            'key': key, 'label': label, 'icon': icon, 'value': round(cur, 2) if money else cur,
            'prev': prev, 'delta': _delta(cur, prev), 'money': money, 'href': href,
            'spark': b.series(day_list, weights),
        }

    kpis = [
        kpi('users', 'New customers', 'fa-user-plus', user_days, href='manage_users'),
        kpi('vehicles', 'Vehicles added', 'fa-car', vehicle_days, href='manage_vehicles'),
        kpi('activations', 'QR activations', 'fa-qrcode', activation_days, href='manage_qrs'),
        kpi('revenue', 'Revenue', 'fa-rupee-sign', paid_days, paid_amounts, money=True, href='view_orders'),
        kpi('posts', 'Civic Sense posts', 'fa-city', post_days, href='civic_sense_reports'),
    ]

    # Growth: three counts on one scale (same unit, so one axis is honest).
    growth = {
        'labels': b.labels(),
        'unit': b.unit,
        'series': [
            {'key': 'users', 'label': 'Customers', 'noun': 'new customers', 'data': b.series(user_days)},
            {'key': 'vehicles', 'label': 'Vehicles', 'noun': 'vehicles added', 'data': b.series(vehicle_days)},
            {'key': 'activations', 'label': 'QR activations', 'noun': 'QR activations', 'data': b.series(activation_days)},
        ],
    }

    # Cumulative customers across the range, starting from everyone who joined before it.
    before = sum(1 for d in user_days if d and d < b.start)
    undated = sum(1 for d in user_days if d is None)
    running, cumulative = before + undated, []
    for n in growth['series'][0]['data']:
        running += n
        cumulative.append(running)

    # Customer funnel (all time).
    user_ids = {u['_id'] for u in users}
    owners = {v.get('ownerId') for v in vehicles if v.get('ownerId')}
    active_owners = {q.get('userID') for q in qrs if q.get('isAssigned') and q.get('userID')}
    funnel = [
        {'label': 'Signed up', 'value': len(users)},
        {'label': 'Added a vehicle', 'value': len(user_ids & owners)},
        {'label': 'Activated a QR', 'value': len(user_ids & owners & active_owners)},
    ]
    profile = {'label': 'Completed profile', 'value': sum(1 for u in users if u.get('profileComplete'))}
    top = funnel[0]['value'] or 1
    for step in funnel + [profile]:
        step['pct'] = round(step['value'] / top * 100)

    # Sign-up heatmap: weekday x 3-hour block (IST), within the range.
    heat = [[0] * 8 for _ in range(7)]
    for u in users:
        dt = to_ist(u.get('createdAt'))
        if dt and _in(dt.date(), cur_start, cur_end):
            heat[dt.weekday()][dt.hour // 3] += 1
    heatmap = {
        'rows': WEEKDAYS,
        'cols': ['12a', '3a', '6a', '9a', '12p', '3p', '6p', '9p'],
        'cells': heat,
        'max': max(max(r) for r in heat),
        'total': sum(sum(r) for r in heat),
    }

    # Engagement from lastSeen.
    now = datetime.now(IST)
    seen = [to_ist(u.get('lastSeen')) for u in users]
    engagement = {
        'day': sum(1 for s in seen if s and now - s <= timedelta(days=1)),
        'week': sum(1 for s in seen if s and now - s <= timedelta(days=7)),
        'month': sum(1 for s in seen if s and now - s <= timedelta(days=30)),
        'total': len(users),
    }

    cities = top_counts([_place(u.get('city') or u.get('district')) for u in users], 7)
    platforms = top_counts([PLATFORM_NAMES.get(_clean(u.get('appPlatform')).lower(), _title(u.get('appPlatform')))
                            for u in users], 4)
    versions = top_counts([_clean(u.get('appVersion')) for u in users], 5, other='Older / other')
    no_app = sum(1 for u in users if not _clean(u.get('appVersion')))

    vehicle_types = top_counts([_title(v.get('vehicleType')) for v in vehicles], 6)
    makes = top_counts([_title(v.get('make')) for v in vehicles], 7)
    lost_mode = sum(1 for v in vehicles if v.get('isLostMode'))

    # QR stock and how long a printed sticker waits before it is activated.
    assigned = [q for q in qrs if q.get('isAssigned')]
    wait_bins = [('Same day', 0, 0), ('1–7 days', 1, 7), ('8–30 days', 8, 30),
                 ('1–3 months', 31, 90), ('3+ months', 91, 10 ** 6)]
    waits = []
    for q in assigned:
        made, used = _day(q.get('createdDateTime')), _day(q.get('assignedAt'))
        if made and used and used >= made:
            waits.append((used - made).days)
    waits.sort()
    qr_stock = {
        'total': len(qrs),
        'assigned': len(assigned),
        'unassigned': len(qrs) - len(assigned),
        'rate': round(len(assigned) / len(qrs) * 100) if qrs else 0,
        'median_wait': waits[len(waits) // 2] if waits else None,
        'dated': len(waits),
        'undated': len(assigned) - len([q for q in assigned if _day(q.get('assignedAt'))]),
        'wait_bins': [(name, sum(1 for w in waits if lo <= w <= hi)) for name, lo, hi in wait_bins],
        'printed': b.series(print_days),
        'activated': b.series(activation_days),
    }

    # Orders and revenue.
    statuses = Counter(STATUS_NAMES.get(o.get('orderStatus'), 'Other') for o in orders)
    web = sum(1 for o in orders if o.get('source') == 'website' or o.get('placedVia') == 'Website'
              or o.get('channel') == 'web')
    revenue = {
        'labels': b.labels(),
        'amounts': b.series(paid_days, paid_amounts),
        'orders': b.series(order_days),
        'total': round(sum(paid_amounts), 2),
        'count': len(orders),
        'paid': len(paid),
        'aov': round(sum(paid_amounts) / len(paid)) if paid else 0,
        'status': [(name, statuses.get(name, 0)) for name in STATUS_NAMES.values() if statuses.get(name)],
        'channels': [('App', len(orders) - web), ('Website', web)],
        'unpaid_count': len(orders) - len(paid),
        'unpaid_amount': round(sum(_num(o.get('amount')) for o in orders
                                   if o.get('paymentStatus') != 'paid' and o.get('orderStatus') not in (4, 6)), 2),
    }

    def post_state(p):
        if p.get('isDeleted') or p.get('status') == 'removed' or p.get('moderationStatus') == 'rejected':
            return 'Removed'
        if int(_num(p.get('reportsCount'))) > 0:
            return 'Reported'
        if p.get('moderationStatus') == 'pending':
            return 'Pending'
        return 'Live'

    civic = {
        'total': len(posts),
        'series': b.series(post_days),
        'categories': top_counts([_title(p.get('category')) for p in posts], 6),
        'states': [(s, sum(1 for p in posts if post_state(p) == s)) for s in ('Live', 'Reported', 'Pending', 'Removed')],
    }

    smart = {
        'total': len(tags),
        'assigned': sum(1 for t in tags if t.get('isAssigned')),
        'scans': int(sum(_num(t.get('scanCount')) for t in tags)),
        'categories': top_counts([_title(t.get('categoryLabel') or t.get('category')) for t in tags], 6),
    }

    return {
        'range_days': days,
        'unit': b.unit,
        'kpis': kpis,
        'growth': growth,
        'cumulative': {'labels': b.labels(), 'data': cumulative, 'start': before + undated},
        'funnel': funnel,
        'profile': profile,
        'heatmap': heatmap,
        'engagement': engagement,
        'cities': cities,
        'platforms': platforms,
        'versions': versions,
        'no_app': no_app,
        'vehicle_types': vehicle_types,
        'makes': makes,
        'lost_mode': lost_mode,
        'vehicles_total': len(vehicles),
        'qr': qr_stock,
        'revenue': revenue,
        'civic': civic,
        'smart': smart,
    }


SLOT_NAMES = ['12–3 AM', '3–6 AM', '6–9 AM', '9 AM–12 PM', '12–3 PM', '3–6 PM', '6–9 PM', '9 PM–12 AM']
FULL_DAYS = ['Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays', 'Sundays']


def _inr(n):
    n = int(round(n or 0))
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ','.join(parts) + ',' + tail
    return ('-' if n < 0 else '') + '₹' + s


def _note(tone, headline, detail='', action=None, url=None, weight=0, icon='fa-lightbulb'):
    return {'tone': tone, 'headline': headline, 'detail': detail, 'action': action, 'url': url,
            'weight': weight, 'icon': icon}


def insights(s):
    """Plain-language takeaways for each chart, plus the top few for the summary panel.

    `tone` is good / warn / alert / info. `url` is a URL name; the view resolves it.
    """
    out = {}
    period = 'this period' if not s['range_days'] else f"the last {s['range_days']} days"
    kpi = {k['key']: k for k in s['kpis']}

    # Growth
    users = kpi['users']
    g = s['growth']['series'][0]['data']
    if users['value']:
        peak = max(range(len(g)), key=lambda i: g[i])
        when = s['growth']['labels'][peak]
        if users['delta'] is not None and users['delta'] > 0:
            out['growth'] = _note('good', f"Sign-ups are up {users['delta']}%.",
                                  f"{users['value']} new customers in {period}, versus {users['prev']} before. "
                                  f"The busiest {s['unit']} was {when}.", weight=60, icon='fa-arrow-up')
        elif users['delta'] is not None and users['delta'] < 0:
            out['growth'] = _note('warn', f"Sign-ups are down {abs(users['delta'])}%.",
                                  f"{users['value']} new customers in {period}, versus {users['prev']} before. "
                                  "A push campaign or a social post could help.",
                                  'Send a push', 'manage_promotion_notification', weight=80, icon='fa-arrow-down')
        else:
            out['growth'] = _note('info', f"{users['value']} new customers in {period}.",
                                  f"The busiest {s['unit']} was {when}.", weight=20, icon='fa-chart-bar')
    else:
        out['growth'] = _note('warn', 'No new customers in this period.',
                              'Try a promotion or check that sign-up works in the app.', weight=90, icon='fa-user-slash')

    # Customer base
    c = s['cumulative']
    now_total = c['data'][-1] if c['data'] else 0
    added = now_total - c['start'] if c['data'] else 0
    if c['start'] and added:
        out['base'] = _note('good', f"The customer base grew {round(added / c['start'] * 100)}%.",
                            f"From {c['start']} to {now_total} customers in {period}.", icon='fa-users')
    else:
        out['base'] = _note('info', f"{now_total} customers in total.", '', icon='fa-users')

    # Journey: find the biggest drop between steps
    f = s['funnel']
    if f[0]['value']:
        drops = [(f[i]['value'] - f[i + 1]['value'], i) for i in range(len(f) - 1)]
        lost, i = max(drops)
        if lost > 0:
            nxt = f[i + 1]['label'].lower()
            tone = 'alert' if f[i + 1]['pct'] < 60 else 'warn'
            if i == 0:
                out['funnel'] = _note(tone, f"{lost} customers signed up but never added a vehicle.",
                                      f"Only {f[1]['pct']}% get that far, the biggest drop-off. Without a vehicle they "
                                      "can't use a QR sticker, so a reminder push could win them back.",
                                      'Send a reminder', 'manage_promotion_notification', weight=95, icon='fa-car-side')
            else:
                out['funnel'] = _note(tone, f"{lost} customers added a vehicle but never activated a QR.",
                                      f"That's the biggest drop-off, before \"{nxt}\". They may not have a sticker yet. "
                                      "Check for unshipped orders or offer one.",
                                      'View orders', 'view_orders', weight=90, icon='fa-qrcode')
        else:
            out['funnel'] = _note('good', 'Everyone who signs up goes on to activate a QR.', '', weight=10, icon='fa-check')
    else:
        out['funnel'] = _note('info', 'No customers yet.', '', icon='fa-users')

    # Heatmap
    h = s['heatmap']
    if h['total']:
        best = max(((v, d, t) for d, row in enumerate(h['cells']) for t, v in enumerate(row)))
        day_tot = [sum(r) for r in h['cells']]
        top_day = max(range(7), key=lambda d: day_tot[d])
        slot_tot = [sum(h['cells'][d][t] for d in range(7)) for t in range(8)]
        top_slot = max(range(8), key=lambda t: slot_tot[t])
        out['heat'] = _note('info', f"Most people sign up on {FULL_DAYS[top_day]}, {SLOT_NAMES[top_slot]}.",
                            f"{slot_tot[top_slot]} of {h['total']} sign-ups were in that time slot. That's the best time "
                            "for push notifications and ads.", weight=40, icon='fa-clock')
    else:
        out['heat'] = _note('info', 'No sign-ups in this period yet.', '', icon='fa-clock')

    # Engagement
    e = s['engagement']
    if e['total']:
        month_pct = round(e['month'] / e['total'] * 100)
        tone = 'good' if month_pct >= 50 else 'warn' if month_pct >= 25 else 'alert'
        out['engagement'] = _note(tone, f"{month_pct}% of customers opened the app this month.",
                                  f"{e['day']} in the last day, {e['week']} in the last week. "
                                  f"{e['total'] - e['month']} haven't opened it in over 30 days.",
                                  'Re-engage them' if tone != 'good' else None,
                                  'manage_promotion_notification' if tone != 'good' else None,
                                  weight=70 if tone == 'alert' else 45, icon='fa-mobile-alt')
    if s['no_app'] and e['total']:
        out['versions'] = _note('info', f"{e['total'] - s['no_app']} of {e['total']} customers report an app version.",
                                "Older app builds don't send it, so this fills in as people update.", icon='fa-mobile')

    # QR stock
    q = s['qr']
    if q['total']:
        unused = 100 - q['rate']
        tone = 'alert' if q['unassigned'] < 50 else 'warn' if q['rate'] < 25 else 'good'
        if q['unassigned'] < 50:
            out['qr'] = _note('alert', f"Only {q['unassigned']} QR stickers left in stock.",
                              'Print a new batch before you run out.', 'Generate QR', 'generate_qr', weight=100, icon='fa-layer-group')
        else:
            detail = f"{q['unassigned']} of {q['total']} printed stickers ({unused}%) haven't been linked to a vehicle yet."
            if q['median_wait'] is not None:
                detail += f" When they are, it takes a median of {q['median_wait']} days after printing."
            out['qr'] = _note(tone, f"{q['rate']}% of printed QR stickers are in use.", detail,
                              'Assign a QR', 'assign_qr', weight=50 if tone == 'warn' else 15, icon='fa-qrcode')

    # Vehicles
    vt = s['vehicle_types']
    if vt and s['vehicles_total']:
        top_label, top_n = vt[0][0], vt[0][1]
        share = round(top_n / s['vehicles_total'] * 100)
        mk = s['makes'][0] if s['makes'] else None
        out['vehicles'] = _note('info', f"{top_label}s are {share}% of all vehicles.",
                                (f"{mk[0]} is the most common make ({mk[1]}). " if mk else '') +
                                'Design stickers and ads with them in mind.', icon='fa-car')
    if s['lost_mode']:
        out['lost'] = _note('alert', f"{s['lost_mode']} vehicle{'s are' if s['lost_mode'] > 1 else ' is'} in lost mode.",
                            'Owners have marked these as lost or stolen.', 'View vehicles', 'manage_vehicles',
                            weight=85, icon='fa-exclamation-triangle')

    # Cities
    ct = [x for x in s['cities'] if x[0] != 'Other']
    if ct and e['total']:
        share = round(ct[0][1] / e['total'] * 100)
        second = f" {ct[1][0]} is next with {ct[1][1]}." if len(ct) > 1 else ''
        out['cities'] = _note('info', f"{ct[0][0]} is your biggest market: {share}% of customers.",
                              f"{ct[0][1]} customers live there.{second} Local promotions there reach the most people.",
                              weight=30, icon='fa-map-marker-alt')

    # Revenue
    r = s['revenue']
    if r['unpaid_count'] and r['unpaid_amount']:
        out['revenue'] = _note('alert', f"{_inr(r['unpaid_amount'])} is waiting on payment.",
                               f"{r['unpaid_count']} of {r['count']} orders aren't marked as paid. Check the payments "
                               "and follow up with those customers.", 'Check payments', 'view_orders', weight=92,
                               icon='fa-rupee-sign')
    elif r['count']:
        out['revenue'] = _note('good', f"All {r['count']} orders are paid.",
                               f"{_inr(r['total'])} collected, {_inr(r['aov'])} per order on average.", icon='fa-check')
    else:
        out['revenue'] = _note('info', 'No orders yet.', '', icon='fa-shopping-bag')
    ch = dict((x[0], x[1]) for x in r['channels'])
    if r['count']:
        web_pct = round(ch.get('Website', 0) / r['count'] * 100)
        out['channels'] = _note('info', f"{web_pct}% of orders come from the website.",
                                f"{ch.get('App', 0)} from the app, {ch.get('Website', 0)} from the website.", icon='fa-globe')

    # Civic Sense
    cv = s['civic']
    states = dict(cv['states'])
    if states.get('Reported'):
        out['civic'] = _note('alert', f"{states['Reported']} Civic Sense post{'s' if states['Reported'] > 1 else ''} reported.",
                             'Review and remove anything that breaks the rules.', 'Review reports', 'civic_sense_reports',
                             weight=88, icon='fa-flag')
    elif cv['total']:
        out['civic'] = _note('good', 'No open reports in Civic Sense.',
                             f"{cv['total']} post{'s' if cv['total'] != 1 else ''} so far, {states.get('Removed', 0)} removed by moderators.",
                             icon='fa-check')
    else:
        out['civic'] = _note('info', 'No Civic Sense posts yet.', '', icon='fa-city')

    # Smart Tags
    sm = s['smart']
    if sm['total']:
        per = round(sm['scans'] / sm['assigned'], 1) if sm['assigned'] else 0
        out['smart'] = _note('info', f"{sm['assigned']} of {sm['total']} Smart Tags are active.",
                             f"They've been scanned {sm['scans']} times, about {per} scans per active tag.", icon='fa-tag')

    ranked = sorted((n for n in out.values() if isinstance(n, dict) and n.get('weight')),
                    key=lambda n: -n['weight'])
    out['top'] = ranked[:4]
    return out


def _first(name):
    name = _clean(name)
    return name.split(' ')[0].title() if name else 'Someone'


def activity(data, limit=8):
    """Latest events across collections, newest first, for the dashboard feed."""
    events = []
    for u in _real_users(data.get('users', [])):
        at = to_ist(u.get('createdAt'))
        if at:
            city = _place(u.get('city'))
            events.append({'at': at, 'kind': 'user', 'icon': 'fa-user-plus',
                           'text': f"{_first(u.get('fullName'))} joined SudoTag" + (f" from {city}" if city else ''),
                           'url': 'manage_users'})
    for v in data.get('vehicles', []):
        at = to_ist(v.get('createdAt'))
        if at:
            make, model = _clean(v.get('make')), _clean(v.get('model'))
            car = model if make and model.lower().startswith(make.lower()) else ' '.join(x for x in (make, model) if x)
            car = car or _title(v.get('vehicleType')) or 'a vehicle'
            reg = _clean(v.get('registrationNumber')).upper()
            events.append({'at': at, 'kind': 'vehicle', 'icon': 'fa-car',
                           'text': f"{_first(v.get('ownerFullName'))} added {car}" + (f" · {reg}" if reg else ''),
                           'url': 'manage_vehicles'})
    for q in data.get('qrcodes', []):
        at = to_ist(q.get('assignedAt'))
        if at and q.get('isAssigned') and q.get('purpose') != BRIDGE_PURPOSE:
            events.append({'at': at, 'kind': 'qr', 'icon': 'fa-qrcode',
                           'text': f"QR {str(q.get('_id', ''))[:8]}… activated on a vehicle", 'url': 'manage_qrs'})
    for o in data.get('orders', []):
        at = to_ist(o.get('timestamp'))
        if at:
            paid = o.get('paymentStatus') == 'paid'
            events.append({'at': at, 'kind': 'order', 'icon': 'fa-shopping-bag',
                           'text': f"{_first(o.get('fullName'))} ordered for {_inr(_num(o.get('amount')))}" +
                                   ('' if paid else ' · payment pending'),
                           'url': 'view_orders'})
    for p in data.get('community_posts', []):
        at = to_ist(p.get('createdAt'))
        if at:
            title = _clean(p.get('title')) or 'a post'
            events.append({'at': at, 'kind': 'civic', 'icon': 'fa-city',
                           'text': f"{_first(p.get('authorName'))} posted “{title[:40]}” in Civic Sense",
                           'url': 'civic_sense_reports'})
    events.sort(key=lambda e: e['at'], reverse=True)
    out = events[:limit]
    for e in out:
        e['iso'] = e['at'].isoformat()
    return out


def month_pace(data, today=None):
    """This month so far vs the whole of last month, with a straight-line projection."""
    today = today or datetime.now(IST).date()
    this_start = today.replace(day=1)
    last_end = this_start - timedelta(days=1)
    last_start = last_end.replace(day=1)
    next_month = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    days_in_month = (next_month - this_start).days
    elapsed = today.day

    users = _real_users(data.get('users', []))
    qrs = [q for q in data.get('qrcodes', []) if q.get('purpose') != BRIDGE_PURPOSE and q.get('isAssigned')]
    paid = [o for o in data.get('orders', []) if o.get('paymentStatus') == 'paid']
    series = [
        ('customers', 'New customers', [(_day(u.get('createdAt')), 1) for u in users], False),
        ('vehicles', 'Vehicles added', [(_day(v.get('createdAt')), 1) for v in data.get('vehicles', [])], False),
        ('activations', 'QR activations', [(_day(q.get('assignedAt')), 1) for q in qrs], False),
        ('revenue', 'Revenue', [(_day(o.get('timestamp')), _num(o.get('amount'))) for o in paid], True),
    ]
    out = []
    for key, label, rows, money in series:
        now_v = sum(w for d, w in rows if d and this_start <= d <= today)
        last_v = sum(w for d, w in rows if d and last_start <= d <= last_end)
        projected = round(now_v / elapsed * days_in_month) if elapsed else now_v
        pct = round(now_v / last_v * 100) if last_v else (100 if now_v else 0)
        out.append({
            'key': key, 'label': label, 'money': money,
            'now': round(now_v), 'last': round(last_v), 'projected': projected,
            'pct': pct, 'ring': min(pct, 100),
            'ahead': last_v and projected >= last_v,
            'now_text': _inr(now_v) if money else str(round(now_v)),
            'last_text': _inr(last_v) if money else str(round(last_v)),
            'projected_text': _inr(projected) if money else str(projected),
        })
    return {'items': out, 'month': today.strftime('%B'), 'last_month': last_start.strftime('%B'),
            'day': elapsed, 'days': days_in_month}


def resolve(notes):
    """Turns each note's URL name into a real link."""
    from django.urls import NoReverseMatch, reverse
    for n in list(notes.values()) + notes.get('top', []):
        if isinstance(n, dict) and n.get('url') and not str(n['url']).startswith('/'):
            try:
                n['url'] = reverse(n['url'])
            except NoReverseMatch:
                n['url'], n['action'] = None, None
    return notes


def parse_range(raw):
    key = raw if raw in RANGES else DEFAULT_RANGE
    return key, RANGES[key]
