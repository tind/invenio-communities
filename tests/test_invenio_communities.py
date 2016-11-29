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
from datetime import datetime, timedelta

import pytest
from flask import Flask
from flask_cli import FlaskCLI
from invenio_db import db as db_
from invenio_oaiserver.models import OAISet
from invenio_records.api import Record
from flask_security import url_for_security
from invenio_communities import InvenioCommunities
from invenio_communities.errors import CommunitiesError, \
    InclusionRequestExistsError, InclusionRequestMissingError, \
    InclusionRequestObsoleteError
from invenio_communities.models import Community, FeaturedCommunity, \
    InclusionRequest


from tind.tests.utils import get_community_by_id, get_record_by_pid, get_user_by_email

try:
    from werkzeug.urls import url_parse
except ImportError:
    from urlparse import urlsplit as url_parse


def get_json(res, code=None):
    """Transform a JSON response into a dictionary."""
    if code:
        assert res.status_code == code
    return json.loads(res.get_data(as_text=True))


def assert_community_serialization(community, **kwargs):
    """Check the values of a community."""
    for key in kwargs.keys():
        assert community[key] == kwargs[key]


def test_version():
    """Test version import."""
    from invenio_communities import __version__
    assert __version__


def test_init():
    """Test extension initialization."""
    app = Flask('testapp')
    FlaskCLI(app)
    ext = InvenioCommunities(app)
    assert 'invenio-communities' in app.extensions

    app = Flask('testapp')
    FlaskCLI(app)
    ext = InvenioCommunities()
    assert 'invenio-communities' not in app.extensions
    ext.init_app(app)
    assert 'invenio-communities' in app.extensions


def test_model_init(app, db, communities, records):
    """Test basic model initialization and actions."""
    comm1 = get_community_by_id('comm1')
    comm2 = get_community_by_id('comm2')
    comm3 = get_community_by_id('oth3')
    communities_key = app.config["COMMUNITIES_RECORD_KEY"]

    # Create a record and accept it into the community by creating an
    # InclusionRequest and then calling the accept action
    pid, rec1 = get_record_by_pid('recid', 1000003)
    InclusionRequest.create(community=comm1, record=rec1)
    assert InclusionRequest.query.count() == 1
    comm1.accept_record(rec1)
    assert 'comm1' in rec1[communities_key]
    assert InclusionRequest.query.count() == 0

    # Likewise, reject a record from the community
    pid, rec2 = get_record_by_pid('recid', 1000004)
    InclusionRequest.create(community=comm1, record=rec2)
    assert InclusionRequest.query.count() == 1
    comm1.reject_record(rec2)
    assert communities_key not in rec2  # dict key should not be created
    assert InclusionRequest.query.count() == 0

    # Add record to another community
    InclusionRequest.create(community=comm2, record=rec1)
    comm2.accept_record(rec1)
    assert communities_key in rec1
    assert len(rec1[communities_key]) == 2
    assert comm1.id in rec1[communities_key]
    assert comm2.id in rec1[communities_key]

    # Accept/reject a record to/from a community without inclusion request
    pid, rec3 = get_record_by_pid('recid', 1000005)
    pytest.raises(InclusionRequestMissingError, comm1.accept_record, rec3)
    pytest.raises(InclusionRequestMissingError, comm1.reject_record, rec3)

    # Create two inclusion requests
    InclusionRequest.create(community=comm3, record=rec1)
    db_.session.commit()
    db_.session.flush()
    pytest.raises(InclusionRequestExistsError, InclusionRequest.create,
                  community=comm3, record=rec1)

    # Try to accept a record to a community twice (should raise)
    # (comm1 is already in rec1)
    pytest.raises(InclusionRequestObsoleteError, InclusionRequest.create,
                  community=comm1, record=rec1)


def test_email_notification(app, db, communities, users, records):
    """Test mail notification sending for community request."""
    # Mock the send method of the Flask-Mail extension
    with app.extensions['mail'].record_messages() as outbox:
        test = get_user_by_email('test@tind.io')
        comm1 = get_community_by_id('comm1')
        # Create a record and accept it into the community by creating an
        # InclusionRequest and then calling the accept action
        pid, rec1 = get_record_by_pid('recid', 1000006)
        InclusionRequest.create(community=comm1, record=rec1, user=test)
        # assert len(outbox) == 1


def test_model_featured_community(app, db, communities):
    """Test the featured community model and actions."""
    comm1 = get_community_by_id('comm1')
    comm2 = get_community_by_id('comm2')
    t1 = datetime.now()

    # Create two community featurings starting at different times
    fc1 = FeaturedCommunity(id_community=comm1.id,
                            start_date=t1 + timedelta(days=1))
    fc2 = FeaturedCommunity(id_community=comm2.id,
                            start_date=t1 + timedelta(days=3))
    db_.session.add(fc1)
    db_.session.add(fc2)
    # Check the featured community at three different points in time
    assert FeaturedCommunity.get_featured_or_none(start_date=t1) is None
    assert FeaturedCommunity.get_featured_or_none(
        start_date=t1 + timedelta(days=2)) is comm1
    assert FeaturedCommunity.get_featured_or_none(
        start_date=t1 + timedelta(days=4)) is comm2


def test_oaipmh_sets(app, db, communities):
    """Test the OAI-PMH Sets creation."""
    comm1 = get_community_by_id('comm1')

    assert OAISet.query.count() == len(communities)
    oai_set1 = OAISet.query.first()
    assert oai_set1.spec == 'user-comm1'
    assert oai_set1.name == 'Title1'
    assert oai_set1.description == 'Description1'

    # Delete the community and make sure the set is also deleted
    db_.session.delete(comm1)
    db_.session.commit()
    assert Community.query.count() == len(communities) - 1
    assert OAISet.query.count() == len(communities) - 1


def test_communities_rest_all_communities(app, db, communities):
    """Test the OAI-PMH Sets creation."""
    with app.test_client() as client:
        response = client.get('/api/communities/')
        response_data = get_json(response)
        assert response_data['hits']['total'] == len(communities)
        assert len(response_data['hits']['hits']) == len(communities)

        assert response_data['hits']['hits'][0]['id'] == 'comm1'


def test_community_delete(app, db, communities):
    """Test deletion of communities."""
    comm1 = get_community_by_id('comm1')
    comm2 = get_community_by_id('comm2')

    comm1.delete()
    assert comm1.is_deleted is True
    comm1.undelete()
    assert comm1.is_deleted is False

    # Try to undelete a community that was not marked for deletion
    pytest.raises(CommunitiesError, comm1.undelete)

    # Try to delete community twice
    comm2.delete()
    pytest.raises(CommunitiesError, comm2.delete)


def test_communities_rest_all_communities_query_and_sort(app, db, communities):
    """Test the OAI-PMH Sets creation."""
    with app.test_client() as client:
        response = client.get('/api/communities/?q=comm&sort=title')
        response_data = get_json(response)

        assert response_data['hits']['total'] == 2
        assert response_data['hits']['hits'][0]['id'] == 'comm2'
        assert response_data['hits']['hits'][1]['id'] == 'comm1'


def test_communities_rest_pagination(app, db, communities, users):
    """Test the OAI-PMH Sets creation."""
    def parse_path(app, path):
        """Split the path in base and real relative url.

        Needed because in Flask 0.10.1 the client doesn't take into account the
        query string in an external URL.
        """
        http_host = app.config.get('SERVER_NAME')
        app_root = app.config.get('APPLICATION_ROOT')
        url = url_parse(path)
        base_url = 'http://{0}/'.format(url.netloc or http_host or 'localhost')
        if app_root:
            base_url += app_root.lstrip('/')
        if url.netloc:
            path = url.path
            if url.query:
                path += '?' + url.query
        return dict(path=path, base_url=base_url)

    def assert_header_links(response, ref, page, size):
        """Check if there is a pagination in one of the headers."""
        assert any(all(item in h[1] for item in [
            'ref="{0}"'.format(ref),
            'page={0}'.format(page),
            'size={0}'.format(size)]) for h in response.headers)

    user = get_user_by_email('admin@tind.io')
    login_url = url_for_security('login')
    with app.test_client() as client:
        res = client.post(login_url,
                          data={'email': user.email,
                                'password': user.password},
                          follow_redirects=True)
        response = client.get('/api/communities/?size=1')
        assert_header_links(response, 'self', 1, 1)
        assert_header_links(response, 'next', 2, 1)

        data = get_json(response)
        assert 'self' in data['links']
        assert len(data['hits']['hits']) == 1

        # Assert that self gives back the same result

        response = client.get(**parse_path(app, data['links']['self']))
        assert data == get_json(response)
        assert 'prev' not in data['links']
        assert 'next' in data['links']

        # Second page
        response = client.get(**parse_path(app, data['links']['next']))
        assert_header_links(response, 'next', 3, 1)
        assert_header_links(response, 'self', 2, 1)
        assert_header_links(response, 'prev', 1, 1)

        data = get_json(response)
        assert len(data['hits']['hits']) == 1
        assert 'prev' in data['links']
        assert 'next' in data['links']

        # Third page
        response = client.get(**parse_path(app, data['links']['next']))
        assert_header_links(response, 'self', 3, 1)
        assert_header_links(response, 'prev', 2, 1)

        total = len(communities)
        size = str((total+1)//2)
        page = str(2)
        response = client.get(
            '/api/communities/?size={0}&page={1}'.format(size, page))
        data = get_json(response)
        assert 'prev' in data['links']
        assert 'next' not in data['links']


def test_communities_rest_get_details(app, db, communities):
    """Test the OAI-PMH Sets creation."""
    user = get_user_by_email('admin@tind.io')
    login_url = url_for_security('login')
    with app.test_client() as client:
        res = client.post(login_url,
                          data={'email': user.email,
                                'password': user.password},
                          follow_redirects=True)
        response = client.get('/api/communities/comm1')
        assert_community_serialization(
            get_json(response),
            description='Description1',
            title='Title1',
            id='comm1',
            page='',
            curation_policy='',
            last_record_accepted='2000-01-01T00:00:00+00:00',
            links={
                'self': 'http://127.0.0.1/api/communities/comm1',
                'html': 'http://127.0.0.1/communities/comm1/',
            },
        )


def test_communities_rest_etag(app, communities):
    """Test the OAI-PMH Sets creation."""
    user = get_user_by_email('admin@tind.io')
    login_url = url_for_security('login')
    with app.test_client() as client:
        res = client.post(login_url,
                          data={'email': user.email,
                                'password': user.password},
                          follow_redirects=True)
        # The first response should return the data with result code 200
        response = client.get('/api/communities/comm1')
        assert response.status_code == 200
        assert response.get_data(as_text=True) != ''

        # The second response is empty and the result code is 304
        response = client.get('/api/communities/comm1', headers=(
            ('If-None-Match', response.headers.get('ETag')),))
        assert response.status_code == 304
        assert response.get_data(as_text=True) == ''
