"""CivicSense data in PostgreSQL — a read copy.

Writes still happen in Firestore: the app's callables in
functions/civic_sense.js, the daily evidence cleanup, and the admin panel
(admin_app/civic_admin.py). civic.sync copies them here every 10 minutes and
at once after each admin write. Writes move here at the app switch, with the
other Phase 2/3 domains.

The privacy split is kept as separate tables, never merged:
    civic_reports          -> CivicReport         reporter-visible, no owner data
    civic_reports_private  -> CivicReportPrivate  admin-only owner match, flags
    civic_owner_alerts     -> CivicOwnerAlert     owner-visible, no reporter data
Also: civic_report_actions, civic_admin_logs, civic_awareness, civic_stats,
civic_points (+ /ledger), civic_leaderboard, civic_rate_limits,
civic_vehicle_push. Evidence photos stay in Firebase Storage (the Phase 1
mirror backs them up); reports keep their storage paths.

`document` keeps the full Firestore document (types tagged by api.mirror.encode).
"""

from django.db import models


class Copied(models.Model):
    id = models.CharField(max_length=300, primary_key=True)
    document = models.JSONField(default=dict)
    synced_at = models.DateTimeField(null=True)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        abstract = True


class CivicReport(Copied):
    reporter_uid = models.CharField(max_length=128, blank=True, default='', db_index=True)
    status = models.CharField(max_length=20, blank=True, default='', db_index=True)
    category = models.CharField(max_length=32, blank=True, default='')
    created_at = models.DateTimeField(null=True, db_index=True)

    class Meta:
        db_table = 'civic_report'


class CivicReportPrivate(Copied):
    owner_uid = models.CharField(max_length=128, blank=True, default='', db_index=True)
    match_status = models.CharField(max_length=32, blank=True, default='')
    created_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'civic_report_private'


class CivicOwnerAlert(Copied):
    owner_uid = models.CharField(max_length=128, blank=True, default='', db_index=True)
    owner_status = models.CharField(max_length=20, blank=True, default='')
    created_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'civic_owner_alert'


class CivicReportAction(Copied):
    report_doc_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'civic_report_action'


class CivicAdminLog(Copied):
    report_doc_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'civic_admin_log'


class CivicCampaign(Copied):
    """civic_awareness/{id}."""

    is_active = models.BooleanField(default=True)
    publish_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'civic_campaign'


class CivicStat(Copied):
    class Meta:
        db_table = 'civic_stat'


class CivicPoints(Copied):
    """civic_points/{uid}."""

    total = models.IntegerField(default=0, db_index=True)

    class Meta:
        db_table = 'civic_points'


class CivicPointsLedgerEntry(Copied):
    """civic_points/{uid}/ledger/{id}; id is "{uid}/{ledger doc id}"."""

    uid = models.CharField(max_length=128, db_index=True)
    reason = models.CharField(max_length=40, blank=True, default='')
    points = models.IntegerField(default=0)
    at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'civic_points_ledger_entry'


class CivicLeaderboardEntry(Copied):
    month_key = models.CharField(max_length=8, blank=True, default='', db_index=True)
    month_points = models.IntegerField(default=0)

    class Meta:
        db_table = 'civic_leaderboard_entry'


class CivicRateLimit(Copied):
    class Meta:
        db_table = 'civic_rate_limit'


class CivicVehiclePush(Copied):
    class Meta:
        db_table = 'civic_vehicle_push'


class CivicImport(models.Model):
    """One row once a full import has finished; admin lists read PostgreSQL after that."""

    id = models.CharField(max_length=16, primary_key=True, default='full')
    finished_at = models.DateTimeField()

    class Meta:
        db_table = 'civic_import'
