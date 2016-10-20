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

"""Invenio module that adds support for communities."""


import copy
import json
from collections import namedtuple
from functools import partial, wraps

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_babelex import gettext as _
from flask_login import current_user, login_required
from flask_principal import ActionNeed
from invenio_db import db
from invenio_indexer.api import RecordIndexer
from invenio_pidstore.resolver import Resolver
from invenio_records.api import Record

from invenio_access import DynamicPermission
from invenio_access.models import ActionUsers
from invenio_accounts.models import User

from invenio_communities.errors import (InclusionRequestExistsError,
                                        InclusionRequestObsoleteError)
from invenio_communities.forms import (CommunityForm,
                                       DeleteCommunityForm,
                                       EditCommunityForm,
                                       SearchForm)
from invenio_communities.models import (Community,
                                        FeaturedCommunity,
                                        InclusionRequest)
from invenio_communities.utils import (_get_permission,
                                       _get_permissions,
                                       _get_needs,
                                       Pagination,
                                       render_template_to_string)

from .api import CommunitiesFacets

blueprint = Blueprint(
    'invenio_communities',
    __name__,
    url_prefix='/communities',
    template_folder='../templates',
    static_folder='../static',
)


def pass_community(f):
    """Decorator to pass community."""
    @wraps(f)
    def inner(community_id, *args, **kwargs):
        c = Community.get(community_id)
        if c is None:
            abort(404)
        return f(c, *args, **kwargs)
    return inner


def permission_required(action):
    """Decorator to require permission."""
    def decorator(f):
        @wraps(f)
        def inner(community, *args, **kwargs):
            permission = _get_permission(action, community)
            if permission.can() \
                    or DynamicPermission(ActionNeed('admin-access')).can():
                return f(community, *args, **kwargs)
            abort(403)
        return inner
    return decorator


def permission_required_no_id(action):
    """Decorator to require permission."""
    def decorator(f):
        @wraps(f)
        def inner(*args, **kwargs):
            permission = _get_permission(action)
            if permission.can() \
                    or DynamicPermission(ActionNeed('admin-access')).can():
                return f(*args, **kwargs)
            abort(403)
        return inner
    return decorator


@blueprint.app_template_filter('format_item')
def format_item(item, template, name='item'):
    """Render a template to a string with the provided item in context."""
    ctx = {name: item}
    return render_template_to_string(template, **ctx)


@blueprint.app_template_filter('mycommunities_ctx')
def mycommunities_ctx():
    """Helper method for return ctx used by many views."""
    communities = Community.filter_communities("", "title").all()
    mycommunities = [c for c in communities
                     if _get_permission("communities-read", c).can() or
                     DynamicPermission(ActionNeed('admin-access')).can()]
    return {
        "mycommunities": mycommunities,
        "permission_admin": DynamicPermission(ActionNeed('admin-access')),
        "permission_cadmin": partial(_get_permission, "communities-admin"),
        "permission_curate": partial(_get_permission, "communities-curate"),
        "permission_manage": partial(_get_permission, "communities-manage"),
        "permission_read": partial(_get_permission, "communities-read"),
        "permission_suggest": partial(_get_permission, "communities-suggest")
    }


@blueprint.route('/', methods=['GET', ])
def index():
    """Index page with uploader and list of existing depositions."""
    ctx = mycommunities_ctx()

    p = request.args.get('p', type=str)
    so = request.args.get('so', type=str)
    page = request.args.get('page', type=int, default=1)

    so = so or current_app.config.get('COMMUNITIES_DEFAULT_SORTING_OPTION')

    communities = Community.filter_communities(p, so).all()
    communities = [c for c in communities
                   if _get_permission("communities-read", c).can() or
                   DynamicPermission(ActionNeed('admin-access')).can()]
    featured_community = FeaturedCommunity.get_featured_or_none()
    form = SearchForm(p=p)
    per_page = 10
    page = max(page, 1)
    p = Pagination(page, per_page, len(communities))

    facets = {}

    try:
        facets = CommunitiesFacets().get()['communities']['buckets']
    except KeyError:
        pass

    ctx.update({
        'r_from': max(p.per_page * (p.page - 1), 0),
        'r_to': min(p.per_page * p.page, p.total_count),
        'r_total': p.total_count,
        'pagination': p,
        'form': form,
        'title': _('Communities'),
        'communities': communities[per_page * (page - 1):per_page * page],
        'featured_community': featured_community,
        'facets': facets
    })

    return render_template(
        current_app.config['COMMUNITIES_INDEX_TEMPLATE'],
        **ctx
    )


@blueprint.route('/<string:community_id>/', methods=['GET'])
@pass_community
@permission_required('communities-read')
def detail(community):
    """Index page with uploader and list of existing depositions."""
    return generic_item(community,
                        current_app.config['COMMUNITIES_DETAIL_TEMPLATE'])


@blueprint.route('/<string:community_id>/search', methods=['GET'])
@pass_community
@permission_required('communities-read')
def search(community):
    """Index page with uploader and list of existing depositions."""
    return generic_item(
        community,
        current_app.config['COMMUNITIES_SEARCH_TEMPLATE'],
        detail=False)


@blueprint.route('/<string:community_id>/about/', methods=['GET'])
@pass_community
@permission_required('communities-read')
def about(community):
    """Index page with uploader and list of existing depositions."""
    return generic_item(community, "invenio_communities/about.html")


def generic_item(community, template, **extra_ctx):
    """Index page with uploader and list of existing depositions."""
    # Check existence of community
    ctx = mycommunities_ctx()

    community_facets = {}

    try:
        all_facets = CommunitiesFacets().get()['communities']['buckets']
        for facet in all_facets:
            if facet['key'] == community.id:
                community_facets = facet
    except KeyError:
        pass

    ctx.update({
        'is_owner': community.id_user == current_user.get_id(),
        'community': community,
        'detail': True,
        'facets': community_facets
    })
    ctx.update(extra_ctx)

    return render_template(template, **ctx)


@blueprint.route('/new/', methods=['GET', 'POST'])
@login_required
@permission_required_no_id('communities-admin')
def new():
    """Create a new community."""
    form = CommunityForm(request.values)

    ctx = mycommunities_ctx()
    ctx.update({
        'form': form,
        'is_new': True,
        'community': None,
    })

    if form.validate_on_submit():
        data = copy.deepcopy(form.data)

        community_id = data.pop('identifier')
        del data['logo']

        community = Community.create(
            community_id, current_user.get_id(), **data)

        file = request.files.get('logo', None)
        if file:
            if not community.save_logo(file.stream, file.filename):
                form.logo.errors.append(_(
                    'Cannot add this file as a logo. Supported formats: '
                    'PNG, JPG and SVG. Max file size: 1.5 MB.'))
                db.session.rollback()
                community = None

        if community:
            permissions = _get_permissions()
            for permission in permissions:
                db.session.add(ActionUsers(action=permission,
                               user=current_user,
                               argument=community_id))
            db.session.commit()
            flash("{} was successfully created.".format(
                    current_app.config["COMMUNITIES_NAME"].capitalize()),
                  category='success')
            return redirect(url_for('.edit', community_id=community.id))

    return render_template(
        "/invenio_communities/new.html",
        community_form=form,
        **ctx
    )


@blueprint.route('/<string:community_id>/edit/', methods=['GET', 'POST'])
@login_required
@pass_community
@permission_required('communities-manage')
def edit(community):
    """Create or edit a community."""
    form = EditCommunityForm(request.values, community)
    deleteform = DeleteCommunityForm()
    ctx = mycommunities_ctx()
    ctx.update({
        'form': form,
        'is_new': False,
        'community': community,
        'deleteform': deleteform,
    })

    if form.validate_on_submit():
        for field, val in form.data.items():
            setattr(community, field, val)

        file = request.files.get('logo', None)
        if file:
            if not community.save_logo(file.stream, file.filename):
                form.logo.errors.append(_(
                    'Cannot add this file as a logo. Supported formats: '
                    'PNG, JPG and SVG. Max file size: 1.5 MB.'))

        if not form.logo.errors:
            db.session.commit()
            flash("{} successfully edited.".format(
                        current_app.config["COMMUNITIES_NAME"].capitalize()),
                  category='success')
            return redirect(url_for('.edit', community_id=community.id))

    return render_template(
        "invenio_communities/new.html",
        **ctx
    )


@blueprint.route('/<string:community_id>/delete/', methods=['POST'])
@login_required
@pass_community
@permission_required('communities-admin')
def delete(community):
    """Delete a community."""
    deleteform = DeleteCommunityForm(request.values)
    ctx = mycommunities_ctx()
    ctx.update({
        'deleteform': deleteform,
        'is_new': False,
        'community': community,
    })

    if deleteform.validate_on_submit():
        community.delete()
        # we delete all the permissions associated
        permissions = _get_permissions(False, False)
        for p in permissions:
            ActionUsers.query.filter_by(action=p,
                                        argument=community.id).delete()
        db.session.commit()
        flash("{} was deleted.".format(
                        current_app.config["COMMUNITIES_NAME"].capitalize()),
              category='success')
        return redirect(url_for('.index'))
    else:
        flash("{} could not be deleted.".format(
                        current_app.config["COMMUNITIES_NAME"].capitalize()),
              category='warning')
        return redirect(url_for('.edit', community_id=community.id))


@blueprint.route('/<string:community_id>/make-public/', methods=['POST'])
@login_required
@pass_community
@permission_required('communities-manage')
def make_public(community):
    """Makes a community public."""
    ActionUsers.query.filter_by(action="communities-read",
                                argument=community.id).delete()
    db.session.commit()
    flash("{} is now public.".format(
                        current_app.config["COMMUNITIES_NAME"].capitalize()),
          category='success')
    return redirect(url_for('.edit', community_id=community.id))


@blueprint.route('/<string:community_id>/curate/', methods=['GET', 'POST'])
@login_required
@pass_community
@permission_required('communities-curate')
def curate(community):
    """Index page with uploader and list of existing depositions.

    :param community_id: ID of the community to curate.
    """
    if request.method == 'POST':
        action = request.json.get('action')
        recid = request.json.get('recid')

        # 'recid' is mandatory
        if not recid:
            return jsonify({'status': 'danger', 'msg': _('Unknown record')})
        if action not in ['accept', 'reject', 'remove']:
            return jsonify({'status': 'danger', 'msg': _('Unknown action')})

        # Resolve recid to a Record
        resolver = Resolver(
            pid_type='recid', object_type='rec', getter=Record.get_record)
        pid, record = resolver.resolve(recid)

        action_name = ""
        status = "success"
        # Perform actions
        try:
            if action == "accept":
                community.accept_record(record)
                action_name = "added to"
            elif action == "reject":
                community.reject_record(record)
                action_name = "rejected from"
                status = "info"
            elif action == "remove":
                community.remove_record(record)
                action_name = "removed from"
                status = "info"
        except CommunitiesError:
            return jsonify({
                'status': 'danger',
                'msg': _('record not in the curation list,'
                         ' please refresh the page.')})

        record.commit()
        db.session.commit()
        RecordIndexer().index_by_id(record.id)
        title = ""
        if "title_statement" in record and \
                "title" in record["title_statement"]:
            title = record["title_statement"]["title"]
        message = _(
            'The record '
            '"{}" has been {} the community.').format(title, action_name)
        return jsonify({'status': status, 'msg': message})

    ctx = {'community': community}
    return render_template(
        current_app.config['COMMUNITIES_CURATE_TEMPLATE'],
        **ctx
    )


@blueprint.route('/suggest/', methods=['GET', 'POST'])
@login_required
# @permission_required('communities-suggest')  # tested later from the POST
def suggest():
    """Index page with uploader and list of existing depositions.

    :param community_id: ID of the community to curate.
    """
    community = None
    record = None
    values = request.get_json() or request.values

    if "community" not in values:
        return json.dumps({
            "status": "DANGER",
            "message": "Error, no {} given".format(
                current_app.config["COMMUNITIES_NAME"])})

    community_id = values["community"]
    community = Community.get(community_id)
    if not community:
        return json.dumps({
            "status": "DANGER",
            "message": "Error, unknown {} {}".format(
                current_app.config["COMMUNITIES_NAME"], community_id)})

    if not _get_permission("communities-suggest", community).can() \
            and not DynamicPermission(ActionNeed('admin-access')).can():
        return json.dumps({
            "status": "DANGER",
            "message": "Error, you don't have suggest permissions on the " +
                       "{} {}".format(current_app.config["COMMUNITIES_NAME"],
                                      community_id)})

    if "recpid" not in values:
        return json.dumps({
            "status": "DANGER",
            "message": "Error, no record given"})

    recid = values["recpid"]
    resolver = Resolver(
            pid_type='recid', object_type='rec', getter=Record.get_record)
    try:
        pid, record = resolver.resolve(recid)
    except Exception:
        return json.dumps({
            "status": "DANGER",
            "message": "Error, unknown record {}".format(recid)})

    # if the user has the curate permission on this community,
    # we automatically add the record
    if _get_permission("communities-curate", community).can():
        try:
            community.add_record(record)
        except:  # the record is already in the community
            return json.dumps({
                "status": "WARNING",
                "message": "The record already exists in the {} {}.".format(
                    current_app.config["COMMUNITIES_NAME"],
                    community.title)})
        else:
            record.commit()
            db.session.commit()
            RecordIndexer().index_by_id(record.id)
            return json.dumps({
                "status": "SUCCESS",
                "message": "The record has been added to the {} {}.".format(
                    current_app.config["COMMUNITIES_NAME"],
                    community.title)})
    # otherwise we only suggest it and it will appear in the curate list
    else:
        try:
            InclusionRequest.create(community=community,
                                    record=record,
                                    user=current_user)
        # the record is already in the community
        except InclusionRequestObsoleteError:
            return json.dumps({
                "status": "WARNING",
                "message": "The record already exists in the {} {}.".format(
                    current_app.config["COMMUNITIES_NAME"],
                    community.title)})
        except InclusionRequestExistsError:
            return json.dumps({
                "status": "WARNING",
                "message": "The record has already been suggested "
                           "to the {} {}.".format(
                               current_app.config["COMMUNITIES_NAME"],
                               community.title)})
            flash(u"The record has been suggested "
                  u"to the {} {}.".format(
                                current_app.config["COMMUNITIES_NAME"],
                                community.title))
    db.session.commit()
    RecordIndexer().index_by_id(record.id)
    return json.dumps({
            "status": "INFO",
            "message": "The record has been suggested to the {} {}.".format(
                current_app.config["COMMUNITIES_NAME"], community.title)})


@blueprint.route('/<string:community_id>/team/')
@login_required
@pass_community
@permission_required('communities-manage')
def team_management(community):
    """Team management for communities.

    :param community_id: ID of the community to manage.
    """
    Action = namedtuple("Action", ["title", "name", "existing"])

    actions = []
    permissions = _get_permissions()
    for action in permissions:
        # 12 = len("communities-")
        a = Action(action[12:].replace("-", " ").capitalize(),
                   action,
                   ActionUsers.query_by_action(
                       _get_needs(action, community.id)).all())
        actions.append(a)
    ctx = mycommunities_ctx()
    ctx.update({
        "community": community,
        "actions": actions
    })
    return render_template(
        current_app.config['COMMUNITIES_TEAM_TEMPLATE'],
        **ctx
    )


@blueprint.route('/<string:community_id>/team/delete-user/', methods=['POST'])
@login_required
@pass_community
@permission_required('communities-manage')
def team_delete_user(community):
    """page to delete a user. redirect to team_management

    :param community_id: ID of the community.
    """
    if request.method != 'POST':
        abort(404)
    if "action_id" not in request.form:
        flash(u"Error: action not valid.", "danger")
    else:
        action = ActionUsers.query.get(request.form["action_id"])
        if action.argument != community.id:
            flash(u"You don't have the permission for this action.", "danger")
        else:
            db.session.delete(action)
            db.session.commit()
            flash(u"The permission has been succesfully deleted.")
    return redirect(url_for(".team_management", community_id=community.id))


@blueprint.route('/<string:community_id>/team/add/', methods=['GET', 'POST'])
@login_required
@pass_community
@permission_required('communities-manage')
def team_add(community):
    """Add a member to a team community

    :param community_id: ID of the community to manage.
    """
    actions = _get_permissions()
    default_action = ""
    if "default_action" in request.values:
        default_action = request.values["default_action"]
    ctx = mycommunities_ctx()
    ctx.update({
        "community": community,
        "users": User.query.all(),
        "actions": actions,
        "default_action": default_action
    })
    return render_template(
        current_app.config['COMMUNITIES_TEAM_ADD_TEMPLATE'],
        **ctx
    )


@blueprint.route('/<string:community_id>/team/add-user/', methods=['POST'])
@login_required
@pass_community
@permission_required('communities-manage')
def team_add_user(community):
    """page to add a user. redirect to team_management

    :param community_id: ID of the community.
    """
    if request.method != 'POST':
        abort(404)
    if "action" not in request.form or "user" not in request.form:
        flash(u"Error: action not valid.", "danger")
    else:
        user = User.query.get(request.form["user"])
        db.session.add(ActionUsers(action=request.form["action"],
                                   user=user,
                                   argument=community.id))
        db.session.commit()
        flash(u"The permission has been succesfully added.")
    return redirect(url_for(".team_management", community_id=community.id))
