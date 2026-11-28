"""In-memory stand-ins for Firestore and Firebase Auth used by the API tests."""

from __future__ import annotations

import itertools

_ids = itertools.count(1)


class FakeSnap:
    def __init__(self, ref, data):
        self.reference = ref
        self.id = ref.id
        self._data = data

    @property
    def exists(self):
        return self._data is not None

    def to_dict(self):
        return dict(self._data) if self._data is not None else None


class FakeDocRef:
    def __init__(self, db, path):
        self._db = db
        self.path = path
        self.id = path.rsplit('/', 1)[-1]

    def get(self):
        data = self._db.docs.get(self.path)
        return FakeSnap(self, data)

    def _resolve(self, data, current):
        """Apply Firestore sentinels (Increment, SERVER_TIMESTAMP) like the server."""
        from datetime import datetime, timezone

        from google.cloud.firestore_v1 import transforms

        out = {}
        for key, value in data.items():
            if isinstance(value, transforms.Increment):
                out[key] = (current.get(key) or 0) + value.value
            elif value is transforms.SERVER_TIMESTAMP:
                out[key] = datetime.now(timezone.utc)
            else:
                out[key] = value
        return out

    def set(self, data, merge=False):
        if self._db.fail_writes:
            raise RuntimeError('write failed')
        current = self._db.docs.get(self.path, {})
        resolved = self._resolve(data, current if merge else {})
        if merge and self.path in self._db.docs:
            self._db.docs[self.path].update(resolved)
        else:
            self._db.docs[self.path] = resolved

    def update(self, data):
        if self.path not in self._db.docs:
            raise KeyError(self.path)
        self._db.docs[self.path].update(self._resolve(data, self._db.docs[self.path]))

    def delete(self):
        self._db.docs.pop(self.path, None)

    def collection(self, name):
        return FakeQuery(self._db, f'{self.path}/{name}')


class FakeQuery:
    def __init__(self, db, collection_path, filters=(), limit=None):
        self._db = db
        self._path = collection_path
        self._filters = filters
        self._limit = limit

    def document(self, doc_id=None):
        return FakeDocRef(self._db, f'{self._path}/{doc_id or f"auto{next(_ids)}"}')

    def where(self, field, op, value):
        assert op == '==', op
        return FakeQuery(self._db, self._path, self._filters + ((field, value),), self._limit)

    def limit(self, n):
        return FakeQuery(self._db, self._path, self._filters, n)

    def order_by(self, field, direction=None):
        return self  # tests don't depend on order

    def stream(self):
        prefix = self._path + '/'
        out = []
        for path, data in self._db.docs.items():
            if not path.startswith(prefix) or '/' in path[len(prefix):]:
                continue
            if all(data.get(f) == v for f, v in self._filters):
                out.append(FakeSnap(FakeDocRef(self._db, path), data))
        return out[: self._limit] if self._limit else out


class FakeDB:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.fail_writes = False

    def collection(self, name):
        return FakeQuery(self, name)

    def put(self, path, data):
        self.docs[path] = dict(data)


class UserNotFoundError(Exception):
    pass


class FakeUser:
    def __init__(self, uid, phone_number=None):
        self.uid = uid
        self.phone_number = phone_number


class FakeAuth:
    """firebase_admin.auth subset used by the OTP login."""

    UserNotFoundError = UserNotFoundError

    def __init__(self):
        self.users: dict[str, FakeUser] = {}
        self.created: list[str] = []

    def get_user_by_phone_number(self, phone):
        for user in self.users.values():
            if user.phone_number == phone:
                return user
        raise UserNotFoundError(phone)

    def get_user(self, uid):
        if uid not in self.users:
            raise UserNotFoundError(uid)
        return self.users[uid]

    def create_user(self, uid=None, phone_number=None):
        uid = uid or f'new{next(_ids)}'
        self.users[uid] = FakeUser(uid, phone_number)
        self.created.append(uid)
        return self.users[uid]

    def update_user(self, uid, phone_number=None):
        self.users[uid].phone_number = phone_number

    def create_custom_token(self, uid):
        return f'token-for-{uid}'.encode()
