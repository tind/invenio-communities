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

from invenio_communities.models import InclusionRequest
from tind.tests.utils import get_community_by_id, get_record_by_pid


def test_community_delete_task(app, db, communities, records):
    """Test the community deletion task."""
    comm1 = get_community_by_id('comm1')
    pid, rec1 = get_record_by_pid('recid', 1000003)
    communities_key = app.config["COMMUNITIES_RECORD_KEY"]
    InclusionRequest.create(community=comm1, record=rec1, notify=False)

    assert InclusionRequest.get(comm1.id, rec1.id)

    comm1.accept_record(rec1)
    assert 'comm1' in rec1[communities_key]

    comm1.delete()
    assert comm1.is_deleted
