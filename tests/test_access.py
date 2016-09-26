# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2016 CERN.
#
# Invenio is free software; you can redistribute it
# and/or modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# Invenio is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Invenio; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place, Suite 330, Boston,
# MA 02111-1307, USA.
#
# In applying this license, CERN does not
# waive the privileges and immunities granted to it by virtue of its status
# as an Intergovernmental Organization or submit itself to any jurisdiction.


"""Module tests."""

from __future__ import absolute_import, print_function

import json
from uuid import uuid4

from invenio_accounts.models import User
from invenio_access.models import ActionUsers
from invenio_pidstore.providers.recordid import RecordIdProvider
from invenio_records.api import Record

from invenio_communities.models import Community


def create_users(db):
    """Create 4 users for the tests."""
    admin = User(active=True,
                 email='admin@inveniosoftware.org',
                 password="duck")
    owner = User(active=True,
                 email='owner@inveniosoftware.org',
                 password="face")
    reader = User(active=True,
                  email='reader@inveniosoftware.org',
                  password="is")
    suggester = User(active=True,
                     email='suggester@inveniosoftware.org',
                     password="really")
    curator = User(active=True,
                   email='curator@inveniosoftware.org',
                   password="so")
    none = User(active=True,
                email='none@inveniosoftware.org',
                password="bad")
    db.session.add_all([admin, owner, reader, suggester, curator, none])
    db.session.commit()
    return admin, owner, reader, suggester, curator, none


def add_action_to_users(db, users, **kwargs):
    """Adds the action to the user."""
    for user in users:
        db.session.add(ActionUsers(user=user, **kwargs))
    db.session.commit()


def create_record():
    """Creates a record and returns (id, pid)."""
    recid = uuid4()
    pid = RecordIdProvider.create(object_type='rec',
                                  object_uuid=recid).pid.pid_value
    data = {
        "pid_value": pid,
        "control_number": pid
    }
    record = Record.create(data, id_=recid)
    return recid, pid


def test_suggest(app, db):
    """Test for get_communities()"""
    admin, owner, reader, suggester, curator, none = create_users(db)
    c1 = Community.create(community_id="c1", user_id=owner.id)
    recid, pid = create_record()

    add_action_to_users(db, [admin], action="admin-access")
    add_action_to_users(db, [owner], action="communities-manage",
                        argument="c1")
    add_action_to_users(db, [owner, reader], action="communities-read",
                        argument="c1")
    add_action_to_users(db, [owner, suggester], action="communities-suggest",
                        argument="c1")
    add_action_to_users(db, [owner, curator], action="communities-curate",
                        argument="c1")

    def test_user(user, status):
        with app.test_client() as c:
            with c.session_transaction() as sess:
                sess['user_id'] = user.id
                sess['_fresh'] = True
            res = c.post("/communities/suggest/", **{
                "content_type": "application/json",
                "data": json.dumps({
                    "community": "c1",
                    "recpid": str(pid)
                })
            })
            assert json.loads(res.get_data(as_text=True))["status"] == status

    test_user(none, "DANGER")  # not allowed
    test_user(curator, "DANGER")  # not allowed
    test_user(reader, "DANGER")  # not allowed
    test_user(admin, "INFO")  # can suggest (and curate but not all at once)
    test_user(owner, "SUCCESS")  # can add
    test_user(suggester, "WARNING")  # the record already exists
