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
from flask_security import url_for_security
# from invenio_access.models import ActionUsers

from tind.tests.utils import get_record_by_pid, get_user_by_email


def test_suggest(app, db, users, records, communities):
    """Test for get_communities()"""
    admin = get_user_by_email('admin@tind.io')
    owner = get_user_by_email('owner@tind.io')
    reader = get_user_by_email('reader@tind.io')
    suggester = get_user_by_email('suggester@tind.io')
    curator = get_user_by_email('curator@tind.io')
    none = get_user_by_email('none@tind.io')

    pid, public = get_record_by_pid('recid', 1000001)

    def test_user(user, status):
        login_url = url_for_security('login')
        with app.test_client() as c:
            res = c.post(login_url,
                         data={'email': user.email,
                               'password': user.password},
                         follow_redirects=True)
            # with c.session_transaction() as sess:
            #     sess['user_id'] = user.id
            #     sess['_fresh'] = True
            res = c.post("/communities/suggest/", **{
                "content_type": "application/json",
                "data": json.dumps({
                    "community": "c1",
                    "recpid": str(pid.pid_value)
                })
            })
            print(json.loads(res.get_data(as_text=True))["message"])
            print(pid)
            print(user.email)
            assert json.loads(res.get_data(as_text=True))["status"] == status

    test_user(none, "DANGER")  # not allowed
    test_user(curator, "DANGER")  # not allowed
    test_user(reader, "DANGER")  # not allowed
    test_user(admin, "INFO")  # can suggest (and curate but not all at once)
    test_user(owner, "SUCCESS")  # can add
    test_user(suggester, "WARNING")  # the record already exists
