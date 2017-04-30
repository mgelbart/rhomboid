import re
import json
import yaml
from collections import OrderedDict
from utils import validate_weights, PEER_REVIEW_WEIGHT
import pdb

DEFAULT_GRADES_FORM_SYMBOL = "FILL_THIS_IN_WITH_GRADE"
BONUS_ALIAS = "Spark (bonus)"
def check_for_bonus(exercise_name):
    return "optional" in exercise_name.lower() or "bonus" in exercise_name.lower()


update_finder = re.compile("rub(r(ic)?)? *[=:]? *({.*})")

header_finder_tex = re.compile(r'(?:sub?:)*section(?:\*?:)?.*')
header_finder = re.compile("# .*")

# TODO: just look on the previous line, instead of insisting on this
def extract_exercise_name(text, location, doctype="md"):
    #find name by scanning through file for headers:

    if doctype == "md":
        m_header_l = reversed(header_finder.findall(text[:location]))
        m_first = next(m_header_l)
        if m_first is not None:
            return m_first.lstrip().lstrip("#").lstrip().rstrip().replace("\\n","").replace("\"","").rstrip(",").replace('\\"','"').replace('"','\\"') # m_first[2:]

    elif doctype == "tex":
        m_header_l = reversed(header_finder_tex.findall(text[:location]))
        m_first = next(m_header_l)
        if m_first is not None:
            return m_first.lstrip().lstrip("section").lstrip("*").lstrip(r'{').lstrip().rstrip().replace("\\n","").replace("\"","").rstrip(",").replace('\\"','"').replace('"','\\"').rstrip(r'}')

    return "Untitled Exercise"

with open("rubric_config.json", 'r') as f:
    rubric_config = json.load(f)

# make sure weights add up to 1 for any rubrics that have weighted sub-rubrics.
for rubric_name, cfg in rubric_config.items():
    if "rows" in cfg:
        validate_weights(cfg["rows"])


# we use yaml.load instead of json.loads because
# the snippets are in the form
#   {code:1}
# rather than
#   {"code":1}
# yaml handles this.
def loadsnippet(snip):
    return yaml.load(snip.replace("\t","").replace(":"," : "))

"""
Parse the rubric snippets from a homework file. Generate a JSON form for the TA to fill out,
and also get the weights.
"""
def parse_rubric_snippets(text, peer_review=False, doctype="md"):

    grades_form = OrderedDict()
    weights = OrderedDict() # the relative weights of the different questions
    total_points = 0

    for m in update_finder.finditer(text): # for each exercise in the assignment
        snippet_str = m.group(3)
        # if (is_ipynb):
            # snippet_str=snippet_str.replace("\\t","\t").replace('\\"','"')
        snippet_dict = loadsnippet(snippet_str)

        # deal with exercise name
        if "name" not in snippet_dict: # you can manually specify the name of an exercise inside of a snippet!
            exercise_name = extract_exercise_name(text, m.start(), doctype=doctype)
        else:
            exercise_name = snippet_dict["name"]
            del snippet_dict["name"]

        if exercise_name in grades_form:
            raise Exception('The exercise name "%s" appears more than once in the assessment file. Please fix.' % exercise_name)

        grades_form_inner, weights_inner, total_points_inner = parse_rubric_snippets_inner(snippet_dict, rubric_config, exercise_name) # inner loop for exercise

        grades_form[exercise_name] = grades_form_inner
        weights[exercise_name] = weights_inner
        total_points += total_points_inner

    # add peer review
    if peer_review:
        d = OrderedDict()
        d["Peer Review"] = DEFAULT_GRADES_FORM_SYMBOL
        d["feedback"] = ""
        # d[snipgen.BONUS_ALIAS] = 0
        grades_form["PEER REVIEW"] = d
        # later, can personalize forms so it says who review is of. but that means not just one
        # json_form_str for all students
        peer_review_points = total_points*PEER_REVIEW_WEIGHT/(1-PEER_REVIEW_WEIGHT) # a little more correct than just total_points*PEER_REVIEW_WEIGHT
        # PR pts / (other pts + PR PTS) = PEER_REVIEW_WEIGHT
        # PR pts = PEER_REVIEW_WEIGHT * other pts + PEER_REVIEW_WEIGHT PR PTS
        # PR pts (1-PEER_REVIEW_WEIGHT) = PEER_REVIEW_WEIGHT * other pts
        # PR pts  = PEER_REVIEW_WEIGHT/(1-PEER_REVIEW_WEIGHT) * other pts
        peer_review_points = round(peer_review_points, 2) # round to 1 or 2 decimal place for sanity
        weights["PEER REVIEW"] = {"Peer Review" : peer_review_points}

    return grades_form, weights

# for a single exercise, put all the rubrics together -- different rubrics and different rows in a rubric
# input is the little snippet inside a homework assignment (dict)
# and the rubric_config (dict)
# output is another dict that represents the part of the grade form *for that exercise*
def parse_rubric_snippets_inner(rubr, rubric_config, exercise_name):

    grades_form_inner = OrderedDict()
    weights_inner = OrderedDict()
    total_points_inner = 0

    for rubric_name, rubric_num_points in rubr.items():
        try:
            rubric_num_points = float(rubric_num_points)
        except ValueError:
            print("Failed to convert %s to a float. This is supposed to be the number of points for a rubric." % rubric_num_points)
            raise

        total_points_inner += rubric_num_points
        if rubric_name == "spark":
            raise Exception('We decided to stop accepting "spark" as an explicit rubric. Please made this question optional instead, for example by adding "optional" to its name.')

        elif rubric_name in rubric_config:
            rubric_display_name = rubric_config[rubric_name]["name"]
            if "rows" in rubric_config[rubric_name]: # this is a multi-row rubric
                for rubric_row_name, rubric_row_weight in rubric_config[rubric_name]["rows"].items():
                    grades_form_inner[": ".join((rubric_display_name, rubric_row_name))] = DEFAULT_GRADES_FORM_SYMBOL
                    weights_inner[": ".join((rubric_display_name, rubric_row_name))] = round(rubric_row_weight * rubric_num_points, 5) # round to avoid numerical issues making ugly outputs

            else: # this is a single-row rubic. We get the display name from the rubric_config dict.
                grades_form_inner[rubric_display_name] = DEFAULT_GRADES_FORM_SYMBOL
                weights_inner[rubric_display_name] = rubric_num_points

        else:
            raise Exception('Unrecognized rubric "%s" in Exercise "%s".' % (rubric_name, rubr["exercise name"]))

    grades_form_inner["feedback"] = ""

   # hacky dealing with bonus questions
    if check_for_bonus(exercise_name):
        print("Found bonus question: %s" % exercise_name)
        grades_form_inner["is_bonus"] = True # currently unused, just FYI
        weights_inner["is_bonus"] = True # this one is used later on
    else:
        # TODO: maybe this in a config file for the course, whether or not
        USE_BONUS = False
        # if it's not a bonus question, allow for the TA to give bonus points
        if USE_BONUS:
            grades_form_inner[BONUS_ALIAS] = 0
            weights_inner[BONUS_ALIAS] = 1

    return grades_form_inner, weights_inner, total_points_inner
