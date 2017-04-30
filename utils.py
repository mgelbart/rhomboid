from tabulate import tabulate
import json
import os
from collections import OrderedDict


STATUS_FILENAME = "status.json"
README = "README.md"
OVERALL_GRADE_COLUMN_NAME = "Course Grade"
UPDATES_BRANCH_NAME = "instructor-updates"
OVERALL_FEEDBACK_STR = "Overall feedback"
CAP_INDIVIDUAL_ASSESSMENTS_AT_100 = False
PEER_REVIEW_WEIGHT = 0.15 # peer review should be worth 15% of any assessment that is being reviewed

COURSE_CONFIG_FILENAME = "course_config.json"
RUBRIC_CONFIG_FILENAME = os.path.join("rubric", "rubric_config.json")
DEFAULT_COURSE_CONFIG_FILENAME = "default_course_config.json"

if not os.path.isfile(DEFAULT_COURSE_CONFIG_FILENAME):
    raise Exception("There must be a file named %s in the current directory." % DEFAULT_COURSE_CONFIG_FILENAME)
else:
    with open(DEFAULT_COURSE_CONFIG_FILENAME, 'r') as f:
        DEFAULT_COURSE_CONFIG = json.load(f, object_pairs_hook=OrderedDict)

def group_to_pretty_str(group):
	return ", ".join(map(user_to_str, group))

def user_to_str(user):
	return "%s (%s)" % (user.login, user.name) if user.name else user.login

def validate_weights(weights):
    assert(abs(sum(weights.values()) - 1.0) < 1e-6)
# validate_weights(DEFAULT_OVERALL_WEIGHTS)

def get_course_name(course):
    return course["name"]
    # return '_'.join(('DSCI', str(course['course_number']), course['slug']))

def group_to_str(group):
    return "_".join(sorted(group))

# ASSESSMENTS = [("lab", 1), ("lab", 2), ("lab", 3), ("lab", 4), ("quiz", 1), ("quiz", 2)]

def get_assessment_repo_name(group, course, assname):
    if "repo-prefix" in course:
        return "%s_%s_%s" % (course["repo-prefix"], group_to_str(group), assname)
    else:
        return "%s_%s" % (group_to_str(group), assname)


def get_partners_issue_title(assname):
    return "%s_partner" % assname

def get_partners_file_name(assname):
    return "%s_partner.md" % assname
    
def get_student_grades_repo_name(cwl, course):
    if "repo-prefix" in course:
        return "%s_grades_%s" % (course["repo-prefix"], cwl)
    else:
        return "%s_grades" % cwl

def tabulate_github(table, headers):
    return tabulate(table, headers=headers, tablefmt="orgtbl").replace("-+-", "-|-")
