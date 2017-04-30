"""
Rhomboid. Faithfully delivering course material since 2016.

Mike Gelbart, 2016.
"""

import github3 # docs at http://github3.readthedocs.io/en/develop/api.html
from github3 import GitHubEnterprise
from github3.models import __timeformat__ as gh3_time_fmt

import pandas as pd
import numpy as np
import os
import os.path
import sys
import operator
import functools
import base64
try: import simplejson as json
except ImportError: import json
import argparse
import random
import urllib.parse
from datetime import datetime, timedelta
from dateutil import tz
from collections import OrderedDict, defaultdict
import math
from io import StringIO

# import snipgen
import grades
import rubrics
from utils import *

import pdb


class Goatcabin(object):

    def __init__(self, config, dry_run=False):
        # get token
        if "GITHUB_PAT" in os.environ:
            token = os.environ["GITHUB_PAT"]
            print("Successfully read GitHub PAT from environment variable.")
        else:
            token = input("Please enter your GitHub API token: ")

        # log in to GHE
        self.ghe = GitHubEnterprise(config["url"], token=token)

        # get MDS org
        self.org = self.ghe.organization(config["org"])

        self.config = config

        # remove whitespace from course name
        # self.config["name"] = ''.join(self.config["name"].split())

        self.teams = {team.name : team for team in self.org.teams()}
        self.repos = {repo.name : repo for repo in self.org.repositories()}
        self.members = {member.login : member for member in self.org.members()}
        # above: if you call memeber.refresh() it is slow, but has more info...!!!!

        user = self.ghe.me()
        self.userstr = user_to_str(user)
        self.usercwl = user.login

        # load course config if possible
        if config["staff-repo"] in self.repos:
            course_repo = self.repos[config["staff-repo"]]
            course_config_string = self._file_contents(course_repo, COURSE_CONFIG_FILENAME)
            if course_config_string:
                self.course_config = json.loads(course_config_string, object_pairs_hook=OrderedDict)

        self.staff_team   = self.teams[config["staff-team"]]
        # self.students_team = self.teams[config["students-team"]]
        self.staff_repo    = self.repos.get(config["staff-repo"], None)
        self.students_repo = self.repos.get(config["students-repo"], None)
        self.grades_repo   = self.repos.get(config["grades-repo"], None)

        self.dry_run = dry_run

    @property
    def students_teams(self):
        if isinstance(self.config["students-team"], str):
            yield self.teams[self.config["students-team"]]
        elif isinstance(self.config["students-team"], list):
            for students_team_name in self.config["students-team"]:
                yield self.teams[students_team_name]
        else:
            raise Exception("Unknown data type of students-team in config file.")

    @property
    def students(self):
        for student_team in self.students_teams:
            for member in student_team.members():
                yield member

    """ Add invitees to team and possibly also the organization (if not already a member) """
    def _invite_to_team(self, team, invitees):
        if not team:
            print("Team %s does not exist -- you need to create the Team first." % team.name)
            return

        for invitee in invitees:
            if team.is_member(invitee):
                print("%-12s is already a member of Team %s." % (invitee, team.name))
                continue

            if self.dry_run:
                print("DRY RUN: Now I would add %s to Team %s" % (invitee, team.name))
                return
            is_org_member = self.org.is_member(invitee)
            success = team.invite(invitee)
            if success and is_org_member:
                print("%-12s: invited to team %s." % (invitee, team.name))
            elif success and not is_org_member:
                print("%-12s: invited to %s organization and team %s." % (invitee, self.org.login, team.name))
            else:
                print("Failed to add %-12s to team %s" % (invitee, team.name))


    def _file_exists(self, repo, filename):
        repo_contents_info = self._get_all_files_in_repo_at_path(repo, get_contents=False)
        return filename in repo_contents_info


    def _create_branch(self, repo, new_branch_name, source_branch_name="master"):
        if self.dry_run:
            print("DRY RUN: Now I would create a branch %s in repo %s." % (new_branch_name, repo.name))
            return

        existing_branch = repo.branch(new_branch_name)
        if existing_branch:
            print("Branch %s already exists in %s" % (new_branch_name, repo.name))
            return existing_branch
        # get revision sha
        sha = repo.branch(source_branch_name).latest_sha().decode("UTF-8")

        # create branch
        new_ref = repo.create_ref(ref="refs/heads/%s"%new_branch_name, sha=sha)
        if new_ref:
            print("Sucessfully created branch %s in repo %s" % (new_branch_name, repo.name))
            return repo.branch(new_branch_name)
        else:
            print("Failed to create branch %s in repo %s" % (new_branch_name, repo.name))
            return None

    # for now, head should be the name of a branch e.g. instructor_updates.
    # and base should also be the name of a branch, e.g. master
    def _create_pull_request(self, repo, title, message, base, head):
        if self.dry_run:
            print('DRY RUN: Now I would update the PR entitled "%s" in repo %s' % (title, repo.name))
            return

        if not repo.branch(head):
            print("Branch %s does not exist, therefore I can't create a PR from it. Aborting." % head)

        # if the pull request already exists, update it
        for existing_PR in repo.pull_requests(state="open"):
            if existing_PR.as_dict()["title"] == title: # "hopefully you can't have multiple PR's the the same title... but you probably can :("
                # TODO: need a better way of checking equality. Perhaps the base and head. yes i think so
                print('FYI: an open pull request with title "%s" in repo %s already exists.' % (title, repo.name))

                if existing_PR.as_dict()["head"]["sha"] == repo.branch(head).latest_sha().decode("UTF-8"):
                    print("The latest sha of this PR matches the latest sha of the branch %s, so this PR is vacuous (I think). Skipping." % head)
                    return

                PR = existing_PR.update(title=title, body=message) # or could call with no arguments, that would work too
                if PR:
                    print("Successfully updated Pull Request in %s from branch %s to %s" % (repo.name, head, "master"))
                else:
                    print("Failed to update Pull Request in %s from branch %s to %s" % (repo.name, head, "master"))
                return

        # Need to check if the two branches are actually different. Because if not then `create_pull` will throw an error.
        # if repo.branch(UPDATES_BRANCH_NAME).latest_sha() == repo.branch("master").latest_sha():
            # print("You are trying to create a PR from branch %s to master in %s, but these two branches are already in sync. Skipping." % (UPDATES_BRANCH_NAME, repo.name))
            # return

        # what might be even better than the above is to see if the sha of the head of the PR is anywhere in the history of master
        # because if so it means the person probably already merged the PR and then made further edits. and in that case we don't want to do it.
        # if repo.branch(UPDATES_BRANCH_NAME).latest_sha() == repo.branch("master").latest_sha():
            # print("You are trying to create a PR from branch %s to master in %s, but these two branches are already in sync. Skipping." % (UPDATES_BRANCH_NAME, repo.name))
            # return
        # another approach is to explitly check all merged PRs.
        # if repo.branch(UPDATES_BRANCH_NAME).latest_sha().decode("UTF-8") in (rc.sha for rc in repo.commits(sha="master")): # this works too
        if next(repo.commits(sha=head, number=1)) in repo.commits(sha="master"): # sha="master" is optional as that's already the default
            # above: compare the actual RepoCommit objects themselves, instead of the sha strings. High five! Ok no one cares.
            print("You are trying to create a PR from branch %s to master in %s, but the latest commit of %s (%s) already exists in master's history. Skipping." % (head, repo.name, head, repo.branch(UPDATES_BRANCH_NAME).latest_sha()))
            return

        PR = repo.create_pull(title=title, base="master", head=head, body=message)
        if PR:
            print("Successfully created Pull Request in %s from branch %s to %s" % (repo.name, head, "master"))
        else:
            print("Failed to create Pull Request in %s from branch %s to %s" % (repo.name, head, "master"))


    def _create_file(self, repo, filename, file_contents, overwrite=False, branch="master"):
        if repo is None:
            print("Cannot create file %s because repo is None" % filename)
            return

        if self.dry_run:
            print("DRY RUN: Now I would create/update a file named %s in repo %s with contents:\n%s" % (filename, repo.name, file_contents))
            return

        # check if this is a new branch
        # branch_obj = repo.branch(branch) # get the branch
        # if branch != "master" and not branch_obj:
        #     self._create_branch(repo, branch)
        # else:
        #     latest_sha = branch.latest_sha() # not used. right now we leave the sha for this particular file, not the latest sha for the whole branch
            # hence the code below: sha=repo_contents_info[basename]

        basename = os.path.basename(filename)
        filepath = os.path.dirname(filename)
        repo_contents_info = self._get_all_files_in_repo_at_path(repo, path=filepath, get_contents=False, branch=branch)

        if basename in repo_contents_info: # if file exists
            if not overwrite:
                print("Skipping: %-30s already exists in repository %s on branch %s." % (filename, repo.name, branch))
                return False
            else:
                if not isinstance(file_contents, bytes):
                    file_contents = bytes(file_contents, "UTF-8")

                # check if the file has actually changed
                old_contents = self._file_contents(repo, filename, ref=branch, decode=False)
                if file_contents == old_contents:
                    # print("Skipping: %-30s: the old and new files are exactly the same in repository %s on branch %s" % (filename, repo.name, branch))
                    return False
                output = repo.create_file(filename, "Update %s."%basename, file_contents, sha=repo_contents_info[basename] if repo_contents_info else None, branch=branch)
                print("Attempted to overwrite contents of %s/%s on branch %s" % (repo.name, filename, branch))
                # (above) for some reason the output seems to be None when overwriting a file, not sure why...
                # else:
                    # print("Failed to overwrite contents of %s/%s" % (repo.name, filename))
        else:
            if not isinstance(file_contents, bytes):
                file_contents = bytes(file_contents, "UTF-8")
            if repo.create_file(filename, "Create %s."%basename, file_contents, branch=branch):
                print("Successfully created new file %s/%s on branch %s" % (repo.name, filename, branch))
                return True
            else:
                print("Failed to create new file %s/%s on branch %s" % (repo.name, filename, branch))
                return False

        return True # not exactly right... ca nwe read output somehow?

    # repo: the repo
    # path: the path to the file in the repo
    # ref: the branch
    # decode: if true, *try* to decode from bytes type to string.
    def _file_contents(self, repo, path, ref=None, decode=True):
        c1 = repo.file_contents(path, ref=ref)
        if not c1:
            print("The file %s/%s does not exist." % (repo.name, path))
            return None
        c2 = base64.b64decode(c1.content)
        if not decode:
            return c2
        else:
            try:
                c3 = c2.decode("UTF-8")
            except UnicodeDecodeError: # this error got thrown for an image, for example.
                return c2
            return c3

    """ Check if repo is empty. Empty is defined as having no contents or only containing a README.md file. """
    def _repo_is_empty(self, repo, branch="master"):
        try:
            tree = repo.tree(branch)
        except github3.exceptions.ClientError:
            return True
        if len(tree.tree)==1 and tree.tree[0].path == README:
            return True
        return False


    """ Get all files in a Repository at a specific path (helper method)
        Note: if path is non-empty AND relative_path is True (advanced), it will be stripped off all file paths! in other words "path" becomes the root dir
        Note2: If get_contents=False, we return the sha instead of the actual content
        """
    def _get_all_files_in_repo_at_path(self, repo, path="", get_contents=True, relative_path=True, branch="master"):
        if path in ["/", "."]: # assume the caller means the root directory if these are used for path
            path = ""
        if path and path[0] != "/": # if path non-empty, make sure it ends with "/"
            path += "/"
        data = dict()
        try:
            tree = repo.tree("%s?recursive=1" % branch)
        except github3.exceptions.ClientError as e:
            return dict() # return empty dict because repository is empty
        tree = tree.as_dict()
        if tree['truncated']:
            print("Warning: there were too many files and not all were received through the GitHub API!")
        for elem in tree['tree']:
            if elem['path'].startswith(path):
                if elem['type'] == 'blob':
                    # get the actual contents
                    contents = base64.b64decode(repo.file_contents(elem['path']).content) if get_contents else elem['sha']
                    if relative_path:
                        data[elem['path'][len(path):]] = contents
                    else:
                        data[elem['path']] = contents
        return data

    def _create_team(self, team_name, privacy="closed"):
        if self.dry_run:
            print("DRY RUN: Now I would create a team %s" % (team_name))
            return

        if team_name in self.teams:
            print("%-30s: team already exists." % team_name)
            return self.teams[team_name] # return the team since that's what this function is expected to do

        team = self.org.create_team(team_name, privacy=privacy)
        if team:
            print('%-30s: team created.' % team_name)
            self.teams[team_name] = team
            return team
        else:
            print('Failed to create team %s' % team_name)

    def _create_repo(self, repo_name, private=True):
        if self.dry_run:
            print("DRY RUN: Now I would create a repo %s with private=%s" % (repo_name, private))
            return

        if repo_name in self.repos:
            print("Repo %s already exists... skipping." % (repo_name))
            return self.repos[repo_name] # return the repo since that's what this function is expected to do
        else:
            repo = self.org.create_repository(repo_name, private=private)
            if repo:
                print("Created %s repository %s/%s" % ("PRIVATE" if private else "PUBLIC", self.org.login, repo_name))
                self.repos[repo_name] = repo
                return repo
            else:
                print("Failed to create repository %s/%s" % (self.org.login, repo_name))

    # if donotrepeat=False, then it is OK to create an issue with the same title as an already existing issue
    def _open_issue(self, repo, title, body, donotrepeat=True, labels=None):
        if self.dry_run:
            print('DRY RUN: Now I would open an Issue entitled "%s" in repo %s' % (title, repo.name))
            return

        if donotrepeat:
            for existing_issue in repo.issues(state="open"):
                if existing_issue.title == title: # and existing_issue.as_dict()['state']=="open":
                    print('An open issue with title "%s" already exists in repo %s - skipping' % (title, repo.name))
                    return

        if repo.create_issue(title=title, body=body, labels=labels):
            print('Created issue "%s" in repository %s.' % (title, repo.name))
        else:
            print("Failed to create issue %s in repository %s." % (title, repo.name))

    def _close_issue(self, issue):
        if self.dry_run:
            print('DRY RUN: Now I would close an Issue %s' % str(issue))
            return

        attributes = issue.as_dict()
        repo_name = attributes["repository_url"].split("/")[-1]
        if issue.close():
            print("Successfully closed issue #%d in %s with title %s" % (attributes["number"], repo_name, attributes["title"]))
        else:
            print("Failed to close close issue #%d in %s with title %s" % (attributes["number"], repo_name, attributes["title"]))

    def _add_collaborator(self, repo, user, permission="push"):
        if repo is None:
            print("Could not add collaborator %s because repo is None" % user)
            return

        if self.dry_run:
            print('DRY RUN: Now I add %s as a collaborator to repo %s with permission %s' % (user, repo.name, permission))
            return

        if not self.org.is_member(user):
            print("Warning: %s is not a member of the %s organization. Proceeding anyway." % (user, self.org.name))

        if repo.name not in self.repos:
            print("Could not find Repository %s." % repo.name)
            return

        # if repo.is_collaborator(user):
        #   success_str = "Added %-15s as a Collaborator with %s access to %s." % (user, permission, repo.name)
        #   success_str =
        if repo.add_collaborator(user, permission=permission):
            print("Added %-15s as a collaborator with %s access to %s." % (user, permission, repo.name))
        else:
            print("FAILED to add %s as a Collaborator to %s." % (user, repo.name))

    def _add_repo_to_team(self, repo, team, permission="push"):
        if repo.name not in self.repos:
            print("Could not find Repository %s." % repo.name)
            return

        if self.dry_run:
            print('DRY RUN: Now I give Team %s access to repo %s with permission %s' % (team.name, repo.name, permission))
            return

        if team.add_repository(repo, permission=permission):
            print("Added Repository %-40s to Team %s with %s access" % (repo.name, team.name, permission))
        else:
            print("FAILED to add Repository %s to Team %s" % (repo.name, team.name))


    # to be used in prepare_assessment and update_assessment_via_PR
    def copy_assessment_to_students_repo(self, aname):
        ass_main_dir = os.path.split(self.course_config[aname]["main-file"])[0]
        ass_contents = self._get_all_files_in_repo_at_path(self.staff_repo, path=ass_main_dir, relative_path=False)

        # add content from course repo
        for filename, file_contents_object in ass_contents.items():
            self._create_file(self.students_repo, filename, file_contents_object, overwrite=True)

        return ass_contents

    # copy assessment to each student
    def gift_repos(self, groups, aname, branch="master", overwrite=False):
        print("Gifting %s %s to students on branch %s" % (self.config["name"], aname, branch))

        if "main-dir" in self.course_config[aname]:
            lab_main_dir = self.course_config[aname]["main-dir"]
        else:
            raise Exception("Did not find main-dir in config")
            # lab_main_dir = os.path.split(self.course_config[aname]["main-file"])[0]
        source_repo_contents = self._get_all_files_in_repo_at_path(self.staff_repo, lab_main_dir)

        for group in groups:
            # print("Gifting to %s" % group_to_pretty_str(group))
            repo_name = get_assessment_repo_name(group, self.config, aname)
            repo = self.repos[repo_name]

            # add content from course repo
            for filename, file_contents_object in source_repo_contents.items():
                self._create_file(repo, filename, file_contents_object, branch=branch, overwrite=overwrite)

            # add a README file
            readme_file_contents = '#%s\n\n%s %s for %s.\n\nTODO: improve this README file per the homework instructions.' % \
                (repo_name, self.config["name"], aname, group_to_str(group))
            self._create_file(repo, README, readme_file_contents, branch=branch, overwrite=overwrite)

    def create_updates_branches(self, groups, aname):
        for group in groups:
            repo_name = get_assessment_repo_name(group, self.config, aname)
            repo = self.repos[repo_name]

            branch = self._create_branch(repo, new_branch_name=UPDATES_BRANCH_NAME, source_branch_name="master")
            branch.protect() # don't let students delete the branch after merging
            # the first PR, as this
            # causes problems for future PRs, if the students make commits to master in between.
            # becasue UPDATES_BRANCH_NAME refers to HEAD which then has student commits, so then ALL
            # files get updated evern unchanged ones, and they revert the student commits. bad. only
            # the instructor should be making commits to this branch. not that students were before,
            # but for future PRs we were branching off a ref that included their commits

    def establish_and_save_student_groups(self, aname):
        if aname is None:
            raise Exception("Name cannot be None")

        # if self._file_exists(self.grades_repo, "%s/groups.json" % aname):
        #     print("Groups for %s already exists: returning exiting groups" % aname)
        #     return self.load_student_groups(aname)

        all_logins = set(student.login for student in self.students)

        # collect all partners
        partners = defaultdict(set)
        for student in self.students:
            repo_name = get_student_grades_repo_name(student.login, self.config)
            repo = self.repos[repo_name]

            for issue in repo.issues():
                if get_partners_issue_title(aname) in issue.title:

                    contents = issue.body
                    requested_partners = contents.strip().split(",")

                    if "max-group-size" in self.course_config[aname] and len(requested_partners) > self.course_config[aname]["max-group-size"]:
                        print("%s requested a group larger than the max group size of %d for %s... ignoring." % (student.login, self.course_config[aname]["max-group-size"], aname))
                        # do not honour the request
                        continue
                    for partner in requested_partners:
                        # if partner in all_logins: # make sure this person is an actual student
                        for lgn in all_logins:
                            if partner.lower() == lgn.lower(): # case-insensitivity, just to be nice
                                partners[student.login].add(lgn)


        # form the actual groups
        groups = list()
        for cwl in all_logins:
            if cwl in partners: # student asked for partners
                if cwl in (member for group in groups for member in group): # this student already in a group -- skip. could cache this in a sepearate set for speed.
                    # print("skipping %s because already in another group" % cwl)
                    continue

                # construct a list of the implied OVERALL GROUP implied by each student in this list
                # and make sure these overall groups agree for all students
                implied_group = partners[cwl] | {cwl}
                for partner in partners[cwl]:
                    if partner not in partners: # your request a partner but this person didn't request any partners
                        groups.append((cwl,)) # you work alone
                        print("%s requested partners but the partner %s did not request them back" % (cwl,partner))
                        break

                    if partners[partner] | {partner} != implied_group: # partners disagree on who's in the group
                        groups.append((cwl,)) # you work alone
                        print("%s requested partners but they did not reciprocate" % cwl)
                        break
                else:
                    # success!
                    groups.append(tuple(implied_group)) # use tuple instead of list in case the groups need to be hashable (as in a key of a dict)
            else:
                # the student did not request any partners
                groups.append((cwl,)) # work alone

        assert(set(member for group in groups for member in group) == all_logins)

        # save the groups to a file in the grades repo
        groups_str = json.dumps(groups, indent=4)
        self._create_file(self.grades_repo, "%s/groups.json" % aname, groups_str, overwrite=True)

        return sorted(groups, key=group_to_str)

    def load_student_groups(self, aname):
        groups_str = self._file_contents(self.grades_repo, "%s/groups.json" % aname)
        groups = json.loads(groups_str)
        groups = list(map(tuple, groups)) # change from list to tuple for the reason described above (hashable)
        groups = sorted(groups, key=group_to_str)
        return groups

    """ Create a repo for each course for each student and gift the contents """
    def prepare_assessment(self, groups, aname):
        # check the main file exists
        # this function will raise an Exception if it doesn't exist
        self.get_assessment_main_file_name(aname)

        new_groups = []
        for group in groups:

            # create repository
            repo_name = get_assessment_repo_name(group, self.config, aname)

            if repo_name in self.repos:
                print("Repo %s already exists - skipping prepare_assessment" % repo_name)
                continue

            repo = self._create_repo(repo_name, private=True)
            # repo.ignore() # ignore notifications ! otherwise all the PR merging sends lots of notifications
            # no longer doing this. workaround is to have a bot user open the PRs

            # add repo to course team

            self._add_repo_to_team(repo, self.staff_team, permission="pull") #"admin"
            # (above) "admin" allows TAs to close labs. but OTOH there's a fear of them getting too many notifications
            # if they are auto-watching repos.

            new_groups.append(group) # don't re-gift if students already have it...

        self.gift_repos(new_groups, aname)
        self.create_updates_branches(new_groups, aname) # these branches are protected

        # DO NOT call copy_assessment_to_students_repo() here!!! otherwise if you prepare a quiz in advance they will see it too early. only do once assessment is actually opened
        # too bad there's inefficiency for getting all contents twice then, but has to be done this way.

    # closely related to prepare_assessment() but for when an assessment is changed by the instructor
    def update_assessment_via_PR(self, groups, aname):

        # 1: copy new files into the update branch
        self.gift_repos(groups, aname, branch=UPDATES_BRANCH_NAME, overwrite=True)

        # 2: create a PR from the updates branch to master
        current_time = datetime.strftime(datetime.now(), '%Y-%m-%d at %H:%M')
        for group in groups:
            repo_name = get_assessment_repo_name(group, self.config, aname)
            repo = self.repos[repo_name]

            # in the rare case that the person doing `update` is not the person who did `open`
            # (only the person who did `open` is ignoring the repo up to this point)
            # repo.ignore()
            # no longer doing this. workaround is to have a bot user (this user) open the PRs; there are no notifications

            title = "An update to %s" % aname
            body = "@%s: the instructor has updated this assessment, %s %s, since its original form. Navigate to the `Files changed` tab to see what changed. You may want to merge this Pull Request. This is an automatically generated message." % \
                (" @".join(group), self.config["name"], aname)
            self._create_pull_request(repo, title, body, "master", UPDATES_BRANCH_NAME)

    """ Add students as a collaborators on their course repos """
    def add_students_as_collaborators(self, groups, aname, permission="push"):
        for group in groups:
            repo_name = get_assessment_repo_name(group, self.config, aname)
            repo = self.repos[repo_name]
            for student in group:
                self._add_collaborator(repo, student, permission=permission)


    # decided to have one per course, so that TAs can have read access (allowing them to push issues)
    # - b/c we don't want TAs to see grades from other courses
    def create_student_grades_repos_and_give_access(self):
        for student in self.students:
            # for j, course in self.course_info.iterrows():
            repo_name = get_student_grades_repo_name(student.login, self.config)
            repo = self._create_repo(repo_name, private=True)

            self._add_collaborator(repo, student.login, permission="pull")
            self._create_file(repo, README, "## %s grades for %s\n" % (self.config["name"], student.login))

    """ Give course Teams acccess to student course repos """
    def course_team_access_student_grades_repos(self):
        # for j, course in self.course_info.iterrows():

        for student in self.students:
            repo_name = get_student_grades_repo_name(student.login, self.config)
            repo = self.repos[repo_name]
            self._add_repo_to_team(repo, self.staff_team, permission="push")

    def create_instructor_grades_repo_and_grant_access(self):
        self.grades_repo = self._create_repo(self.config["grades-repo"], private=True)

        self._add_repo_to_team(self.grades_repo, self.staff_team, permission="push")

    def create_course_config_file(self, ask_human=False):
        repo = self.staff_repo

        default_config = DEFAULT_COURSE_CONFIG
        default_config_str = json.dumps(default_config, indent=4)

        config_file_already_exists = self._file_exists(repo, COURSE_CONFIG_FILENAME)
        print("===================================")
        print("|           ATTENTION             |")
        print("===================================")
        if not config_file_already_exists:
            print("No course config file found. I am copying in the **default** course config file:")
            print(default_config_str)
            config_created = self._create_file(repo, COURSE_CONFIG_FILENAME, default_config_str)
            self.course_config = default_config # set for later use
        else:
            course_config = self.course_config
            course_config_str = json.dumps(self.course_config, indent=4)
            print("Found the following course config file:")
            print(course_config_str)

        if ask_human:
            answer = input("\nIs the above config file correct for %s (yes/no)?\n" % self.config["name"])
            if answer.lower() not in ("yes", "y"):
                print("You have indicated that the config file is not correct. Please fix it and push to %s/%s, and then re-run the script to open this course." % (repo.name, COURSE_CONFIG_FILENAME))
                print("Terminating now...")
                sys.exit(0)
        else:
            print("Using the above config file.")



    def create_grades_csv(self):
        grade_mapping = self.config.get("grade-mapping", None)

        # 0. read status.json
        status_json = self._file_contents(self.grades_repo, STATUS_FILENAME)
        status_dict = json.loads(status_json)

        student_cwls = [student.login for student in self.students]
        grades_df = pd.DataFrame(index=student_cwls)

        # 1. look through assessments that are already graded
        all_graded = True
        for aname in self.course_config:
            if status_dict.get(aname, "n/a") in ("closed", "returned"):
                # exercise_grades_df = self.student_info[[GRADES_DF_INDEX]]

                # read in the weights
                weights_path = '%s/weights.json' % aname
                weights_string = self._file_contents(self.grades_repo, weights_path)
                weights = json.loads(weights_string)

                grades_dict = dict()
                individual_grades_dict = OrderedDict()

                ass_groups = self.load_student_groups(aname)
                for group in ass_groups:
                    grades_path = "%s/forms/%s.json" % (aname, group_to_str(group))
                    grades_string = self._file_contents(self.grades_repo, grades_path)
                    try:
                        student_grades = json.loads(grades_string, object_pairs_hook=OrderedDict)
                    except json.decoder.JSONDecodeError as ex:
                        print("There is a problem with the JSON for %s %s: " % (aname, group), end="")
                        print(ex)
                        # raise
                    # need to convert all these grades from one assessment into a single score
                    overall_assessment_grade = grades.calculate_single_assessment_grade_and_create_report(student_grades, weights, grade_mapping)["grade"]
                    if overall_assessment_grade is None:
                        print("It seems like %s isn't completely graded yet for %s." % (aname, group_to_str(group)))
                        continue
                    if overall_assessment_grade == 0:
                        print("Note that %s got a grade of zero on %s" % (group_to_str(group), aname))

                    else: # get average grade for each question, but only include people who actually did it in the averages
                        per_exercise_grades = grades.calculate_single_assessment_grade_and_create_report(student_grades, weights, grade_mapping)["grades"]
                        for exercise_name, grade in per_exercise_grades.items():
                            if exercise_name in individual_grades_dict:
                                individual_grades_dict[exercise_name].append(grade)
                            else:
                                individual_grades_dict[exercise_name] = [grade]

                    if CAP_INDIVIDUAL_ASSESSMENTS_AT_100:
                        overall_assessment_grade = min(overall_assessment_grade, 100)

                    for student_cwl in group: # all students get the same grade
                        grades_dict[student_cwl] = overall_assessment_grade



                grades_df = grades_df.join(pd.Series(grades_dict, name=aname))

                # get average grade for each exercise
                average_grades_dict = OrderedDict()
                for exercise_name, list_of_grades in  individual_grades_dict.items():
                    average_grades_dict[exercise_name] = np.mean(list_of_grades)

                table_list = [[exercise_name, "%.0f" % (100.0*average_grade)] for exercise_name, average_grade in average_grades_dict.items()]
                indiv_stats_table_str = tabulate_github(table_list, headers=["Exercise Name", "Average Grade"])
                self._create_file(self.grades_repo, "%s/stats.md" % aname, indiv_stats_table_str, overwrite=True)

            else:
                all_graded = False # at least one assessment was not graded

        # get overall grades
        if all_graded:
            final_grades = dict()
            for index, student_grades in grades_df.iterrows():
                final_grades[index] = grades.calculate_overall_course_grade_and_create_report(student_grades.to_dict(), self.course_config)["grade"]
            grades_df = grades_df.join(pd.Series(final_grades, name=OVERALL_GRADE_COLUMN_NAME))

        grades_csv_str = grades_df.to_csv(float_format="%.0f") # index=False

        self._create_file(self.grades_repo, "grades.csv", grades_csv_str, overwrite=True)

        # also create a file with some summary stats
        stats_table = []
        colnames = ["Assessment", "Mean", "Median", "SD", "Min", "Max"]
        for assessment_name in list(self.course_config.keys()) + [OVERALL_GRADE_COLUMN_NAME]:
            if assessment_name in grades_df:
                data = grades_df[assessment_name]
                data_nz = data[data!=0]
                stats = [data_nz.mean(), data_nz.median(), data_nz.std(), data_nz.min(), data_nz.max()] # round all these to integer for sanity
                stats_table.append([assessment_name] + list(map(lambda x: "%.0f" % x, stats)))
        stats_table_str = tabulate_github(stats_table, headers=colnames)
        stats_table_str = "## %s grade statistics\n\n" % self.config["name"] + stats_table_str

        self._create_file(self.grades_repo, "stats.md", stats_table_str, overwrite=True)


    # Create a Markdown table that will serve as the README.md file for the grades repository for a course FOR A PARTICULAR ASSESSMENT
    # report_filename is only used if report_column is True
    def create_grades_repo_readme(self, groups, aname, report_column=False, report_filename=None, get_actual_names=False):

        readme_table = []
        for i, group in enumerate(groups):

            # last_commit_sha = self.get_last_commit_before_due_date(course, aname, student)

            submission_link = self._get_url_to_repo("submission", get_assessment_repo_name(group, self.config, aname))#, particular_commit=last_commit_sha)
            form_link = "[marks form](forms/%s.json)" % group_to_str(group)
            if get_actual_names:
                actual_names = ", ".join(map(lambda m: self.members[m].refresh().name, group))
                row = [i+1, ", ".join(group), actual_names, submission_link, form_link]
            else:
                row = [i+1, ", ".join(group), submission_link, form_link]
            if report_column:
                report_link = ", ".join(map(lambda cwl: self._get_url_to_file(cwl, get_student_grades_repo_name(cwl, self.config), file_name=report_filename), group))
                row.append(report_link)
            readme_table.append(row)
        # pdb.set_trace()
        if get_actual_names:
            colnames = ["#", "Student CWL", "Student Name", "Submission Link", "Marks Form"]
        else:
            colnames = ["#", "Student CWL", "Submission Link", "Marks Form"]

        if report_column:
            colnames.append("Marks Report")
        table = tabulate_github(readme_table, headers=colnames)

        table = "# %s %s marking area\n\n" % (self.config["name"], aname) + table

        return table

    # Create a Markdown table that will serve as the README.md file for the grades repository for a course FOR THE ENTIRE COURSE
    def create_grades_repo_readme_main(self):
        # possible cases for an assessment
        # 1: no directory (not submitted)
        # 2. directory but no report column (ready for grading)
        # 3. dir with report column (graded and returned)
        # maybe want a json file to keep track instead of inferring these things. the various other functions
        # can read/write this file.

        # current_time = datetime.strftime(datetime.now(), 'on %Y-%m-%d at %H:%M:%S')
        # info_str = " by %s %s" % (self.userstr, current_time) # add this whereever
        # info_str = ""

        status_json = self._file_contents(self.grades_repo, STATUS_FILENAME)
        status_dict = json.loads(status_json)
        table = []

        for aname in self.course_config:
            if aname in status_dict:
                status = status_dict[aname]
                if status in ["closed", "returned"]:
                    col2 = "[%s](%s)" % (status, aname)
                else:
                    col2 = status
            else:
                col2 = "n/a"
            # if status not in ["unavailable", "n/a"]:
            #   col2 += info_str
            table.append([aname, col2])

        course_entry_name = self.config["name"]
        table.append([course_entry_name, status_dict.get(course_entry_name,"open")])

        colnames = ["Assessment", "Status"]
        table_str = tabulate_github(table, headers=colnames)
        table_str = "# %s marking area\n\n" % (self.config["name"]) + table_str
        self._create_file(self.grades_repo, README, table_str, overwrite=True)

    def create_instructor_grades_repo_status(self):
        status_dict = {assessment_name : "unavailable" for assessment_name in self.course_config}
        status_dict[self.config["name"]] = "open"

        file_contents = json.dumps(status_dict, indent=4)
        self._create_file(self.grades_repo, STATUS_FILENAME, file_contents)

    # update the json file in a grades repo to reflect a change
    def update_instructor_grades_repo_status(self, aname, new_status):
        status_json = self._file_contents(self.grades_repo, STATUS_FILENAME)
        status_dict = json.loads(status_json)

        if aname is None:
            key = self.config["name"]
        else:
            key = aname
        if key not in status_dict:
            print("Warning: new status dict key: %s" % key)
        elif status_dict[key] == new_status:
            print('Warning: the status of %s is already "%s"' % (key, new_status))
            return
        status_dict[key] = new_status
        new_status_json = json.dumps(status_dict)
        self._create_file(self.grades_repo, STATUS_FILENAME, new_status_json, overwrite=True)


    # we need to figure out if the main file for a lab is lab2.ipynb or lab2.Rmd or lab2.md
    # by looking into the directory contents
    # TODO: copy/pasted code -- bad
    def get_assessment_main_file_name(self, aname):
        extensions_by_priority = (".ipynb", '.Rmd', '.md', '.tex') # if md and other format both exist, use other one

        fname, ext = os.path.splitext(self.course_config[aname]["main-file"])
        if ext in extensions_by_priority:
            return self.course_config[aname]["main-file"]

        path, filename = os.path.split(self.course_config[aname]["main-file"])

        files_in_repo = self._get_all_files_in_repo_at_path(self.staff_repo, get_contents=False)

        for ext in extensions_by_priority:
            if fname+ext in files_in_repo:
                return fname+ext
        raise Exception("Error: could not find main file for %s in %s" % (fname, self.staff_repo.name))

    # decided peer review is per groups also. for one the right now it's part of the same grade form as
    # the assignment, which is per-group
    def assign_peer_reviewees(self, groups, aname):
        reviews_per_student = self.course_config[aname]["peer-review"]
        all_assignments = defaultdict(list)#defaultdict(set) # map from reviewer to reviewee(s)

        students = groups.copy()
        random.shuffle(students)

        # we treat the shuffled list of students as a circular list. and assign student n to review student n+k for all n.
        # we random select k
        N = len(students)

        if N == 1: #this probably only happens during tests
            print("Warning: only found 1 group, skipping peer review.")
            return False

        k_vals = random.sample(range(1,N), reviews_per_student)

        for k in k_vals:
            for i, reviewer in enumerate(students):
                all_assignments[reviewer].append(students[(i+k) % N])

        path = '%s/peer_review_assignments.json' % aname
        assignments_str = json.dumps(list(all_assignments.items()), indent=4)

        self._create_file(self.grades_repo, path, assignments_str)
        return True

    def load_peer_review_assignments(self, aname):
        assignments_str = self._file_contents(self.grades_repo, '%s/peer_review_assignments.json' % aname)

        if assignments_str is None:
            print("Warning: no peer review assignments found, skipping peer review.")
            return None # this only happens during testing / weird cases where there is only 1 group (but then why have peer review??)

        assignments_list_of_lists =  json.loads(assignments_str)

        # all the nonsense below here is because of groups and how we can't store things nicely in json
        # since all keys need to be strings in json. if it was individuals we could just return the output of loads
        # if we had just saved a dict above
        assignments_dict = dict()
        for reviewer_group, reviewee_group in assignments_list_of_lists:
            assignments_dict[tuple(reviewer_group)] = tuple(reviewee_group)

        return assignments_dict

    def calculate_late_days(self, group, aname):
        repo_name = get_assessment_repo_name(group, self.config, aname)
        repo = self.repos[repo_name]

        due_date_str = self.course_config[aname]["deadline"]
        due_date_obj = datetime.strptime(due_date_str, "%Y-%m-%d %H:%M").replace(tzinfo=tz.tzlocal())
        
        # find the last PushEvent
        for e in repo.events():
            # print(e.as_dict())
            if e.type == "PushEvent":
                submission_date_obj = e.created_at.astimezone(tz.tzlocal())
                break
        else:
            # if no PushEvents were available, as a backup look at commits (since times GitHub seems
            #   to not return Events, maybe they expire after some number of days?
            #   it says 90 days but I'm experiencing faster expiry...)
            cmt = next(repo.commits(number=1)) # assume this one it gives is the latest one...
            cmt_date = cmt.commit.committer["date"] 
            submission_date_obj = datetime.strptime(cmt_date, gh3_time_fmt).replace(tzinfo=tz.tzutc()).astimezone(tz.tzlocal())

            # # raise Exception("It seems there were no PushEvents for %s" % repo_name)
            # print("It seems there were no PushEvents for %s" % repo_name)
            # return {
            #    "deadline" : due_date_str,
            #    "submission": "n/a",
            #    "late days": 0
            # }

        
        submission_date_str = datetime.strftime(submission_date_obj, "%Y-%m-%d %H:%M")

        late_days = (submission_date_obj - due_date_obj).total_seconds()/3600/24
        late_days = math.ceil(late_days)
        late_days = max(0, late_days) # can't use negative late days


        return {
           "deadline" : due_date_str,
           "submission": submission_date_str,
           "late days": late_days
        }

    def notify_students_of_peer_review_assignments(self, groups, aname):
        DEFAULT_REVIEWS_DUE_DATE = "48 hours from when the lab was due"
        if "peer-review-deadline" not in self.course_config[aname]:
            response = input('\nYou have not specified "peer-review-deadline" in course_config.json. The default deadline is "%s". Is this OK? (yes/no)?\n' % DEFAULT_REVIEWS_DUE_DATE)
            if response.lower() not in ("yes", "y"):
                print('You responded "no". Exiting. Please update course_config.json and try again.')
                return
            else:
                reviews_deadline = DEFAULT_REVIEWS_DUE_DATE
        else:
            reviews_deadline = self.course_config[aname]["peer-review-deadline"]


        assignments = self.load_peer_review_assignments(aname)
        for reviewer_group in groups:
            reviewee_groups = assignments[reviewer_group]

            issue_title = "Peer review request"
            reviewer_ass_repo_name = get_assessment_repo_name(reviewer_group, self.config, aname)
            reviewer_ass_repo = self.repos[reviewer_ass_repo_name]

            urls = []
            for reviewee_group in reviewee_groups:
                rn = get_assessment_repo_name(reviewee_group, self.config, aname)
                # last_commit_sha = self.get_last_commit_before_due_date(course, aname, reviewee)
                urls.append(self._get_url_to_repo(rn, rn))#, particular_commit=last_commit_sha))


            issue_body = """@%s: for %s %s, you have been assigned to review the following: %s.\n\nInstructions:\n
- The review(s) are due **%s**.
- Please submit each review in the form of an Issue in the target repository.
- The title of your review Issue(s) must be "Peer Review".
- You must tag your %s TA(s) by including `@%s/%s` in the body of your Issue(s).
- Your review(s) will be graded using the [Peer Review rubric](https://github.com/UBC-MDS/public/blob/master/rubric/rubric_peer-review.md).
- Your review(s) are worth %.0f%% of your %s grade.
- The suggested time to complete each review is 20-30 minutes. If you don't get through everything, that's OK.""" % \
            (" @".join(reviewer_group), self.config["name"], aname, \
                " and ".join(urls), reviews_deadline, self.config["name"], self.config["org"], self.config["staff-team"], PEER_REVIEW_WEIGHT*100, aname)
            self._open_issue(reviewer_ass_repo, title=issue_title, body=issue_body)

    def create_grade_forms(self, groups, aname):

        main_file_name = self.get_assessment_main_file_name(aname)
        print("Reading rubric snippets from %s" % main_file_name)

        fcontents = self._file_contents(self.staff_repo, main_file_name)

        root, ext = os.path.splitext(main_file_name)
        doctype = "tex" if "tex" in ext else "md"
        # snipgen.concatenate_for_assignment_inner(fcontents,is_ipynb,cfg=rubric_cfg,dry=False,concatenate=False,make_eval=True,files=get_stuff_dict)
        grades_form_dict, rubric_weights = rubrics.parse_rubric_snippets(fcontents,
            peer_review = self.course_config[aname].get("peer-review", False), doctype=doctype)
        grades_form_dict[OVERALL_FEEDBACK_STR] = ""


        grades_form_str = json.dumps(grades_form_dict, indent=4)

        # repo_contents_info = self._get_all_files_in_repo_at_path(self.grades_repo, get_contents=False)
        # copy this into to grades repo, one per student
        for group in groups:
            eval_filename = "%s/forms/%s.json" % (aname, group_to_str(group))
            self._create_file(self.grades_repo, eval_filename, grades_form_str) # don't set overwrite=True here, this can overwrite grading that was done
                                                                            # (although I guess it would still be in the git history)
        readme_table = self.create_grades_repo_readme(groups, aname)
        readme_path = '%s/%s' % (aname, README)
        self._create_file(self.grades_repo, readme_path, readme_table, overwrite=True)

        # create weights.json file for this particular assessment
        weights_path = '%s/weights.json' % aname
        weights_str = json.dumps(rubric_weights, indent=4)

        self._create_file(self.grades_repo, weights_path, weights_str, overwrite=True)

    # grade reports here
    def create_overall_course_grade_reports(self, dry_run=False, ask_human=True):
        # check if we are ready to return. need to have tabulated first. and need to have returned everything
        grades_csv_str = self._file_contents(self.grades_repo, "grades.csv")
        if grades_csv_str is None:
            print("You need to tabulate first")
            return False

        status_json = self._file_contents(self.grades_repo, STATUS_FILENAME)
        status_dict = json.loads(status_json)
        for assessment_name, assessment_status in status_dict.items():
            if assessment_name != self.config["name"] and assessment_status != "returned":
                print("Failure: cannot return whole course grades until all assignments are returned. Assignment %s is currently %s." % (assessment_name, assessment_status))
                return False

        if not dry_run and ask_human:
            answer = input("\nAre you sure you want to push final course grades for %s (yes/no)?\n" % self.config["name"])
            if answer.lower() not in ("yes", "y"):
                return False

        grades_df = pd.read_csv(StringIO(grades_csv_str), index_col=0)

        for student in self.students:
            student_grades = grades_df.loc[student.login]

            md_table = grades.calculate_overall_course_grade_and_create_report(student_grades, self.course_config)["report"]

            report =  "## %s final grade report for %s\n\n" % (self.config["name"], student.login) + md_table

            if dry_run:
                report_filename = "overall_reports_dry_run/%s_final-grades-report.md" % (student["student_name"])
                self._create_file(self.grades_repo, report_filename, report, overwrite=True)
            else:
                issue_title = "%s final grade report is ready" % self.config["name"]
                stud_repo_name = get_student_grades_repo_name(student.login, self.config)
                stud_repo = self.repos[stud_repo_name]
                report_filename = "final_grade_report.md" # could also consider making this README
                self._create_file(stud_repo, report_filename, md_table, overwrite=True)
                issue_body = "Your %s final grade is now available and a report has been created in this repository. This final grade will eventually appear as your official grade on SSC." % self.config["name"]
                self._open_issue(stud_repo, title=issue_title, body=issue_body)

        # g.create_grade_reports(course, assessment_number, assessment_type, use_weights=False)
        # g.update_instructor_grades_repo_status(course, assessment_number, assessment_type, "returned")
        # g.create_grades_repo_readme_main(course)
        return True

    def create_grade_reports(self, groups, aname, score_only=True, dry_run=False, late_days=True):
        course_repo_materials = self.staff_repo
        main_file_name = self.get_assessment_main_file_name(aname)

        weights_path = '%s/weights.json' % aname
        weights_string = self._file_contents(self.grades_repo, weights_path)
        weights = json.loads(weights_string)
        # don't validate! these weights don't add to 1


        # just for making things pretty: grab the rubric snippets for all exercises (with links to images)

        fcontents = self._file_contents(course_repo_materials, main_file_name)
        is_ipynb = main_file_name.endswith(".ipynb")

        for group in groups:
            grades_path = "%s/forms/%s.json" % (aname, group_to_str(group))
            grades_string = self._file_contents(self.grades_repo, grades_path)
            grades_dict = json.loads(grades_string, object_pairs_hook=OrderedDict)

            grade_mapping = self.config.get("grade-mapping", None)
            report = grades.calculate_single_assessment_grade_and_create_report(grades_dict, weights, grade_mapping, rubric_images=None, score_only=score_only)["report"]

            if report is None:
                print("FAILURE: cannot return until all grading is finished. Please run tabulate first for more information.")
                print(group)
                sys.exit(0)
                # raise Exception("Encountered a -1 in the grade report for %s" % student["student_name"])
            # forms_path = '%s/reports/%s.md' % (directory_name, student["student_name"])
            # self._create_file(grades_repo, forms_path, report_bytes)

            if late_days:
                late_dict = self.calculate_late_days(group, aname)
                report += "\n\n"
                report += "- Assignment deadline: %s\n" % late_dict["deadline"]
                link_to_repo = self._get_url_to_repo("submission", get_assessment_repo_name(group, self.config, aname))
                report += "- Time of %s: %s\n" % (link_to_repo, late_dict["submission"])
                report += "- [Late days](https://github.ubc.ca/cpsc340/home/blob/master/homework_instructions.md#late-submissions) used on %s: **%d**\n" % (aname, late_dict["late days"])

            # next, open an issue with the report in the student repo
            for student_cwl in group:
                if dry_run:
                    report_filename = "%s/reports_dry_run/%s_grades_report.md" % (aname, student_cwl)
                    self._create_file(self.grades_repo, report_filename, report, overwrite=True)
                else:
                    issue_title = "%s %s grade report is ready" % (self.config["name"], aname)
                    stud_repo_name = get_student_grades_repo_name(student_cwl, self.config)
                    stud_repo = self.repos[stud_repo_name]
                    report_filename = "%s_grades.md" % aname
                    # print(report)
                    self._create_file(stud_repo, report_filename, report, overwrite=True)
                    issue_body = "@%s: %s is now graded and a report has been created in this repository. This is an automatically generated message." % (" @".join(group), aname)
                    self._open_issue(stud_repo, title=issue_title, body=issue_body)

        # update the README in the instructor repo to include an extra column for these reports

        status_json = self._file_contents(self.grades_repo, STATUS_FILENAME)
        status_dict = json.loads(status_json)
        make_report_column = status_dict[aname]=="returned" or not dry_run
        if status_dict[aname]=="returned": # just a weird thing that if you return it and THEN later do a dry_run, we want to leave report_column as it was.
            report_filename = "%s_grades.md" % aname

        table = self.create_grades_repo_readme(groups, aname, report_column=make_report_column, report_filename=report_filename)
        readme_path = '%s/%s' % (aname, README)
        self._create_file(self.grades_repo, readme_path, table, overwrite=True)

    # links to a repo if that repo exists, otherwise doesn't make a link
    # if show_empty = False then we don't make links to empty repos.
    def _get_url_to_repo(self, entry_name, repo_name, show_empty=False, particular_commit=None):
        if repo_name in self.repos and (show_empty or not self._repo_is_empty(self.repos[repo_name])):
            base_url = urllib.parse.urljoin(self.config["url"], self.config["org"])
            if particular_commit is None:
                repo_url = "%s/%s" % (base_url, repo_name)
            else:
                repo_url = "%s/%s/tree/%s" % (base_url, repo_name, particular_commit)
            return "[%s](%s)" % (entry_name, repo_url)
        else:
            return entry_name

    def _get_url_to_file(self, entry_name, repo_name, file_name):
        repo = self.repos[repo_name]
        if self._file_exists(repo, file_name):
            file_url = "%s/%s/blob/master/%s" % (urllib.parse.urljoin(self.config["url"], self.config["org"]), repo_name, file_name)
            return "[%s](%s)" % (entry_name, file_url)
        else:
            return entry_name

    # this is UBC-specific
    def create_grades_csv_for_fsc(self):
        final_grades = self._get_final_grades()

        df = final_grades.to_frame()
        df["Session"] = "2016W"
        df["Campus"] = "UBC"
        # df["Subject"] = "DSCI"
        # df["Course"] = course["course_number"]
        df["Section"] = "001"
        df.rename(columns={OVERALL_GRADE_COLUMN_NAME:"Percent Grade"}, inplace=True)
        df.index.names=["Student Number"] # this is the column with the student number
        df["Standing"] = ""
        df["Standing Reason"] = ""

        filename = "%s_grades_for_FSC.csv" % self.config["name"]
        with open(filename, 'w') as f:
            df.to_csv(f, float_format="%.0f")
        # self._create_file(self.repos[get_instructor_grades_repo_name(course)], filename, df.to_csv(float_format="%.0f"), overwrite=True)

        print("Successfully created %s" % filename)

    def _get_final_grades(self):
        if self.grades_repo is None:
            print("No grades repo found for %s" % self.config["name"])
            return None

        grades_csv_str = self._file_contents(self.grades_repo, "grades.csv")

        if grades_csv_str is None:
            print("No tabulated grades found for %s" % self.config["name"])
            return None

        course_grades_df = pd.read_csv(StringIO(grades_csv_str), index_col=0)

        if OVERALL_GRADE_COLUMN_NAME not in course_grades_df:
            print("No final course grades found for %s" % self.config["name"])
            return None

        course_final_grades = course_grades_df[OVERALL_GRADE_COLUMN_NAME]

        return course_final_grades

    def notify_TAs_of_closed_assessment(self, aname):
        # get list of TA(s) for this course
        # TAs = self.instructor_info[self.instructor_info["course_number"] == course["course_number"]].iloc[0]["TA"].split(";")
        issue_title = "%s is ready for grading" % (aname)
        # issue_body = "".join("@%s "%TA for TA in TAs)
        issue_body = "@%s/%s" % (self.config["org"], self.config["staff-team"])
        issue_body = issue_body.rstrip() + ": " + issue_title + ". This is an automatically generated message."
        self._open_issue(self.grades_repo, title=issue_title, body=issue_body, labels=[aname+"_grading"])

    def close_grading_issue(self, aname):
        for issue in self.grades_repo.issues(labels = aname+"_grading", state="open"):
            self._close_issue(issue)

    # this should never be empty, since the initial commit from the instructor should alwaysa be before
    # the deadline. however, one could improve this function by dealing with the case where latest_commit is none/empty.
    def get_last_commit_before_due_date(self, aname, group):

        due_date_str = self.course_config[aname]["deadline"]
        due_date_object = datetime.strptime(due_date_str, "%Y-%m-%d %H:%M")
        due_date_object_utc = due_date_object.replace(tzinfo=tz.tzlocal()).astimezone(tz.tzutc())
        # above: convert due date to utc because commits are in utc and we want to compare them to the due date

        repo = self.repos[get_assessment_repo_name(group, self.config, aname)]

        get_time_f = lambda commit: datetime.strptime(commit.commit.committer["date"], gh3_time_fmt)
        # # hopefully committer is the better choice than author?
        latest_commit = max(repo.commits(until=due_date_object_utc), key=get_time_f)

        return latest_commit.sha

        # note: in the unlikely event of two commits at the same time, i think max takes the first one. which is good because
        # i'm guessing the commits are ordered anyway? ok this is not really relevant.

    # TODO: fix this to work with multiple student teams
    def notify_students_of_open_assessment(self, aname):
        course_repo_name = self.config["students-repo"]
        course_repo = self.repos[course_repo_name]
        issue_title = "%s is now available." % aname
        issue_body = "@%s/%s: %s is now available. This is an automatically generated message; please do not reply." % (self.org.name, self.config["students-team"], aname)
        self._open_issue(course_repo, title=issue_title, body=issue_body)

def main(mode, config_filename, aname=None, dry_run=False, gh_object=None, ask_human=True):

    if gh_object is None:
        with open(config_filename, "r") as f:
            config = json.load(f)
        g = Goatcabin(config, dry_run)
    else:
        g = gh_object
        config = g.config

    # if mode ==  "tabulate" and course_number is None: # tabulate grades across courses
    #     g.tabulate_program_grades()
    #     return g

    # set the assessment type and number from the args
    if mode == "open" and aname is None: # open the course
        course_team = g.teams[config["staff-team"]]

        # dev_repo = g._create_repo(config["staff-repo"], private=True)
        dev_repo = g.repos[config["staff-repo"]]

        if dev_repo is None:
            print("ERROR: could not find repo %s in org %s" % (config["staff-repo"], g.org))

        g._add_repo_to_team(dev_repo, course_team, permission="push")
        # g._add_repo_to_team(dev_repo, g.teams["staff-team"], permission="pull")

        # g.create_course_config_file(ask_human=ask_human)

        # create _students repo
        course_repo_name = config["students-repo"]
        # course_repo = g._create_repo(course_repo_name, private=False)

        # copy README to there, if it doesn't already exist
        # README_contents = g._file_contents(dev_repo, README)
        # g._create_file(course_repo, README, README_contents, overwrite=False)

        g.create_student_grades_repos_and_give_access()
        g.course_team_access_student_grades_repos()

        # one per course so TAs cannot see grades from other courses
        g.create_instructor_grades_repo_and_grant_access()
        g.create_instructor_grades_repo_status()
        g.create_grades_repo_readme_main()

    elif mode == "calendar":
        # put lab due dates on the calendar
        g.add_due_dates_to_calendar()

    elif mode == "tabulate":
        g.create_grades_csv()

    elif mode == "return" and aname is None: # "return" a course - means send out final grade reports to the students
        g.create_grades_csv() # grade reports come from this CSV file so it's critical to re-run the tabulation
        success = g.create_overall_course_grade_reports(dry_run=dry_run)
        if success:
            g.update_instructor_grades_repo_status(None, "returned")
            g.create_grades_repo_readme_main()

    elif mode == "refresh":
        g.create_grades_repo_readme_main()

    elif mode == "fsc":
        g.create_grades_csv_for_fsc()


    elif aname is None:
        raise Exception('You must specify an assignment name with mode "%s".' % mode)





    # elif mode == "prepare": # redundant with open- but good for quizzes so that opening is swift
    #     g.prepare_assessment(groups, aname)
    # disabled for now. it's tricky because you kneed to know the groups in order to do this. but you might want to do it in advance.
    # and that's not quite right.  so just leave this feature out for now and can add it back in later if there's a "real-time" group feature
    # or if it's somehow only allowed on assessments for which max-group-size=1 (for example quizzes). that makes sense. TODO
    
    elif mode == "checkgroups":
        g.dry_run = True
        g.establish_and_save_student_groups(aname)
        
    elif mode == "open": # open a lab or quiz

        # FINALIZE THE GROUPS
        groups = g.establish_and_save_student_groups(aname)

        g.prepare_assessment(groups, aname)

        g.add_students_as_collaborators(groups, aname, permission="push")
        # g.notify_students_of_open_assessment(course, aname)
        # the above appears to be redundant. I think they get notified just for being given push access?
        # or for some other reason, it seems.

        g.update_instructor_grades_repo_status(aname, "open")
        g.create_grades_repo_readme_main()


        # for public access
        #g.copy_assessment_to_students_repo(aname) # MAKE SURE THIS DOES NOT HAPPEN WHEN A QUIZ IS BEING PREPARED!!!!!!
        # above: disabled because it's already on the public github.io website

        # # add due date to calendar
        # try:
        #     g.add_due_date_to_calendar(course, aname)
        # except:
        #     print("Failed to add deadline to MDS calendar.")
        # else:
        #     print("Added deadline to MDS calendar.")
    elif mode == 'startgrading':

        groups = g.load_student_groups(aname)

        g.create_grade_forms(groups, aname)

        # g.update_instructor_grades_repo_status(aname, "closed")
        # g.create_grades_repo_readme_main()
        # g.notify_TAs_of_closed_assessment(aname)


    elif mode == "close": # close a lab or quiz
        groups = g.load_student_groups(aname)

        g.add_students_as_collaborators(groups, aname, permission="pull") # revoke push access

        if g.course_config[aname].get("peer-review", False):
            success = g.assign_peer_reviewees(groups, aname)
            if success:
                g.notify_students_of_peer_review_assignments(groups, aname) # TODO: make sure this links to commit before due data

        g.create_grade_forms(groups, aname) # maybe need a config file in each lab directory giving the name of the "main" file?
        # make the labs visible to other students... do not do this for quizzes!

        if g.course_config[aname]["public-after-submit"]: # for now, hardcode that quizzes cannot be made public
            if "quiz" in aname or "exam" in aname:
                answer = input("\nAre you sure you want students to see each other's %s?\n" % aname)
                if answer.lower() not in ("yes", "y"):
                    return
            for group in groups:
                repo = g.repos[get_assessment_repo_name(group, g.config, aname)]
                for student_team in g.students_teams:
                    g._add_repo_to_team(repo, student_team, permission="pull")

        g.update_instructor_grades_repo_status(aname, "closed")
        g.create_grades_repo_readme_main()
        g.notify_TAs_of_closed_assessment(aname)

    elif mode == "regroup":
        g.establish_and_save_student_groups(aname)

    elif mode == "update": # update a lab via pull request if changes were made
        groups = g.load_student_groups(aname)

        # g.create_updates_branches(groups, aname)
        # above: make sure the UPDATES_BRANCH_NAME branch exists. the reason it might not exist is that the
        # student may have deleted it upon merging a previous PR in this same repo.
        # this should do nothing if the branch already exists because of how _create_branch is implemented
        # UPDATE: no longer need to do it here because
        # branch is now protected

        # g.copy_assessment_to_students_repo(aname) # this could be improved to be all in the single commit instead of a new commit for each file creation. but hopefully
        # it'll only show a commit for the files that were changed. TOOD: verify this
        g.update_assessment_via_PR(groups, aname)

    elif mode == "return": # return a lab or quiz (to be run by a TA)
        groups = g.load_student_groups(aname)

        paper_sub = g.course_config[aname].get("paper-submission", False)
        g.create_grade_reports(groups, aname, score_only=True, dry_run=False, late_days=not paper_sub) # and create README for that assessment
        g.update_instructor_grades_repo_status(aname, "returned")
        g.create_grades_repo_readme_main()
        if not dry_run:
            g.close_grading_issue(aname)
        # g.create_grades_csv() # this is slow and a little annoying sometimes.

    return g

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", default=None, type=str, help="The path to the JSON config file.")
    parser.add_argument("mode", help="What needs to be done?", choices=['open', 'update', 'checkgroups', 'startgrading', 'close', 'regroup', 'tabulate', 'return', 'update', 'refresh', 'calendar', 'fsc'])
    parser.add_argument("--name", default=None, type=str, help="The name of the assessment (see course_config.json).")
    parser.add_argument("--dry", action="store_true", help="If present, reports are not pushed but just made internally.")
    args = parser.parse_args()

    main(args.mode, args.config, aname=args.name, dry_run=args.dry)
